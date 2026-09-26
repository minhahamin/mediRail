"""문헌 검색(MCP) 통합: 권한, 출처/PMID 검증, 오류 처리. 실제 MCP 서버·네트워크 없이 가짜 브리지로 검증."""
import pytest

from app import agent, mcp_bridge, services, tools
from app.guardrails import check_output
from app.rbac import has_permission
from tests.test_agent import FakeLLM, u

PAPERS = {"query": "warfarin aspirin", "total_found": 120, "returned": 2,
          "articles": [{"pmid": "11111111", "title": "Bleeding with warfarin plus aspirin", "year": "2021",
                        "pub_types": ["Meta-Analysis"], "abstract": "RR 1.5"},
                       {"pmid": "22222222", "title": "Another", "year": "2019", "pub_types": ["Review"], "abstract": "x"}],
          "refs": ["PMID:11111111", "PMID:22222222"]}


class FakeBridge:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result or PAPERS, error, []

    def call(self, server, tool, arguments, timeout=45):
        self.calls.append((server, tool, arguments))
        if self.error:
            raise self.error
        return self.result


@pytest.fixture
def bridge(monkeypatch):
    b = FakeBridge()
    monkeypatch.setattr(mcp_bridge, "get_bridge", lambda: b)
    return b


# ---------- 권한 ----------
def test_only_clinicians_can_search_literature():
    assert has_permission("doctor", "literature.search") and has_permission("nurse", "literature.search")
    assert not has_permission("patient", "literature.search") and not has_permission("admin", "literature.search")


@pytest.mark.parametrize("role,expected", [("doctor", True), ("nurse", True), ("patient", False), ("admin", False)])
def test_tool_exposure_by_role(role, expected):
    assert ("search_medical_literature" in {t.name for t in tools.tools_for(role)}) is expected


def test_patient_call_is_denied_even_if_llm_tries(conn, bridge):
    res = tools.execute(conn, u(conn, "patient1"), "search_medical_literature", {"query": "aspirin"})
    assert res.denied and bridge.calls == []


# ---------- 도구 ----------
def test_tool_calls_pubmed_via_mcp_and_returns_refs(conn, bridge):
    res = tools.execute(conn, u(conn, "doctor1"), "search_medical_literature",
                        {"query": "warfarin aspirin", "max_results": 50, "recent_years": 5})
    assert res.ok and res.refs == ("PMID:11111111", "PMID:22222222") and "2건" in res.title
    assert bridge.calls == [("pubmed", "search_pubmed", {"query": "warfarin aspirin", "max_results": 8, "recent_years": 5})]  # 상한 8


def test_audit_records_search_without_query_text(conn, bridge):
    tools.execute(conn, u(conn, "doctor1"), "search_medical_literature", {"query": "김하늘 환자 페니실린 알레르기"})
    log = services.read_audit(conn, u(conn, "admin1"))
    hit = next(r for r in log if r["action"] == "literature.search")
    assert "김하늘" not in hit["detail"] and "q_len=" in hit["detail"]


def test_mcp_tool_error_is_shown_as_service_error(conn, monkeypatch):
    monkeypatch.setattr(mcp_bridge, "get_bridge", lambda: FakeBridge(error=mcp_bridge.McpToolError("검색어가 비어 있습니다")))
    res = tools.execute(conn, u(conn, "doctor1"), "search_medical_literature", {"query": " "})
    assert not res.ok and res.error == "검색어가 비어 있습니다"


def test_mcp_outage_degrades_gracefully(conn, monkeypatch):
    monkeypatch.setattr(mcp_bridge, "get_bridge", lambda: FakeBridge(error=mcp_bridge.McpError("MCP 통신 실패")))
    res = tools.execute(conn, u(conn, "nurse1"), "search_medical_literature", {"query": "aspirin"})
    assert not res.ok and "일시적으로" in res.error


# ---------- PMID 검증 ----------
S = [{"id": "D1", "title": "PubMed 검색", "refs": ["PMID:11111111"]}]


def test_known_pmid_passes():
    r = check_output("2021년 메타분석(PMID 11111111)에서 출혈 위험이 증가했습니다 [D1].", S)
    assert "invalid_pmid" not in r.events and "11111111" in r.text


def test_invented_pmid_is_blocked():
    r = check_output("PMID 99999999 논문에 따르면 안전합니다 [D1].", S)
    assert "invalid_pmid" in r.events and "99999999" not in r.text


def test_pmid_format_variants_are_caught():
    for text in ("(PMID: 98765432)", "PMID:98765432", "pmid 98765432"):
        assert "invalid_pmid" in check_output(text, S).events


def test_pmid_mentioned_by_user_may_be_echoed():
    r = check_output("PMID 99999999는 확인할 수 없습니다.", [], user_text="PMID 99999999 논문 요약해줘")
    assert "invalid_pmid" not in r.events


# ---------- 에이전트 흐름 ----------
def test_agent_literature_flow_with_valid_pmid(conn, bridge):
    llm = FakeLLM(("tool", "search_medical_literature", {"query": "warfarin aspirin bleeding"}),
                  ("say", "2021년 메타분석(PMID 11111111)에서 병용 시 출혈 위험이 증가했습니다 [D1]. 개별 환자 적용은 의사 판단이 필요합니다."))
    r = agent.run_agent(conn, u(conn, "doctor1"), "와파린과 아스피린 병용 출혈 위험 문헌 찾아줘", llm=llm)
    assert r.sources[0]["refs"] == ["PMID:11111111", "PMID:22222222"] and "invalid_pmid" not in r.events
    assert "11111111" in r.answer


def test_agent_blocks_hallucinated_pmid(conn, bridge):
    bad = ("say", "PMID 55555555 연구에서 아스피린 병용은 출혈이 없다고 보고했습니다 [D1].")
    llm = FakeLLM(("tool", "search_medical_literature", {"query": "warfarin"}), bad, bad)
    r = agent.run_agent(conn, u(conn, "doctor1"), "문헌 근거 알려줘", llm=llm)
    assert "invalid_pmid" in r.events and "55555555" not in r.answer


def test_source_without_refs_keeps_original_shape(conn):
    llm = FakeLLM(("tool", "get_clinic_info", {}), ("say", "일요일은 휴진입니다 [D1]."))
    r = agent.run_agent(conn, u(conn, "patient1"), "일요일 진료?", llm=llm)
    assert r.sources == [{"id": "D1", "title": "MediRail 클리닉 안내(가상)"}]
