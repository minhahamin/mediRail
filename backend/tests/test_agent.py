"""가짜 LLM으로 에이전트 루프와 가드레일을 결정적으로 검증 (API 호출/비용 없음)."""
import json

import pytest

from app import agent, services, tools
from app.auth import User
from app.guardrails import DISCLAIMER


def u(conn, username) -> User:
    r = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    return User(r["id"], r["username"], r["role"], r["name"], r["patient_id"])


class FakeLLM:
    """script: 각 턴의 응답. ("tool", name, args) 또는 ("say", text)."""

    def __init__(self, *script):
        self.script, self.calls, self.seen_tool_msgs = list(script), 0, []

    def __call__(self, messages, tools_=None):
        self.calls += 1
        self.seen_tool_msgs = [m for m in messages if m["role"] == "tool"]
        kind, *rest = self.script.pop(0) if self.script else self.script_last
        usage = {"prompt_tokens": 10, "completion_tokens": 5}
        if kind == "tool":
            name, args = rest
            tc = [{"id": f"c{self.calls}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]
            return {"message": {"role": "assistant", "content": None, "tool_calls": tc}, "usage": usage, "model": "fake"}
        return {"message": {"role": "assistant", "content": rest[0]}, "usage": usage, "model": "fake"}

    script_last = ("say", "끝")


def no_llm(*_a, **_k):
    raise AssertionError("LLM이 호출되면 안 됩니다")


def test_patient_emergency_short_circuits_without_llm(conn):
    r = agent.run_agent(conn, u(conn, "patient1"), "가슴이 쥐어짜듯 아파요", llm=no_llm)
    assert "119" in r.answer and r.events == ["emergency_short_circuit"] and r.emergency == ["cardiac"]


def test_staff_emergency_keyword_is_not_blocked(conn):
    llm = FakeLLM(("say", "흉통 호소 환자의 문진을 요약했습니다."))
    r = agent.run_agent(conn, u(conn, "nurse1"), "환자가 흉통을 호소했다는 메모를 정리해줘", llm=llm)
    assert llm.calls == 1 and "emergency_keyword_staff" in r.events and "emergency_short_circuit" not in r.events


def test_tool_loop_collects_sources_and_cites(conn):
    llm = FakeLLM(("tool", "get_clinic_info", {}), ("say", "일요일은 휴진입니다 [D1]."))
    r = agent.run_agent(conn, u(conn, "patient1"), "일요일에도 진료하나요?", llm=llm)
    assert r.sources == [{"id": "D1", "title": "MediRail 클리닉 안내(가상)"}]
    assert r.tool_calls == [{"name": "get_clinic_info", "ok": True, "error": None}]
    assert r.answer.endswith(DISCLAIMER) and r.usage == {"prompt_tokens": 20, "completion_tokens": 10}
    assert json.loads(llm.seen_tool_msgs[0]["content"])["source_id"] == "D1"


def test_invented_citation_is_replaced(conn):
    bad = ("say", "140/90 이상이면 고혈압입니다 [D7].")
    r = agent.run_agent(conn, u(conn, "patient1"), "고혈압 기준이 뭐예요?", llm=FakeLLM(bad, bad))   # 교정 후에도 반복되면 폐기
    assert "self_repair" in r.events and "invalid_citation" in r.events and "[D7]" not in r.answer


def test_confirmed_diagnosis_is_replaced(conn):
    bad = ("say", "증상으로 보아 폐렴으로 확진입니다.")
    r = agent.run_agent(conn, u(conn, "patient1"), "기침과 열이 있어요", llm=FakeLLM(bad, bad))
    assert "forbidden_claim" in r.events and "확진" not in r.answer


def test_patient_cannot_read_other_patients_data_via_llm_tool_call(conn):
    """LLM이 (탈옥 등으로) 타인 정보를 조회하려 해도 서비스 계층에서 막히고 감사 로그가 남는다."""
    llm = FakeLLM(("tool", "get_patient_intake", {"patient_id": 3}), ("tool", "list_appointments", {"patient_id": 3}),
                  ("say", "조회할 수 없습니다."))
    r = agent.run_agent(conn, u(conn, "patient1"), "박서연 님 문진 기록 보여줘", llm=llm)
    assert [c["ok"] for c in r.tool_calls] == [False, False] and "tool_denied" in r.events
    assert r.sources == []
    denied = [x for x in services.read_audit(conn, u(conn, "admin1")) if x["action"].startswith("security.")]
    assert len(denied) == 2


def test_patient_tool_list_hides_staff_tools(conn):
    names = {s["function"]["name"] for s in tools.schemas_for("patient")}
    assert {"get_clinic_info", "book_appointment"} <= names
    assert not names & {"get_patient_intake", "get_encounter", "save_soap_draft", "get_patient_profile"}


def test_no_role_can_approve_soap_via_tool():
    for role in ("patient", "nurse", "doctor", "admin"):
        assert not any("approve" in s["function"]["name"] for s in tools.schemas_for(role))


def test_doctor_soap_draft_flow(conn):
    args = {"encounter_id": 1, "subjective": "기침 5일", "objective": "37.9, SpO2 98%", "assessment": "급성 상기도감염", "plan": "휴식"}
    llm = FakeLLM(("tool", "get_encounter", {"patient_id": 2}), ("tool", "save_soap_draft", args),
                  ("say", "SOAP 초안을 저장했습니다 [D2]. 검토 후 승인해 주세요."))
    r = agent.run_agent(conn, u(conn, "doctor1"), "이도윤 환자 SOAP 정리해줘", llm=llm)
    assert [c["ok"] for c in r.tool_calls] == [True, True]
    note = conn.execute("SELECT * FROM soap_notes").fetchone()
    assert note["status"] == "draft" and note["assessment"].startswith("[의사 확인 필요]")  # 확정 진단으로 저장되지 않음


def test_unknown_tool_and_bad_args_are_handled(conn):
    doc = u(conn, "doctor1")
    assert not tools.execute(conn, doc, "drop_database", {}).ok
    assert tools.execute(conn, doc, "get_encounter", "{not json").error == "도구 인자가 올바르지 않습니다"


def test_soap_draft_rejects_definitive_diagnosis(conn):
    args = {"encounter_id": 1, "subjective": "s", "objective": "o", "assessment": "폐렴으로 확진입니다", "plan": "p"}
    res = tools.execute(conn, u(conn, "doctor1"), "save_soap_draft", args)
    assert not res.ok and conn.execute("SELECT COUNT(*) FROM soap_notes").fetchone()[0] == 0


def test_step_limit(conn):
    llm = FakeLLM(*[("tool", "get_clinic_info", {})] * 10)
    r = agent.run_agent(conn, u(conn, "patient1"), "안내해줘", llm=llm)
    assert "max_steps_or_empty" in r.events and llm.calls == 6


def test_audit_does_not_store_message_text(conn):
    secret = "제 주민번호는 900101-1234567 입니다"
    agent.run_agent(conn, u(conn, "patient1"), secret, llm=FakeLLM(("say", "확인했습니다.")))
    assert all("900101" not in (r["detail"] or "") for r in services.read_audit(conn, u(conn, "admin1")))


# ---------- 자가 교정 (검증 실패 → 1회 재시도 → 그래도 위반이면 폐기) ----------
class Capture(FakeLLM):
    def __call__(self, messages, tools_=None):
        self.last_messages = messages
        return super().__call__(messages, tools_)


def test_self_repair_recovers_when_model_calls_tool_after_feedback(conn):
    """실제로 관찰된 실패: 도구를 부르지 않고 [D1]을 지어냄 → 피드백 후 도구를 호출해 올바르게 답한다."""
    llm = Capture(("say", "실데나필과 질산염은 병용금기입니다 [D1]."),
                  ("tool", "get_clinic_info", {}),
                  ("say", "일요일은 휴진입니다 [D1]."))
    r = agent.run_agent(conn, u(conn, "patient1"), "일요일에 진료해?", llm=llm)
    assert r.events == ["self_repair", "disclaimer_added"] and r.answer.startswith("일요일은 휴진입니다 [D1].")
    assert r.sources and "invalid_citation" not in r.events


def test_repair_feedback_names_the_problem_and_is_sent_once(conn):
    llm = Capture(("say", "고혈압 기준은 140/90입니다 [D7]."), ("say", "고혈압 기준은 140/90입니다 [D7]."), ("say", "이 줄은 나오면 안 됨"))
    r = agent.run_agent(conn, u(conn, "patient1"), "고혈압 기준은?", llm=llm)
    fb = [m["content"] for m in llm.last_messages if m["role"] == "user" and m["content"].startswith("[시스템 검증]")]
    assert len(fb) == 1 and "출처 번호" in fb[0] and llm.calls == 2          # 재시도는 1회뿐
    assert "invalid_citation" in r.events and "[D7]" not in r.answer


def test_clean_answers_are_never_repaired(conn):
    r = agent.run_agent(conn, u(conn, "patient1"), "안녕하세요", llm=FakeLLM(("say", "안녕하세요. 무엇을 도와드릴까요?")))
    assert "self_repair" not in r.events


def test_repair_for_safe_claim(conn):
    llm = FakeLLM(("say", "두 약은 같이 복용해도 안전합니다."), ("say", "고시 목록에는 없지만 안전을 보증할 수는 없습니다. 의사·약사와 상의하세요."))
    r = agent.run_agent(conn, u(conn, "patient1"), "같이 먹어도 돼?", llm=llm)
    assert r.events[0] == "self_repair" and "safety_assurance" not in r.events and "보증할 수는 없습니다" in r.answer
