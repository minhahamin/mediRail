"""약물 조회(식약처 DUR MCP) 통합: 권한, 감사 로그, 오류 처리, '안전' 단정 차단. 가짜 브리지로 검증."""
import pytest

from app import agent, mcp_bridge, services, tools
from app.guardrails import check_output
from tests.test_agent import FakeLLM, u
from tests.test_literature import FakeBridge

CONTRA = {"status": "contraindicated", "source": "식약처 DUR 품목정보 병용금기", "notice": "목록 기준...",
          "contraindications": [{"ingredient": "심바스타틴", "partner": "클래리트로마이신", "reason": "근병증, 횡문근융해의 위험증가", "notified": "20090303"}],
          "refs": ["DUR:병용금기:심바스타틴×클래리트로마이신"]}
NOT_LISTED = {"status": "not_listed", "contraindications": [], "notice": "목록 기준...",
              "listed_partners": {"of": "실데나필", "names": ["니코란딜", "희석니트로글리세린"]}}


@pytest.fixture
def bridge(monkeypatch):
    b = FakeBridge(result=CONTRA)
    monkeypatch.setattr(mcp_bridge, "get_bridge", lambda: b)
    return b


# ---------- 권한 ----------
@pytest.mark.parametrize("role,expected", [("patient", True), ("nurse", True), ("doctor", True), ("admin", False)])
def test_drug_tools_exposure_by_role(role, expected):
    names = {t.name for t in tools.tools_for(role)}
    assert ({"check_drug_interaction", "get_drug_safety_info"} <= names) is expected


def test_admin_call_is_denied_even_if_llm_tries(conn, bridge):
    res = tools.execute(conn, u(conn, "admin1"), "check_drug_interaction", {"drug_a": "심바스타틴", "drug_b": "클래리트로마이신"})
    assert res.denied and bridge.calls == []


def test_patients_cannot_use_literature_but_can_check_drugs():
    names = {t.name for t in tools.tools_for("patient")}
    assert "check_drug_interaction" in names and "search_medical_literature" not in names


# ---------- 도구 ----------
def test_interaction_tool_calls_dur_server(conn, bridge):
    res = tools.execute(conn, u(conn, "patient1"), "check_drug_interaction", {"drug_a": " 심바스타틴 ", "drug_b": "클래리트로마이신"})
    assert res.ok and res.refs == ("DUR:병용금기:심바스타틴×클래리트로마이신",) and "contraindicated" in res.title
    assert bridge.calls == [("mfds_dur", "check_drug_interaction", {"drug_a": "심바스타틴", "drug_b": "클래리트로마이신"})]


def test_safety_tool_calls_dur_server(conn, bridge):
    bridge.result = {"drug": "아스피린", "categories": {}, "refs": []}
    assert tools.execute(conn, u(conn, "nurse1"), "get_drug_safety_info", {"drug": "아스피린"}).ok
    assert bridge.calls[0][:2] == ("mfds_dur", "get_drug_safety_info")


def test_missing_arguments_rejected_without_calling_server(conn, bridge):
    res = tools.execute(conn, u(conn, "doctor1"), "check_drug_interaction", {"drug_a": "심바스타틴"})
    assert not res.ok and "두 약물명" in res.error and bridge.calls == []


def test_audit_does_not_record_drug_names(conn, bridge):
    tools.execute(conn, u(conn, "patient1"), "check_drug_interaction", {"drug_a": "와파린", "drug_b": "아스피린"})
    hit = next(r for r in services.read_audit(conn, u(conn, "admin1")) if r["action"] == "drug.check")
    assert "와파린" not in hit["detail"] and "아스피린" not in hit["detail"]


def test_tool_error_and_outage_messages(conn, monkeypatch):
    monkeypatch.setattr(mcp_bridge, "get_bridge", lambda: FakeBridge(error=mcp_bridge.McpToolError("서비스 키가 아직 등록되지 않았습니다")))
    assert "등록되지 않았습니다" in tools.execute(conn, u(conn, "doctor1"), "get_drug_safety_info", {"drug": "아스피린"}).error
    monkeypatch.setattr(mcp_bridge, "get_bridge", lambda: FakeBridge(error=mcp_bridge.McpError("MCP 통신 실패")))
    assert "일시적으로" in tools.execute(conn, u(conn, "doctor1"), "get_drug_safety_info", {"drug": "아스피린"}).error


# ---------- '안전' 단정 차단 ----------
@pytest.mark.parametrize("text", [
    "와파린과 아스피린은 같이 복용해도 안전합니다.",
    "두 약을 함께 드셔도 괜찮습니다.",
    "이 조합은 병용해도 문제가 없습니다.",
    "메트포르민과 병용 시 문제되지 않습니다.",
])
def test_safety_assurance_is_blocked(text):
    r = check_output(text, [])
    assert "safety_assurance" in r.events and "안전" not in r.text.split("※")[0].replace("안전 여부는 제가 보증할 수 없습니다", "")


@pytest.mark.parametrize("text", [
    "식약처 DUR 병용금기 고시 목록에는 없습니다. 안전하다는 뜻은 아니므로 의사·약사와 상의하세요.",
    "일요일은 휴진입니다.",
    "월요일 오전 10시는 예약이 가능합니다.",
    "이 두 성분은 병용금기로 고시되어 있습니다.",
])
def test_legitimate_wording_is_not_blocked(text):
    assert "safety_assurance" not in check_output(text, []).events


# ---------- 에이전트 흐름 ----------
def test_agent_reports_contraindication_with_source(conn, bridge):
    llm = FakeLLM(("tool", "check_drug_interaction", {"drug_a": "심바스타틴", "drug_b": "클래리트로마이신"}),
                  ("say", "식약처 DUR에서 병용금기로 고시되어 있습니다(근병증, 횡문근융해의 위험증가) [D1]. 복용 변경은 의사·약사와 상의하세요."))
    r = agent.run_agent(conn, u(conn, "patient1"), "심바스타틴이랑 클래리트로마이신 같이 먹어도 돼?", llm=llm)
    assert r.sources[0]["refs"] == ["DUR:병용금기:심바스타틴×클래리트로마이신"] and r.events == ["disclaimer_added"]


def test_agent_blocks_safe_claim_after_not_listed(conn, monkeypatch):
    monkeypatch.setattr(mcp_bridge, "get_bridge", lambda: FakeBridge(result=NOT_LISTED))
    bad = ("say", "DUR 목록에 없으므로 같이 복용해도 안전합니다 [D1].")
    llm = FakeLLM(("tool", "check_drug_interaction", {"drug_a": "실데나필", "drug_b": "질산염"}), bad, bad)
    r = agent.run_agent(conn, u(conn, "patient1"), "실데나필이랑 질산염 같이 먹어도 안전해?", llm=llm)
    assert "safety_assurance" in r.events and "안전합니다" not in r.answer


def test_agent_can_retry_with_partner_from_listed_partners(conn, monkeypatch):
    """not_listed의 상대 목록을 본 LLM이 계열 성분(니트로글리세린)으로 재조회하는 흐름."""
    results = iter([NOT_LISTED, {**CONTRA, "contraindications": [{"ingredient": "실데나필시트르산염", "partner": "희석니트로글리세린",
                                                                   "reason": "혈압강하작용 증가", "notified": "20080401"}], "refs": ["DUR:병용금기:실데나필×니트로글리세린"]}])

    class Seq:
        calls = []

        def call(self, server, tool, arguments, timeout=45):
            self.calls.append(arguments)
            return next(results)
    seq = Seq()
    monkeypatch.setattr(mcp_bridge, "get_bridge", lambda: seq)
    llm = FakeLLM(("tool", "check_drug_interaction", {"drug_a": "실데나필", "drug_b": "질산염"}),
                  ("tool", "check_drug_interaction", {"drug_a": "실데나필", "drug_b": "니트로글리세린"}),
                  ("say", "질산염 계열인 니트로글리세린과 병용금기입니다(혈압강하작용 증가) [D2]."))
    r = agent.run_agent(conn, u(conn, "doctor1"), "실데나필과 질산염제 병용 가능한가?", llm=llm)
    assert [c["drug_b"] for c in seq.calls] == ["질산염", "니트로글리세린"] and r.events == ["disclaimer_added"]
    assert len(r.sources) == 2
