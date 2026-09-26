"""NCBI E-utilities 기반 PubMed 클라이언트.

- 키 없이도 동작한다 (초당 3회 제한). NCBI_API_KEY가 있으면 초당 10회까지 올린다.
- 요청 간격 제한, 429 재시도, 결과 캐시(TTL), 입력 검증을 포함한다.
- MCP와 무관한 순수 라이브러리다. server.py가 이를 MCP 도구로 감싼다.
"""
import re
import threading
import time
import xml.etree.ElementTree as ET

import httpx

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
MAX_QUERY_LEN = 300
MAX_RESULTS = 10
ABSTRACT_LIMIT = 1500  # LLM 컨텍스트 절약
CACHE_TTL = 3600


class PubMedError(Exception):
    """사용자/LLM에게 그대로 보여줄 수 있는 오류."""


class PubMedClient:
    def __init__(self, api_key: str | None = None, email: str | None = None, http: httpx.Client | None = None,
                 sleep=time.sleep, clock=time.monotonic):
        self.api_key, self.email = api_key or None, email or None
        self.http = http or httpx.Client(timeout=20)
        self._interval = 0.11 if self.api_key else 0.34
        self._last = 0.0
        self._lock = threading.Lock()
        self._sleep, self._clock = sleep, clock
        self._cache: dict = {}

    # ---------- HTTP ----------
    def _get(self, endpoint: str, params: dict) -> httpx.Response:
        params = {**params, "tool": "medirail", "email": self.email, "api_key": self.api_key}
        params = {k: v for k, v in params.items() if v is not None}
        for attempt in range(3):
            with self._lock:  # NCBI 이용 제한 준수: 요청 간 최소 간격
                wait = self._interval - (self._clock() - self._last)
                if wait > 0:
                    self._sleep(wait)
                self._last = self._clock()
            try:
                r = self.http.get(f"{BASE}/{endpoint}", params=params)
            except httpx.HTTPError as e:
                raise PubMedError(f"PubMed에 연결할 수 없습니다: {type(e).__name__}")
            if r.status_code == 429 and attempt < 2:
                self._sleep(1.5 * (attempt + 1))
                continue
            if r.status_code != 200:
                raise PubMedError(f"PubMed 응답 오류 (HTTP {r.status_code})")
            return r
        raise PubMedError("PubMed 요청 한도를 초과했습니다. 잠시 후 다시 시도하세요")

    def _cached(self, key, fn):
        hit = self._cache.get(key)
        if hit and self._clock() - hit[0] < CACHE_TTL:
            return hit[1]
        val = fn()
        self._cache[key] = (self._clock(), val)
        return val

    # ---------- 공개 API ----------
    def search(self, query: str, max_results: int = 5, recent_years: int | None = None, sort: str = "relevance") -> dict:
        query = (query or "").strip()
        if not query:
            raise PubMedError("검색어가 비어 있습니다")
        if len(query) > MAX_QUERY_LEN:
            raise PubMedError(f"검색어는 {MAX_QUERY_LEN}자 이하여야 합니다")
        max_results = max(1, min(int(max_results), MAX_RESULTS))
        if sort not in ("relevance", "pub_date"):
            raise PubMedError("sort는 'relevance' 또는 'pub_date'여야 합니다")
        return self._cached(("s", query.lower(), max_results, recent_years, sort),
                            lambda: self._search(query, max_results, recent_years, sort))

    def _search(self, query, max_results, recent_years, sort) -> dict:
        p = {"db": "pubmed", "term": query, "retmax": max_results, "retmode": "json", "sort": sort}
        if recent_years:
            p |= {"datetype": "pdat", "reldate": int(recent_years) * 365}
        data = self._get("esearch.fcgi", p).json().get("esearchresult", {})
        ids = data.get("idlist", [])
        total = int(data.get("count", 0))
        articles = self._fetch(ids) if ids else []
        return {"query": query, "total_found": total, "returned": len(articles), "articles": articles,
                "refs": [f"PMID:{a['pmid']}" for a in articles]}

    def get_article(self, pmid: str) -> dict:
        pmid = str(pmid).strip()
        if not re.fullmatch(r"\d{1,9}", pmid):
            raise PubMedError("PMID는 숫자여야 합니다")
        arts = self._cached(("a", pmid), lambda: self._fetch([pmid]))
        if not arts:
            raise PubMedError(f"PMID {pmid}에 해당하는 논문을 찾을 수 없습니다")
        return {**arts[0], "refs": [f"PMID:{pmid}"]}

    def _fetch(self, ids: list[str]) -> list[dict]:
        r = self._get("efetch.fcgi", {"db": "pubmed", "id": ",".join(ids), "retmode": "xml", "rettype": "abstract"})
        return parse_articles(r.text)


# ---------- XML 파싱 ----------
def _text(el) -> str:
    """하위 태그(<i>, <sup> 등)까지 포함한 텍스트."""
    return re.sub(r"\s+", " ", "".join(el.itertext())).strip() if el is not None else ""


def _year(article) -> str:
    for path in ("MedlineCitation/Article/Journal/JournalIssue/PubDate/Year", "MedlineCitation/Article/ArticleDate/Year"):
        y = article.findtext(path)
        if y:
            return y
    m = re.search(r"\d{4}", article.findtext("MedlineCitation/Article/Journal/JournalIssue/PubDate/MedlineDate") or "")
    return m.group(0) if m else ""


def parse_articles(xml_text: str) -> list[dict]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        raise PubMedError("PubMed 응답을 해석할 수 없습니다")
    out = []
    for art in root.iter("PubmedArticle"):
        pmid = art.findtext("MedlineCitation/PMID") or ""
        parts = []
        for at in art.findall("MedlineCitation/Article/Abstract/AbstractText"):
            label, txt = at.get("Label"), _text(at)
            parts.append(f"{label}: {txt}" if label and txt else txt)
        abstract = " ".join(p for p in parts if p)
        authors = []
        for a in art.findall("MedlineCitation/Article/AuthorList/Author"):
            name = " ".join(x for x in (a.findtext("LastName"), a.findtext("Initials")) if x) or a.findtext("CollectiveName")
            if name:
                authors.append(name)
        doi = next((_text(i) for i in art.findall("PubmedData/ArticleIdList/ArticleId") if i.get("IdType") == "doi"), "")
        out.append({
            "pmid": pmid,
            "title": _text(art.find("MedlineCitation/Article/ArticleTitle")),
            "journal": art.findtext("MedlineCitation/Article/Journal/Title") or "",
            "year": _year(art),
            "authors": authors[:3] + (["et al."] if len(authors) > 3 else []),
            "pub_types": [_text(t) for t in art.findall("MedlineCitation/Article/PublicationTypeList/PublicationType")],
            "abstract": abstract[:ABSTRACT_LIMIT] + ("…" if len(abstract) > ABSTRACT_LIMIT else "") if abstract else "(초록 없음)",
            "doi": doi,
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        })
    return out
