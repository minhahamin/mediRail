"""식약처 의약품안전사용서비스(DUR) **성분정보** 클라이언트 (공공데이터포털 OpenAPI).

설계 (실제 API를 탐색해 확인한 사실 기반)
- 성분서비스는 병용금기가 1,836행(성분 쌍)뿐이다. 품목서비스는 79만 행(품목 쌍)이라 쌍당 수 초가 걸렸다.
  → 카테고리별 전체 데이터를 한 번(약 3초) 받아 **로컬 인덱스**로 쓰고, 이후 조회는 즉시 응답한다. 결과는 SQLite에 30일 캐시한다.
- 데이터에는 삭제된 항목(DEL_YN=삭제)이 섞여 있다(병용금기 65행). → 반드시 제외한다.
- 병용금기 쌍은 한쪽 방향으로만 등재된 경우가 많다(양방향 대칭 16%). → 항상 양방향으로 검색한다.
- numOfRows가 500을 넘으면 오류 없이 빈 응답이 온다. → 500으로 고정하고, 받은 행 수가 totalCount와 다르면 실패 처리한다.
- 응답 항목이 {"item": {...}}로 감싸져 있고, 오류는 XML 또는 HTTP 400 JSON으로 온다. → 모두 해석해 읽을 수 있는 메시지로 바꾼다(키는 절대 노출하지 않는다).
- 성분 표기가 제각각이다(클래리트로마이신/클라리스로마이신). 한글·영문 부분 일치까지는 확정 매칭한다. 표기만 비슷한 이름은 자모 유사도로 후보를 찾되,
  같은 약의 다른 표기와 다른 약(로바스타틴~로수바스타틴 0.92)을 유사도로는 구분할 수 없으므로 **확정하지 않고 needs_confirmation으로** 결과와 후보를 함께 돌려준다.
- 상품명(타이레놀 등)은 품목서비스로 성분명(아세트아미노펜)을 찾아 변환한다.

주의: DUR '병용금기'는 고시된 금기 등급만 담는다. 목록에 없다는 것이 안전하다는 뜻은 아니다. 모든 결과에 그 고지를 포함한다.
"""
import difflib
import json
import re
import sqlite3
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import unquote

import httpx

ING = "https://apis.data.go.kr/1471000/DURIrdntInfoService03"
PRD = "https://apis.data.go.kr/1471000/DURPrdlstInfoService03"
PAGE = 500
TTL = 30 * 86400
FUZZY = 0.85  # 자모 단위 유사도. 표기 변형(클라리스↔클래리트)은 0.89지만 다른 약(로바스타틴↔로수바스타틴)도 0.92라 후보 제시용으로만 쓴다
MAX_PARTNERS = 60
SCHEMA_VERSION = "v2"

PAIR = "병용금기"
OPS = {
    "병용금기": "getUsjntTabooInfoList02",
    "임부금기": "getPwnmTabooInfoList02",
    "특정연령대금기": "getSpcifyAgrdeTabooInfoList02",
    "노인주의": "getOdsnAtentInfoList02",
    "용량주의": "getCpctyAtentInfoList02",
    "투여기간주의": "getMdctnPdAtentInfoList02",
}
SINGLE = [c for c in OPS if c != PAIR]
NOTICE = ("식약처 DUR '병용금기' 고시 목록 기준입니다. 목록에 없다고 해서 병용이 안전하다는 뜻이 아니며, "
          "주의가 필요한 상호작용은 이 목록에 없을 수 있습니다. 최종 판단은 의사·약사가 합니다.")


class DurError(Exception):
    """사용자/LLM에게 그대로 보여줄 수 있는 오류 (API 키는 절대 포함하지 않는다)."""


def norm(s) -> str:
    return re.sub(r"[\s()\[\]·\-]", "", (s or "")).lower()


def name_match(query: str, *names: str) -> bool:
    """부분 일치(양방향). 염·제형 접미사 변형과 한글/영문 표기를 함께 잡는다."""
    q = norm(query)
    if len(q) < 2:
        return False
    return any(n and (q in n or (len(n) >= 3 and n in q)) for n in map(norm, names))


def jamo_ratio(a: str, b: str) -> float:
    """한글을 자모로 분해해 비교한다. 글자 단위(0.75)보다 표기 변형(ㅏ↔ㅐ, ㅅ↔ㅌ)을 정확히 잡는다(0.89)."""
    return difflib.SequenceMatcher(None, unicodedata.normalize("NFD", a), unicodedata.normalize("NFD", b)).ratio()


def _clean(s) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


class DurClient:
    def __init__(self, service_key: str | None, http: httpx.Client | None = None, cache_path: str | None = None,
                 clock=time.time, workers: int = 4):
        if not service_key:
            raise DurError("식약처 API 키(DATA_GO_KR_API_KEY)가 설정되지 않았습니다")
        self.key = unquote(service_key) if "%" in service_key else service_key  # 포털의 'Encoding' 키도 이중 인코딩되지 않게
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
        key = f"{SCHEMA_VERSION}:{key}"
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
        if "NOT REGISTERED" in m or "미등록" in msg:
            return "서비스 키가 아직 등록되지 않았습니다 (활용 승인 직후에는 반영까지 1시간 정도 걸릴 수 있습니다)"
        if "LIMITED" in m or "EXCEED" in m or "초과" in msg:
            return "식약처 API 일일 호출 한도를 초과했습니다"
        if "NO_OPENAPI_SERVICE" in m or "폐기" in msg:
            return "해당 식약처 OpenAPI 서비스를 찾을 수 없습니다 (서비스 활용 신청·승인 여부를 확인하세요)"
        if "DEADLINE" in m or "EXPIRED" in m:
            return "서비스 키의 사용 기간이 만료되었습니다"
        return f"식약처 API 오류: {msg[:80]}"

    def _call(self, base: str, op: str, page: int = 1, rows: int = PAGE, **filters) -> tuple[int, list[dict]]:
        params = {"serviceKey": self.key, "pageNo": page, "numOfRows": min(rows, PAGE), "type": "json", **filters}
        last = None
        for attempt in range(2):
            try:
                r = self.http.get(f"{base}/{op}", params=params)
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
        text = r.text.strip()
        if text.startswith("<"):  # 인증/한도 오류는 XML로 온다
            m = re.search(r"<(?:returnAuthMsg|errMsg|resultMsg)>([^<]+)", text)
            raise DurError(self._explain(m.group(1) if m else "알 수 없는 응답"))
        try:
            j = r.json()
        except ValueError:
            raise DurError(f"식약처 API 응답을 해석할 수 없습니다 (HTTP {r.status_code})")
        hdr = (j.get("OpenAPI_ServiceResponse") or {}).get("cmmMsgHeader")  # HTTP 400 JSON 오류 형식
        if hdr:
            raise DurError(self._explain(f"{hdr.get('errMsg', '')} {hdr.get('returnAuthMsg', '')}"))
        if r.status_code != 200:
            raise DurError(f"식약처 API 응답 오류 (HTTP {r.status_code})")
        code = (j.get("header") or {}).get("resultCode")
        if code not in (None, "00"):
            raise DurError(self._explain(str((j.get("header") or {}).get("resultMsg", code))))
        body = j.get("body") or {}
        items = body.get("items") or []
        if isinstance(items, dict):
            items = items.get("item", [])
        items = [x["item"] if isinstance(x, dict) and "item" in x else x for x in items]  # {"item": {...}} 래퍼 해제
        return int(body.get("totalCount") or 0), items

    # ---------- 데이터셋 (전체를 받아 로컬 인덱스로) ----------
    def _dataset(self, category: str) -> list[dict]:
        def compute():
            op = OPS[category]
            total, rows = self._call(ING, op)
            pages = -(-total // PAGE)
            if pages > 1:
                with ThreadPoolExecutor(self._workers) as ex:
                    for chunk in ex.map(lambda p: self._call(ING, op, page=p)[1], range(2, pages + 1)):
                        rows += chunk
            if len(rows) != total:  # 조용히 잘린 응답을 완전한 결과로 오해하지 않는다
                raise DurError(f"식약처 API 응답이 불완전합니다 ({category}: {len(rows)}/{total}행)")
            out = []
            for x in rows:
                if (x.get("DEL_YN") or "정상") != "정상":  # 삭제된 고시는 제외
                    continue
                if category == PAIR:
                    out.append({"a": x.get("INGR_KOR_NAME") or "", "a_eng": x.get("INGR_ENG_NAME") or "", "a_code": x.get("INGR_CODE") or "",
                                "b": x.get("MIXTURE_INGR_KOR_NAME") or "", "b_eng": x.get("MIXTURE_INGR_ENG_NAME") or "",
                                "b_code": x.get("MIXTURE_INGR_CODE") or "", "reason": _clean(x.get("PROHBT_CONTENT")),
                                "remark": _clean(x.get("REMARK")), "notified": x.get("NOTIFICATION_DATE") or ""})
                else:
                    out.append({"kor": x.get("INGR_NAME") or "", "eng": x.get("INGR_ENG_NAME") or "", "code": x.get("INGR_CODE") or "",
                                "reason": _clean(x.get("PROHBT_CONTENT")), "remark": _clean(x.get("REMARK")), "notified": x.get("NOTIFICATION_DATE") or "",
                                "age_base": _clean(x.get("AGE_BASE")), "max_qty": _clean(x.get("MAX_QTY")),
                                "max_term": _clean(x.get("MAX_DOSAGE_TERM")), "grade": _clean(x.get("GRADE"))})
            return out
        return self._cached(f"ds:{category}", compute)

    def _entries(self, category: str) -> list[dict]:
        """카테고리 데이터셋의 고유 성분 (code, kor, eng)."""
        rows = self._dataset(category)
        seen: dict = {}
        for r in rows:
            if category == PAIR:
                seen.setdefault(r["a_code"], (r["a_code"], r["a"], r["a_eng"]))
                seen.setdefault(r["b_code"], (r["b_code"], r["b"], r["b_eng"]))
            else:
                seen.setdefault(r["code"], (r["code"], r["kor"], r["eng"]))
        return [{"code": c, "kor": k, "eng": e} for c, k, e in seen.values()]

    @staticmethod
    def _match(query: str, entries: list[dict]) -> tuple[list[dict], str]:
        """이름 → 성분. exact > partial > similar_spelling 순으로 시도한다."""
        q = norm(query)
        if len(q) < 2:
            return [], "none"
        exact = [e for e in entries if q in (norm(e["kor"]), norm(e["eng"]))]
        if exact:
            return exact, "exact"
        partial = [e for e in entries if name_match(query, e["kor"], e["eng"])]
        if partial:
            return partial, "partial"
        if len(q) >= 4:
            scored = sorted(((jamo_ratio(q, norm(e["kor"])), e) for e in entries), key=lambda t: -t[0])
            sim = [e for r, e in scored[:3] if r >= FUZZY]
            if sim:
                return sim, "similar_spelling"
        return [], "none"

    def _brand_ingredients(self, name: str) -> list[str]:
        """상품명 → 성분명. 품목서비스의 품목명 끝 괄호(예: 타이레놀정500밀리그람(아세트아미노펜))에서 추출한다."""
        def compute():
            _, items = self._call(PRD, "getDurPrdlstInfoList03", rows=10, itemName=name)
            out = []
            for it in items:
                m = re.search(r"\(([^()]+)\)\s*$", it.get("ITEM_NAME") or "")
                if m:
                    out += [p.strip() for p in re.split(r"[,/]", m.group(1)) if p.strip()]
            return list(dict.fromkeys(out))[:4]
        return self._cached(f"brand:{norm(name)}", compute)

    def _resolve(self, name: str, entries: list[dict]) -> dict:
        found, mtype = self._match(name, entries)
        via = None
        if not found:  # 상품명일 수 있으니 품목서비스로 성분을 찾아 다시 매칭
            for ing in self._brand_ingredients(name):
                found, mtype = self._match(ing, entries)
                if found:
                    via = f"품목명 '{name}' → 성분 '{ing}'"
                    break
        return {"input": name, "entries": found, "match_type": mtype if found else "none", "via": via}

    # ---------- 공개 API ----------
    def check_interaction(self, drug_a: str, drug_b: str) -> dict:
        a, b = _clean(drug_a), _clean(drug_b)
        if len(norm(a)) < 2 or len(norm(b)) < 2:
            raise DurError("약물명은 2자 이상이어야 합니다")
        pairs, ents = self._dataset(PAIR), self._entries(PAIR)
        ra, rb = self._resolve(a, ents), self._resolve(b, ents)

        def summary(r):
            return {"input": r["input"], "matched": [e["kor"] for e in r["entries"]][:5] or None,
                    "match_type": r["match_type"], **({"via": r["via"]} if r["via"] else {})}

        base = {"drug_a": summary(ra), "drug_b": summary(rb), "source": "식약처 DUR 성분정보 병용금기", "notice": NOTICE}
        ca, cb = {e["code"] for e in ra["entries"]}, {e["code"] for e in rb["entries"]}
        hits = [r for r in pairs if (r["a_code"] in ca and r["b_code"] in cb) or (r["a_code"] in cb and r["b_code"] in ca)]  # 양방향
        similar = [r for r in (ra, rb) if r["match_type"] == "similar_spelling"]
        if hits:
            uniq = {}
            for h in hits:
                uniq.setdefault((h["a"], h["b"], h["reason"]), h)
            weakest = max((ra["match_type"], rb["match_type"]), key=["exact", "partial", "similar_spelling"].index)
            out = {**base, "status": "needs_confirmation" if similar else "contraindicated", "match_type": weakest,
                   "contraindications": [{"ingredient": h["a"], "partner": h["b"], "reason": h["reason"] or "(사유 미기재)",
                                          "remark": h["remark"] or None, "notified": h["notified"]} for h in list(uniq.values())[:12]],
                   "refs": [f"DUR:병용금기:{hits[0]['a']}×{hits[0]['b']}"]}
            if similar:
                out["confirm"] = [{"input": r["input"], "candidates": [e["kor"] for e in r["entries"]]} for r in similar]
                out["match_note"] = ("입력한 이름은 DUR에 없고, 표기가 비슷한 성분으로 조회한 결과입니다: "
                                     + ", ".join(f"'{r['input']}' ≈ {', '.join(e['kor'] for e in r['entries'])}" for r in similar)
                                     + ". 같은 성분(표기만 다름)인지 다른 약인지 판단하세요. 같은 성분이면 이 결과는 병용금기이므로 후보의 정확한 이름으로 다시 조회해 확정하고, "
                                       "다른 약이면 이 결과는 해당하지 않습니다.")
            elif weakest == "partial":
                out["match_note"] = ("입력한 이름의 일부만 일치하는 성분(염·제형 표기 차이)으로 조회했습니다: "
                                     + ", ".join(f"'{r['input']}' → {', '.join(e['kor'] for e in r['entries'][:3])}" for r in (ra, rb) if r["match_type"] == "partial"))
            return out
        if not ra["entries"] and not rb["entries"]:
            return {**base, "status": "unresolved", "contraindications": [],
                    "hint": "두 약물 모두 DUR 병용금기 데이터에서 찾지 못했습니다. 성분명(한글, 식약처 표기)으로 다시 시도하세요. 목록에 없는 것이 안전을 뜻하지는 않습니다."}
        out = {**base, "status": "not_listed", "contraindications": [],
               "in_dur_list": {a: bool(ra["entries"]), b: bool(rb["entries"])},
               "hint": "두 성분 사이의 병용금기는 고시 목록에 없습니다. 목록에 없다는 것이 안전하다는 뜻은 아닙니다."}
        if similar:  # 유사 표기 후보는 있으나 금기 쌍은 없음: 후보를 알려 재조회하게 한다
            out["did_you_mean"] = [{"input": r["input"], "candidates": [e["kor"] for e in r["entries"]]} for r in similar]
        unresolved = [r["input"] for r in (ra, rb) if not r["entries"]]
        if unresolved:  # 한쪽을 못 찾았을 때만 상대 목록을 보여줘 LLM이 계열명(예: 질산염→니트로글리세린)으로 재조회하게 한다
            known = ra if ra["entries"] else rb
            codes = {e["code"] for e in known["entries"]}
            partners = sorted({r["b"] if r["a_code"] in codes else r["a"] for r in pairs if r["a_code"] in codes or r["b_code"] in codes})
            of = known["entries"][0]["kor"]
            out["unresolved"] = unresolved
            out["listed_partners"] = {"of": of, "names": partners[:MAX_PARTNERS],
                                      "meaning": f"{of}와(과) 병용금기로 고시된 성분 전체 목록입니다. 사용자가 말한 약물이 (다른 표기나 계열명으로) 이 목록에 있으면 병용금기이므로 그 이름으로 다시 조회하세요."}
            out["hint"] = (f"'{', '.join(unresolved)}'는 DUR 병용금기 성분 목록에서 찾지 못했습니다. listed_partners.names에 같은 계열의 성분이 있는지 확인해 그 이름으로 다시 조회하세요. "
                           "전혀 없다면 고시 목록에 없는 것이지 안전하다는 뜻이 아닙니다.")
        return out

    def drug_safety(self, drug: str) -> dict:
        drug = _clean(drug)
        if len(norm(drug)) < 2:
            raise DurError("약물명은 2자 이상이어야 합니다")
        found, ingredient, via = {}, "", None
        for cat in SINGLE:
            res = self._resolve(drug, self._entries(cat))
            if not res["entries"]:
                continue
            codes = {e["code"] for e in res["entries"]}
            rows = [r for r in self._dataset(cat) if r["code"] in codes]
            ingredient = ingredient or res["entries"][0]["kor"]
            via = via or res["via"]
            item = {"applicable": True, "notes": sorted({r["reason"] or r["remark"] for r in rows if r["reason"] or r["remark"]})[:3]}
            for field in ("age_base", "max_qty", "max_term", "grade"):
                vals = sorted({r[field] for r in rows if r[field]})
                if vals:
                    item[field] = vals[:5]
            found[cat] = item
        pair_res = self._resolve(drug, self._entries(PAIR))
        partners = []
        if pair_res["entries"]:
            codes = {e["code"] for e in pair_res["entries"]}
            ingredient = ingredient or pair_res["entries"][0]["kor"]
            partners = sorted({r["b"] if r["a_code"] in codes else r["a"] for r in self._dataset(PAIR) if r["a_code"] in codes or r["b_code"] in codes})
        return {"drug": drug, "ingredient": ingredient, **({"resolved_via": via} if via else {}), "categories": found,
                "not_flagged": [c for c in SINGLE if c not in found],
                "contraindicated_partners": {"count": len(partners), "names": partners[:MAX_PARTNERS]},
                "source": "식약처 DUR 성분정보",
                "notice": "해당 범주에 표시되지 않은 항목은 DUR 고시에 없다는 뜻이며 안전을 보증하지 않습니다. 최종 판단은 의사·약사가 합니다.",
                "refs": [f"DUR:{c}:{ingredient or drug}" for c in found]}
