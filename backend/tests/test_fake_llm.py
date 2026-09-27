"""E2E용 결정적 가짜 LLM: 시나리오, 가드레일과의 결합, 운영 차단."""
import pytest
from fastapi.testclient import TestClient

from app import agent, fake_llm, llm
from app.main import app
from tests.conftest import login
from tests.test_agent import u


def run(conn, who, text, pid=None):
    return agent.run_agent(conn, u(conn, who), text, patient_id=pid, llm=fake_llm.chat)


def test_clinic_info_scenario_uses_tool_and_cites_source(conn):
    r = run(conn, "patient1", "토요일 진료시간 알려줘")
    assert [c["name"] for c in r.tool_calls] == ["get_clinic_info"] and r.sources == [{"id": "D1", "title": "MediRail 클리닉 안내(가상)"}]
    assert "13:00" in r.answer and "[D1]" in r.answer and r.events == ["disclaimer_added"]
    assert r.model == "fake-llm"


def test_soap_scenario_drafts_but_never_approves(conn):
    r = run(conn, "doctor1", "이 환자 SOAP 초안 만들어줘", pid=2)
    assert [c["name"] for c in r.tool_calls] == ["get_encounter", "save_soap_draft"] and all(c["ok"] for c in r.tool_calls)
    note = conn.execute("SELECT * FROM soap_notes").fetchone()
    assert note["status"] == "draft" and "의사 확인 필요" in note["assessment"] and note["encounter_id"] == 1


def test_soap_without_selected_patient_asks_for_one(conn):
    r = run(conn, "doctor1", "SOAP 초안 만들어줘")
    assert r.tool_calls == [] and "환자를 먼저 선택" in r.answer


def test_intake_summary_scenario_and_missing_intake(conn):
    ok = run(conn, "nurse1", "문진 요약해줘", pid=1)
    assert [c["name"] for c in ok.tool_calls] == ["get_patient_intake"] and "문진을 요약했습니다" in ok.answer
    missing = run(conn, "nurse1", "문진 요약해줘", pid=2)                         # 문진이 없는 환자
    assert "문진 기록이 없습니다" in missing.answer


def test_permissions_still_apply_to_the_fake_model(conn):
    """가짜 모델이 도구를 호출해도 서비스 계층의 권한 검사는 그대로다 (환자는 문진 조회 불가)."""
    r = run(conn, "patient1", "문진 요약해줘", pid=1)
    assert r.tool_calls == [] or all(not c["ok"] for c in r.tool_calls)


def test_emergency_still_short_circuits_before_the_fake_model(conn):
    def boom(*a, **k):
        raise AssertionError("응급은 LLM(가짜 포함)을 호출하지 않는다")
    r = agent.run_agent(conn, u(conn, "patient1"), "가슴이 쥐어짜듯 아파요", llm=boom)
    assert "119" in r.answer


def test_default_reply(conn):
    assert "안녕하세요" in run(conn, "patient1", "안녕").answer


def test_llm_chat_delegates_when_enabled(monkeypatch):
    monkeypatch.setenv("MEDIRAIL_FAKE_LLM", "1")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    r = llm.chat([{"role": "system", "content": "x"}, {"role": "user", "content": "안녕"}], [])
    assert r["model"] == "fake-llm"                                              # 키 없이도 동작 = 외부 호출 없음


def test_real_llm_path_untouched_when_disabled(monkeypatch):
    monkeypatch.delenv("MEDIRAIL_FAKE_LLM", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr("app.config._load_dotenv", lambda: None)
    with pytest.raises(llm.LLMError, match="OPENROUTER_API_KEY"):
        llm.chat([{"role": "user", "content": "x"}])


def test_fake_llm_is_refused_in_production(monkeypatch, tmp_path):
    """운영에서 가짜 LLM이 켜지면 사용자에게 가짜 의료 답변이 나가므로 기동 자체를 거부한다."""
    monkeypatch.setenv("MEDIRAIL_ENV", "production")
    monkeypatch.setenv("MEDIRAIL_JWT_SECRET", "x" * 40)
    monkeypatch.setenv("MEDIRAIL_FAKE_LLM", "1")
    monkeypatch.setenv("MEDIRAIL_DB", str(tmp_path / "p.db"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="MEDIRAIL_FAKE_LLM"):
        with TestClient(app):
            pass


def test_chat_endpoint_works_end_to_end_with_fake_llm(client, monkeypatch):
    monkeypatch.setenv("MEDIRAIL_FAKE_LLM", "1")
    r = client.post("/chat", headers=login(client, "patient1"), json={"message": "일요일에도 진료해?"}).json()
    assert r["model"] == "fake-llm" and r["sources"][0]["id"] == "D1" and "휴진" in r["answer"]
