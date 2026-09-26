"""식약처 의약품안전사용서비스(DUR) 품목정보 클라이언트 (공공데이터포털 OpenAPI).

실제 API를 탐색해 확인한 특성과 대응
- 데이터는 (품목 A, 품목 B) 쌍 단위로 약 80만 행이다. 성분명 필터가 없고 itemName / itemSeq / ingrCode만 먹는다.
  → 대표 품목 하나의 행을 모두 받아 성분 쌍으로 dedupe한다.
- numOfRows가 500을 넘으면 오류 없이 0건을 돌려준다. → 500으로 고정하고, 받은 행 수가 totalCount와 다르면 실패 처리한다.
- 인증/한도 오류는 type=json이어도 XML로 온다. → 파싱해 사람이 읽을 수 있는 메시지로 바꾼다.
- 성분 표기가 제각각이다(클래리트로마이신/클래리스로마이신). → 한글·영문명 모두 매칭하고, 못 찾으면 상대 성분 목록을 돌려준다.
- 쌍당 조회가 느리다. → 행 수가 적은 쪽을 펼치고, 페이지는 병렬로 받고, 결과는 SQLite에 캐시한다(30일).

주의: DUR '병용금기' 고시 목록에 없다는 것이 안전하다는 뜻은 아니다. 모든 결과에 그 고지를 포함한다.
"""
import difflib
import json
import re
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import unquote

import httpx

BASE = "https://apis.data.go.kr/1471000/DURPrdlstInfoService03"
PAGE = 500
TTL = 30 * 86400
MAX_CANDIDATES = 60
FUZZY = 0.85  # 표기 오류(클라리스↔클래리스 등)는 0.88, 서로 다른 약물은 0.6 이하로 갈린다

OP_PAIR = "getUsjntTabooInfoList03"
CATEGORIES = {  # 단일 약물 안전 정보
    "임부금기": "getPwnmTabooInfoList03",
    "노인주의": "getOdsnAtentInfoList03",
    "특정연령대금기": "getSpcifyAgrdeTabooInfoList03",
    "용량주의": "getCpctyAtentInfoList03",
    "투여기간주의": "getMdctnPdAtentInfoList03",
    "효능군중복": "getEfcyDplctInfoList03",
}
NOTICE = ("식약처 DUR '병용금기' 고시 목록 기준입니다. 목록에 없다고 해서 병용이 안전하다는 뜻이 아니며, "
          "주의가 필요한 상호작용은 이 목록에 없을 수 있습니다. 최종 판단은 의사·약사가 합니다.")


class DurError(Exception):
    """사용자/LLM에게 그대로 보여줄 수 있는 오류 (API 키는 절대 포함하지 않는다)."""


def norm(s) -> str:
    return re.sub(r"[\s()\[\]·\-]", "", (s or "")).lower()


def name_match(query: str, *names: str) -> bool:
    """부분 일치(양방향). 제피과립·고체분산체 같은 제형 접미사 변형과 한글/영문 표기를 함께 잡는다."""
    q = norm(query)
    if len(q) < 2:
        return False
    for n in map(norm, names):
        if n and (q in n or (len(n) >= 3 and n in q)):
            return True
    return False


def similar_partners(query: str, pairs: list[dict]) -> list[dict]:
    """표기가 거의 같은 상대 성분. 놓치는 것(미탐)이 과경고보다 위험하므로 높은 임계값으로 자동 매칭하고 그 사실을 결과에 남긴다."""
    q = norm(query)
    if len(q) < 4:
        return []
    return [p for p in pairs if p["partner"] and difflib.SequenceMatcher(None, q, norm(p["partner"])).ratio() >= FUZZY]


class DurClient:
    def __init__(self, service_key: str | None, http: httpx.Client | None = None, cache_path: str | None = None,
                 clock=time.time, workers: int = 4):
        if not service_key:
            raise DurError("식약처 API 키(DATA_GO_KR_API_KEY)가 설정되지 않았습니다")
        self.key = unquote(service_key) if "%" in service_key else service_key  # 포털의 'Encoding' 키를 받아도 이중 인코딩되지 않게
        self.http = http or httpx.Client(timeout=30)
        self.cache_path, self._clock, self._workers = cache_path, clock, workers
        self._mem: dict = {}
        self._lock = threading.Lock()

    # ---------- 캐시 ----------
    def _db(self):
        con = sqlite3.connect(self.cache_path)
        con.execute("CREATE TABLE IF NOT EXISTS dur_cache (k TEXT PRIMARY KEY, ts REAL, v TEXT)")
        return con

    def _cached(self, key: str, compute):
        with self._lock:
            hit = self._mem.get(key)
            if hit and self._clock() - hit[0] < TTL:
                return hit[1]
        if self.cache_path:
            con = self._db()
            try:
                row = con.execute("SELECT ts, v FROM dur_cache WHERE k=?", (key,)).fetchone()
            finally:
                con.close()
            if row and self._clock() - row[0] < TTL:
                val = json.loads(row[1])
                with self._lock:
                    self._mem[key] = (row[0], val)
                return val
        val = compute()
        now = self._clock()
        with self._lock:
            self._mem[key] = (now, val)
        if self.cache_path:
            con = self._db()
            try:
                con.execute("INSERT OR REPLACE INTO dur_cache VALUES (?,?,?)", (key, now, json.dumps(val, ensure_ascii=False)))
                con.commit()
            finally:
                con.close()
        return val

    # ---------- HTTP ----------
    def _explain(self, msg: str) -> str:
        m = msg.upper()
        if "NOT REGISTERED" in m:
            return "서비스 키가 아직 등록되지 않았습니다 (활용 승인 직후에는 반영까지 1시간 정도 걸릴 수 있습니다)"
        if "LIMITED" in m or "EXCEED" in m:
            return "식약처 API 일일 호출 한도를 초과했습니다"
        if "DEADLINE" in m or "EXPIRED" in m:
            return "서비스 키의 사용 기간이 만료되었습니다"
        return f"식약처 API 오류: {msg[:80]}"

    def _call(self, op: str, page: int = 1, rows: int = PAGE, **filters) -> tuple[int, list[dict]]:
        params = {"serviceKey": self.key, "pageNo": page, "numOfRows": min(rows, PAGE), "type": "json", **filters}
        last = None
        for attempt in range(2):
            try:
                r = self.http.get(f"{BASE}/{op}", params=params)
            except httpx.HTTPError as e:
                last = type(e).__name__
                if attempt == 0:
                    time.sleep(0.5)
                continue
            if r.status_code >= 500 and attempt == 0:
                continue
            break
        else:
            raise DurError(f"식약처 API에 연결할 수 없습니다 ({last})")
        if r.status_code != 200:
            raise DurError(f"식약처 API 응답 오류 (HTTP {r.status_code})")
        text = r.text.strip()
        if text.startswith("<"):
            m = re.search(r"<(?:returnAuthMsg|errMsg|resultMsg)>([^<]+)", text)
            raise DurError(self._explain(m.group(1) if m else "알 수 없는 응답"))
        try:
            j = r.json()
        except ValueError:
            raise DurError("식약처 API 응답을 해석할 수 없습니다")
        code = (j.get("header") or {}).get("resultCode")
        if code not in (None, "00"):
            raise DurError(self._explain(str((j.get("header") or {}).get("resultMsg", code))))
        body = j.get("body") or {}
        items = body.get("items") or []
        if isinstance(items, dict):
            items = items.get("item", [])
        return int(body.get("totalCount") or 0), items

    # ---------- 품목/성분 해석 ----------
    def resolve(self, name: str, categories: tuple[str, ...] = ("병용금기",)) -> dict | None:
        name = (name or "").strip()
        if len(norm(name)) < 2:
            raise DurError("약물명은 2자 이상이어야 합니다")

        def compute():
            for cat in categories:
                op = OP_PAIR if cat == "병용금기" else CATEGORIES[cat]
                _, items = self._call(op, rows=50, itemName=name)
                if not items:
                    continue
                q = norm(name)
                best = max(items, key=lambda x: (x.get("MIX", x.get("MIX_TYPE")) == "단일",
                                                 q in norm(x.get("INGR_KOR_NAME") or x.get("INGR_NAME")),
                                                 q in norm(x.get("INGR_ENG_NAME"))))
                out = {"item_seq": best["ITEM_SEQ"], "item_name": best["ITEM_NAME"], "category": cat,
                       "ingredient": best.get("INGR_KOR_NAME") or best.get("INGR_NAME") or "",
                       "ingredient_eng": best.get("INGR_ENG_NAME") or ""}
                if cat == "병용금기":
                    out["rows"] = self._call(OP_PAIR, rows=1, itemSeq=best["ITEM_SEQ"])[0]
                return out
            return None
        return self._cached(f"resolve:{norm(name)}:{','.join(categories)}", compute)

    def partners(self, item_seq: str) -> dict:
        """대표 품목의 병용금기 상대 성분 목록 (성분 쌍 단위 dedupe)."""
        def compute():
            total, rows = self._call(OP_PAIR, itemSeq=item_seq)
            pages = -(-total // PAGE)
            if pages > 1:
                with ThreadPoolExecutor(self._workers) as ex:
                    for chunk in ex.map(lambda p: self._call(OP_PAIR, page=p, itemSeq=item_seq)[1], range(2, pages + 1)):
                        rows += chunk
            if len(rows) != total:  # 페이지 크기 초과 등으로 조용히 잘린 응답을 완전한 결과로 오해하지 않는다
                raise DurError(f"식약처 API 응답이 불완전합니다 ({len(rows)}/{total}행)")
            seen: dict = {}
            for x in rows:
                reason = (x.get("PROHBT_CONTENT") or "").strip()
                k = (x.get("MIXTURE_INGR_KOR_NAME") or "", reason)
                seen.setdefault(k, {"partner": k[0], "partner_eng": x.get("MIXTURE_INGR_ENG_NAME") or "", "reason": reason,
                                    "notified": x.get("NOTIFICATION_DATE") or "", "ingredient": x.get("INGR_KOR_NAME") or ""})
            return {"total_rows": total, "pairs": list(seen.values())}
        return self._cached(f"partners:{item_seq}", compute)

    # ---------- 공개 API ----------
    def check_interaction(self, drug_a: str, drug_b: str) -> dict:
        a, b = (drug_a or "").strip(), (drug_b or "").strip()
        ra, rb = self.resolve(a), self.resolve(b)
        base = {"drug_a": {"input": a, "resolved": ra and {"ingredient": ra["ingredient"], "ingredient_eng": ra["ingredient_eng"]}},
                "drug_b": {"input": b, "resolved": rb and {"ingredient": rb["ingredient"], "ingredient_eng": rb["ingredient_eng"]}},
                "source": "식약처 DUR 품목정보 병용금기", "notice": NOTICE}
        if not ra and not rb:
            return {**base, "status": "unresolved", "contraindications": [],
                    "hint": "두 약물 모두 DUR 병용금기 데이터에서 찾지 못했습니다. 성분명을 식약처 표기(한글)로 다시 시도하세요. 목록에 없는 것이 안전을 뜻하지는 않습니다."}
        sides = sorted([s for s in ((ra, b), (rb, a)) if s[0]], key=lambda s: s[0]["rows"])  # 행 수가 적은 쪽부터 (빠름)
        checked, candidates = [], []
        for item, other in sides:
            pairs = self.partners(item["item_seq"])["pairs"]
            checked.append(item["ingredient"])
            hits, match = [p for p in pairs if name_match(other, p["partner"], p["partner_eng"])], "exact"
            if not hits:
                hits, match = similar_partners(other, pairs), "similar_spelling"
            if hits:
                out = {**base, "status": "contraindicated", "checked_from": item["ingredient"], "match_type": match,
                       "contraindications": [{"ingredient": h["ingredient"], "partner": h["partner"], "partner_eng": h["partner_eng"],
                                              "reason": h["reason"] or "(사유 미기재)", "notified": h["notified"]} for h in hits[:10]],
                       "refs": [f"DUR:병용금기:{hits[0]['ingredient']}×{hits[0]['partner']}"]}
                if match == "similar_spelling":
                    out["match_note"] = (f"입력한 '{other}'와 표기가 비슷한 성분({', '.join(sorted({h['partner'] for h in hits})[:3])})으로 매칭했습니다. "
                                         "같은 성분인지 확인하세요. 같은 성분이라면 병용금기입니다.")
                return out
            if not candidates:
                candidates = sorted({p["partner"] for p in pairs if p["partner"]})
        out = {**base, "status": "not_listed", "contraindications": [], "checked_from": checked,
               "listed_partners": {"of": sides[0][0]["ingredient"], "names": candidates[:MAX_CANDIDATES],
                                   "meaning": f"{sides[0][0]['ingredient']}와(과) 병용금기로 고시된 성분 전체 목록입니다. 사용자가 말한 약물이 (다른 표기나 계열명으로) 이 목록에 있으면 병용금기이므로 그 이름으로 다시 조회하세요."},
               "hint": "listed_partners.names에 사용자가 말한 약물의 다른 표기·계열 성분이 있는지 확인하세요 (예: 질산염 → 니트로글리세린). 전혀 없다면 병용금기 고시 목록에 없는 것이지 안전하다는 뜻이 아닙니다."}
        unresolved = [n for n, r in ((a, ra), (b, rb)) if not r]
        if unresolved:
            out["unresolved"] = unresolved
        similar = difflib.get_close_matches(norm(b if sides[0][0] is ra else a), [norm(c) for c in candidates], n=3, cutoff=0.6)
        if similar:
            out["similar_names"] = [c for c in candidates if norm(c) in similar][:3]
        return out

    def drug_safety(self, drug: str) -> dict:
        drug = (drug or "").strip()
        if len(norm(drug)) < 2:
            raise DurError("약물명은 2자 이상이어야 합니다")

        def compute():
            found, ingredient = {}, ""
            for cat, op in CATEGORIES.items():
                _, items = self._call(op, rows=50, itemName=drug)
                q = norm(drug)
                mine = [x for x in items if q in norm(x.get("INGR_NAME")) or q in norm(x.get("INGR_ENG_NAME")) or q in norm(x.get("ITEM_NAME"))]
                if not mine:
                    continue
                ingredient = ingredient or mine[0].get("INGR_NAME") or ""
                notes = sorted({(x.get("PROHBT_CONTENT") or x.get("REMARK") or "").strip()[:400] for x in mine} - {""})
                found[cat] = {"applicable": True, "notes": notes[:3], "matched_items": len(mine)}
                if cat == "특정연령대금기":
                    found[cat]["age_note"] = "해당 연령대(소아·노인 등)는 이 API에 포함되어 있지 않습니다. 연령을 임의로 추정하지 말고 허가사항을 확인해야 합니다."
            return {"ingredient": ingredient, "categories": found}
        r = self._cached(f"safety:{norm(drug)}", compute)
        return {"drug": drug, **r, "source": "식약처 DUR 품목정보",
                "checked_categories": list(CATEGORIES),
                "not_flagged": [c for c in CATEGORIES if c not in r["categories"]],
                "notice": "해당 범주에 표시되지 않은 항목은 DUR 고시에 없다는 뜻이며 안전을 보증하지 않습니다. 최종 판단은 의사·약사가 합니다.",
                "refs": [f"DUR:{c}:{r['ingredient'] or drug}" for c in r["categories"]]}
