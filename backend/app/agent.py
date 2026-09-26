"""에이전트 루프: 응급 사전 차단 → 도구 호출 반복 → 출력 사후 검증 → 감사 로그.

    사용자 입력
       │  환자 + 응급 키워드 ─────────▶ 즉시 119 안내 (LLM 호출 없음)
       ▼
    시스템 프롬프트(역할별) + 역할별 도구 목록
       ▼
    ┌─▶ LLM ──tool_calls──▶ execute() ─▶ services(RBAC) ─▶ 결과에 [D#] 출처 부여
    └───────────────────────────────────┘        (최대 max_agent_steps회)
       ▼
    check_output(): 없는 인용 / 확정 진단·처방 / 면책 문구 검증 → 응답
    """
import json
from dataclasses import dataclass, field

from . import guardrails, llm as llm_mod, services, tools
from .auth import User
from .config import get_settings
from .prompts import system_prompt

MAX_HISTORY, MAX_CONTENT = 10, 2000
STEP_LIMIT_MSG = "요청을 처리하지 못했습니다. 질문을 더 구체적으로 다시 입력해 주세요."


@dataclass
class AgentResult:
    answer: str
    sources: list[dict] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    events: list[str] = field(default_factory=list)
    emergency: list[str] = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    model: str = ""


def _clean_history(history) -> list[dict]:
    out = [{"role": h["role"], "content": str(h["content"])[:MAX_CONTENT]}
           for h in (history or []) if isinstance(h, dict) and h.get("role") in ("user", "assistant") and h.get("content")]
    return out[-MAX_HISTORY:]


def run_agent(conn, user: User, message: str, *, history=None, patient_id: int | None = None, llm=None) -> AgentResult:
    llm = llm or llm_mod.chat
    settings = get_settings()

    # 1) 응급 사전 차단 — 환자 입력만. 의료진의 임상 메모는 차단하지 않고 이벤트만 남긴다.
    emergency = guardrails.detect_emergency(message)
    if emergency and user.role == "patient":
        services.audit(conn, user, "chat.emergency", ",".join(emergency))
        return AgentResult(guardrails.emergency_response(emergency), events=["emergency_short_circuit"], emergency=emergency)

    events = ["emergency_keyword_staff"] if emergency else []
    messages = [{"role": "system", "content": system_prompt(user.role, patient_id)},
                *_clean_history(history), {"role": "user", "content": message[:MAX_CONTENT]}]
    schemas = tools.schemas_for(user.role)
    sources: list[dict] = []
    calls: list[dict] = []
    usage = {"prompt_tokens": 0, "completion_tokens": 0}
    model = settings.model
    answer = None

    # 2) 도구 호출 루프
    for _ in range(settings.max_agent_steps):
        resp = llm(messages, schemas)
        model = resp.get("model", model)
        for k in usage:
            usage[k] += (resp.get("usage") or {}).get(k, 0) or 0
        msg = resp["message"]
        tcs = msg.get("tool_calls") or []
        if not tcs:
            answer = (msg.get("content") or "").strip()
            break
        messages.append({"role": "assistant", "content": msg.get("content"), "tool_calls": tcs})
        for tc in tcs:
            fn = tc["function"]
            res = tools.execute(conn, user, fn["name"], fn.get("arguments"))
            if res.ok:
                src_id = f"D{len(sources) + 1}"
                sources.append({"id": src_id, "title": res.title, **({"refs": list(res.refs)} if res.refs else {})})
                payload = {"source_id": src_id, "title": res.title, "data": res.data}
            else:
                payload = {"error": res.error}
                if res.denied:
                    events.append("tool_denied")
            calls.append({"name": fn["name"], "ok": res.ok, "error": res.error or None})
            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": json.dumps(payload, ensure_ascii=False, default=str)})

    # 3) 사후 검증
    if not answer:
        events.append("max_steps_or_empty")
        answer = STEP_LIMIT_MSG
    checked = guardrails.check_output(answer, sources, user_text=message)
    events += checked.events
    services.audit(conn, user, "chat", f"tools={[c['name'] for c in calls]} events={events} len={len(message)}")  # 원문은 기록하지 않음
    return AgentResult(checked.text, sources, calls, events, emergency, usage, model)
