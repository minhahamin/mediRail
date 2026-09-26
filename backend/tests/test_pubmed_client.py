"""PubMed 클라이언트/서버: 네트워크 없이 httpx.MockTransport로 검증."""
import json

import httpx
import pytest

from mcp_servers.pubmed import server
from mcp_servers.pubmed.client import PubMedClient, PubMedError, parse_articles

XML = """<?xml version="1.0"?>
<PubmedArticleSet>
 <PubmedArticle>
  <MedlineCitation><PMID Version="1">11111111</PMID>
   <Article>
    <Journal><JournalIssue><PubDate><Year>2021</Year></PubDate></JournalIssue><Title>Lancet Test</Title></Journal>
    <ArticleTitle>Warfarin plus <i>aspirin</i> and bleeding.</ArticleTitle>
    <Abstract>
      <AbstractText Label="BACKGROUND">Bleeding is common.</AbstractText>
      <AbstractText Label="RESULTS">Risk ratio 1.5 (95% CI 1.2-1.9).</AbstractText>
    </Abstract>
    <AuthorList>
      <Author><LastName>Kim</LastName><Initials>H</Initials></Author>
      <Author><LastName>Lee</LastName><Initials>J</Initials></Author>
      <Author><LastName>Park</LastName><Initials>S</Initials></Author>
      <Author><LastName>Choi</LastName><Initials>M</Initials></Author>
    </AuthorList>
    <PublicationTypeList><PublicationType>Meta-Analysis</PublicationType><PublicationType>Journal Article</PublicationType></PublicationTypeList>
   </Article>
  </MedlineCitation>
  <PubmedData><ArticleIdList><ArticleId IdType="pubmed">11111111</ArticleId><ArticleId IdType="doi">10.1000/xyz</ArticleId></ArticleIdList></PubmedData>
 </PubmedArticle>
 <PubmedArticle>
  <MedlineCitation><PMID Version="1">22222222</PMID>
   <Article>
    <Journal><JournalIssue><PubDate><MedlineDate>2019 Jan-Feb</MedlineDate></PubDate></JournalIssue><Title>Old Journal</Title></Journal>
    <ArticleTitle>No abstract paper</ArticleTitle>
    <AuthorList><Author><CollectiveName>Some Consortium</CollectiveName></Author></AuthorList>
   </Article>
  </MedlineCitation>
 </PubmedArticle>
</PubmedArticleSet>"""


class Recorder:
    """호출 기록 + 시나리오 응답."""

    def __init__(self, ids=("11111111", "22222222"), fail_first_with=None):
        self.requests, self.ids, self.fail = [], list(ids), fail_first_with

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.fail and len(self.requests) == 1:
            return httpx.Response(self.fail)
        if request.url.path.endswith("esearch.fcgi"):
            return httpx.Response(200, json={"esearchresult": {"count": str(len(self.ids) + 100), "idlist": self.ids}})
        return httpx.Response(200, text=XML)


def make(rec=None, **kw):
    rec = rec or Recorder()
    slept = []
    c = PubMedClient(http=httpx.Client(transport=httpx.MockTransport(rec)), sleep=slept.append, **kw)
    return c, rec, slept


# ---------- 파싱 ----------
def test_parse_articles_fields():
    a, b = parse_articles(XML)
    assert a["pmid"] == "11111111" and a["year"] == "2021" and a["journal"] == "Lancet Test"
    assert a["title"] == "Warfarin plus aspirin and bleeding."                     # 인라인 태그 제거
    assert a["abstract"] == "BACKGROUND: Bleeding is common. RESULTS: Risk ratio 1.5 (95% CI 1.2-1.9)."
    assert a["authors"] == ["Kim H", "Lee J", "Park S", "et al."] and a["doi"] == "10.1000/xyz"
    assert a["pub_types"] == ["Meta-Analysis", "Journal Article"]
    assert a["url"] == "https://pubmed.ncbi.nlm.nih.gov/11111111/"
    assert b["year"] == "2019" and b["abstract"] == "(초록 없음)" and b["authors"] == ["Some Consortium"]  # MedlineDate, 단체 저자


def test_parse_invalid_xml():
    with pytest.raises(PubMedError):
        parse_articles("<broken")


def test_abstract_is_truncated():
    long_xml = XML.replace("Bleeding is common.", "x" * 3000)
    assert len(parse_articles(long_xml)[0]["abstract"]) <= 1502


# ---------- 검색 ----------
def test_search_builds_requests_and_refs():
    c, rec, _ = make(email="me@example.com")
    r = c.search("warfarin aspirin", max_results=2)
    assert r["total_found"] == 102 and r["returned"] == 2 and r["refs"] == ["PMID:11111111", "PMID:22222222"]
    es, ef = rec.requests
    assert es.url.params["db"] == "pubmed" and es.url.params["term"] == "warfarin aspirin" and es.url.params["retmax"] == "2"
    assert es.url.params["tool"] == "medirail" and es.url.params["email"] == "me@example.com" and "api_key" not in es.url.params
    assert ef.url.params["id"] == "11111111,22222222"


def test_api_key_is_sent_when_configured():
    c, rec, _ = make(api_key="K123")
    c.search("aspirin")
    assert rec.requests[0].url.params["api_key"] == "K123"


def test_recent_years_filter():
    c, rec, _ = make()
    c.search("aspirin", recent_years=5)
    p = rec.requests[0].url.params
    assert p["datetype"] == "pdat" and p["reldate"] == str(5 * 365)


def test_max_results_is_clamped():
    c, rec, _ = make()
    c.search("aspirin", max_results=999)
    assert rec.requests[0].url.params["retmax"] == "10"


def test_no_results_skips_efetch():
    c, rec, _ = make(Recorder(ids=[]))
    r = c.search("zzzz nonexistent")
    assert r["articles"] == [] and r["refs"] == [] and len(rec.requests) == 1


def test_repeated_query_is_cached():
    c, rec, _ = make()
    c.search("Aspirin ")
    c.search("aspirin")  # 대소문자·공백 무시
    assert len(rec.requests) == 2  # esearch + efetch 한 번씩만


@pytest.mark.parametrize("q", ["", "   ", "x" * 301])
def test_invalid_query_rejected(q):
    c, rec, _ = make()
    with pytest.raises(PubMedError):
        c.search(q)
    assert rec.requests == []


def test_invalid_sort_rejected():
    with pytest.raises(PubMedError):
        make()[0].search("aspirin", sort="random")


# ---------- 단건 조회 ----------
def test_get_article_and_validation():
    c, _, _ = make(Recorder(ids=["11111111"]))
    a = c.get_article("11111111")
    assert a["pmid"] == "11111111" and a["refs"] == ["PMID:11111111"]
    for bad in ("abc", "1; DROP", "", "1234567890"):
        with pytest.raises(PubMedError):
            c.get_article(bad)


# ---------- 안정성 ----------
def test_rate_limit_sleeps_between_requests():
    c, _, slept = make()
    c._clock = lambda: 100.0  # 시간이 흐르지 않는 상황 → 매 요청 전 최소 간격만큼 대기
    c.search("aspirin")
    assert len(slept) == 1 and abs(slept[0] - 0.34) < 1e-6  # esearch 직후 efetch 앞에서 한 번 대기


def test_retries_on_429_then_succeeds():
    c, rec, slept = make(Recorder(fail_first_with=429))
    assert c.search("aspirin")["returned"] == 2
    assert len(rec.requests) == 3 and any(s >= 1.5 for s in slept)


def test_http_error_becomes_pubmed_error():
    c, _, _ = make(Recorder(fail_first_with=500))
    with pytest.raises(PubMedError, match="500"):
        c.search("aspirin")


def test_network_failure_becomes_pubmed_error():
    def boom(request):
        raise httpx.ConnectError("down")
    c = PubMedClient(http=httpx.Client(transport=httpx.MockTransport(boom)), sleep=lambda s: None)
    with pytest.raises(PubMedError, match="연결"):
        c.search("aspirin")


# ---------- MCP 서버 도구 ----------
def test_server_tools_wrap_client(monkeypatch):
    c, _, _ = make()
    monkeypatch.setattr(server, "_client", c)
    r = server.search_pubmed("warfarin", max_results=2)
    assert r["refs"] == ["PMID:11111111", "PMID:22222222"]
    assert server.get_pubmed_article("11111111")["pmid"] == "11111111"


def test_server_converts_errors_to_tool_error(monkeypatch):
    from mcp.server.mcpserver.exceptions import ToolError
    monkeypatch.setattr(server, "_client", make()[0])
    with pytest.raises(ToolError):
        server.search_pubmed("")


def test_server_registers_both_tools():
    import asyncio
    tools = asyncio.run(server.mcp.list_tools())
    names = {t.name for t in (tools.tools if hasattr(tools, "tools") else tools)}
    assert names == {"search_pubmed", "get_pubmed_article"}
