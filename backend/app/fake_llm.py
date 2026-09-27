"""결정적 가짜 LLM (E2E 테스트 · 오프라인 데모 전용).

MEDIRAIL_FAKE_LLM=1 일 때만 llm.chat 대신 쓰인다. 운영 환경에서는 켤 수 없다 (main.lifespan이 기동을 거부한다).
키워드로 시나리오를 고르고 도구를 호출한 뒤 출처([D#])를 붙여 답한다. 실제 모델의 품질이 아니라
"화면·도구 호출·가드레일·권한이 끝까지 이어지는가"를 매번 같은 결과로 검증하기 위한 것이다. 외부 네트워크를 쓰지 않는다.
"""
import json
import re

USAGE = {"prompt_tokens": 10, "completion_tokens": 5}


def _turn(messages: list[dict]) -> tuple[str, list[str], list[dict]]:
    """마지막 사용자 발화, 그 뒤에 호출된 도구 이름들, 그 뒤의 도구 결과."""
    idx = max(i for i, m in enumerate(messages) if m["role"] == "user" and not str(m["content"]).startswith("[시스템 검증]"))
    after = messages[idx + 1:]
    names = [tc["function"]["name"] for m in after for tc in (m.get("tool_calls") or [])]
    results = [json.loads(m["content"]) for m in after if m["role"] == "tool"]
    return str(messages[idx]["content"]), names, results


def _call(name: str, args: dict, n: int) -> dict:
    tc = [{"id": f"fake_{n}", "type": "function", "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}]
    return {"message": {"role": "assistant", "content": None, "tool_calls": tc}, "usage": USAGE, "model": "fake-llm"}


def _say(text: str) -> dict:
    return {"message": {"role": "assistant", "content": text}, "usage": USAGE, "model": "fake-llm"}


def chat(messages: list[dict], tools: list[dict] | None = None, *, model: str | None = None) -> dict:
    user, done, results = _turn(messages)
    pid = re.search(r"선택된 환자 id: (\d+)", messages[0]["content"])
    pid = int(pid.group(1)) if pid else None
    last = results[-1] if results else {}
    n = len(done)

    if "SOAP" in user:
        if pid is None:
            return _say("환자를 먼저 선택해 주세요.")
        if not done:
            return _call("get_encounter", {"patient_id": pid}, n)
        if done == ["get_encounter"]:
            if "error" in last:
                return _say(f"진료 기록을 조회하지 못했습니다: {last['error']}")
            enc = last["data"]
            return _call("save_soap_draft", {"encounter_id": enc["id"], "subjective": enc["chief_complaint"], "objective": enc["notes"],
                                             "assessment": "급성 상기도감염 의심 (의사 확인 필요)", "plan": "충분한 수분·휴식, 3일 후 재방문"}, n)
        return _say("SOAP 초안을 저장했습니다 [D2]. 검토 후 승인해 주세요.")

    if "문진" in user and "요약" in user:
        if pid is None:
            return _say("환자를 먼저 선택해 주세요.")
        if not done:
            return _call("get_patient_intake", {"patient_id": pid}, n)
        if "error" in last:
            return _say(f"문진 기록이 없습니다: {last['error']}")
        return _say(f"문진을 요약했습니다 [D1]. 주호소는 {last['data']['text'][:20]}… 입니다.")

    if re.search(r"진료\s?시간|토요일|일요일|휴진", user):
        if not done:
            return _call("get_clinic_info", {}, n)
        return _say("진료 안내입니다. 평일 09:00-18:00, 토요일은 13:00까지이며 일요일은 휴진입니다 [D1].")

    if "예약" in user and "알려" in user:
        if not done:
            return _call("list_appointments", {}, n)
        return _say("예약 목록을 확인했습니다 [D1].")

    return _say("안녕하세요. 진료시간, 예약, 문진 요약을 도와드릴 수 있습니다.")
