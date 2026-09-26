"""에이전트 도구 레지스트리.

- 역할별로 LLM에 노출하는 도구 목록이 다르다 (tool allowlist).
- 노출과 별개로 실행 시점에 권한을 다시 검사하고, 실제 접근 제어는 services 계층이 강제한다 (다층 방어).
- 도구는 서비스 함수를 감싸는 얇은 어댑터이며 (출처 제목, 데이터)를 돌려준다. 출처 제목은 [D#] 인용에 쓰인다.
"""
import json
from dataclasses import dataclass
from typing import Callable

from . import clinic, mcp_bridge, services
from .auth import User
from .guardrails import FORBIDDEN_CLAIM
from .rbac import has_any


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict
    permissions: tuple[str, ...]  # 하나라도 가지면 사용 가능
    run: Callable  # (conn, user, args) -> (title, data)


@dataclass
class ToolResult:
    ok: bool
    title: str = ""
    data: dict | None = None
    error: str = ""
    denied: bool = False
    refs: tuple = ()  # 이 결과에서 인용 가능한 외부 식별자 (예: 'PMID:123')


def _obj(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or []}


_INT = {"type": "integer"}
_STR = {"type": "string"}


def _pid(args: dict) -> int | None:
    v = args.get("patient_id")
    return int(v) if v not in (None, "") else None


def _clinic_info(conn, user, args):
    return "MediRail 클리닉 안내(가상)", {"info": clinic.CLINIC_INFO}


def _slots(conn, user, args):
    day = str(args.get("date", ""))
    slots = services.available_slots(conn, day)
    return f"예약 가능 시간 {day}", {"date": day, "available_slots": slots[:24], "total": len(slots)}


def _list_appts(conn, user, args):
    return "예약 목록", {"appointments": services.list_appointments(conn, user, _pid(args))}


def _book(conn, user, args):
    r = services.book_appointment(conn, user, str(args.get("slot", "")), str(args.get("reason", "")), _pid(args))
    return "예약 완료", r


def _cancel(conn, user, args):
    return "예약 취소", services.cancel_appointment(conn, user, int(args["appointment_id"]))


def _intake_submit(conn, user, args):
    return "문진 접수", services.submit_intake(conn, user, str(args.get("text", "")))


def _profile(conn, user, args):
    p = services.get_patient_profile(conn, user, int(args["patient_id"]))
    return f"환자 정보 #{p['id']}", p


def _intake(conn, user, args):
    i = services.get_latest_intake(conn, user, int(args["patient_id"]))
    return f"문진 기록 #{i['id']}", i


def _encounter(conn, user, args):
    eid = args.get("encounter_id")
    if eid in (None, ""):
        eid = services.latest_encounter_id(conn, user, int(args["patient_id"]))
    e = services.get_encounter(conn, user, int(eid))
    return f"진료 기록 #{e['id']}", e


def _literature(conn, user, args):
    query = str(args.get("query", "")).strip()
    n = max(1, min(int(args.get("max_results") or 5), 8))
    years = int(args["recent_years"]) if args.get("recent_years") else None
    services.audit(conn, user, "literature.search", f"q_len={len(query)} n={n}")  # 질의 원문은 기록하지 않음(환자 정보가 섞일 수 있음)
    try:
        data = mcp_bridge.get_bridge().call("pubmed", "search_pubmed", {"query": query, "max_results": n, "recent_years": years})
    except mcp_bridge.McpToolError as e:
        raise services.ServiceError(str(e))
    except mcp_bridge.McpError as e:
        raise services.ServiceError(f"문헌 검색 서비스를 일시적으로 사용할 수 없습니다 ({e})")
    return f"PubMed 검색: {query[:60]} ({data.get('returned', 0)}건)", data


def _soap_draft(conn, user, args):
    parts = {k: str(args.get(k, "")).strip() for k in ("subjective", "objective", "assessment", "plan")}
    if not all(parts.values()):
        raise services.ServiceError("S/O/A/P 네 항목을 모두 작성해야 합니다")
    if FORBIDDEN_CLAIM.search(" ".join(parts.values())):
        raise services.ServiceError("확정 진단·처방 표현은 초안에 쓸 수 없습니다. '의심 소견' 형태로 작성하세요")
    if not any(k in parts["assessment"] for k in ("의심", "가능성", "확인 필요")):
        parts["assessment"] = f"[의사 확인 필요] {parts['assessment']}"
    r = services.save_soap_draft(conn, user, int(args["encounter_id"]), **parts)
    return f"SOAP 초안 #{r['soap_id']}", r | {"note": "초안입니다. 의사의 검토·승인 전에는 확정되지 않습니다."}


TOOLS: dict[str, Tool] = {t.name: t for t in [
    Tool("search_medical_literature",
         "PubMed에서 의학 논문을 검색한다(MCP). query는 반드시 영어 키워드/MeSH 용어로 쓴다(예: 'warfarin aspirin bleeding risk'). "
         "결과의 pmid, 연도, 논문 유형(pub_types), 초록을 근거로만 답한다.",
         _obj({"query": _STR, "max_results": _INT, "recent_years": {**_INT, "description": "최근 N년으로 제한(선택)"}}, ["query"]),
         ("literature.search",), _literature),
    Tool("get_clinic_info", "클리닉 진료시간·예약 규칙·준비물 안내를 조회한다.", _obj({}), ("chat",), _clinic_info),
    Tool("get_available_slots", "특정 날짜의 예약 가능한 시간 슬롯을 조회한다.",
         _obj({"date": {**_STR, "description": "YYYY-MM-DD"}}, ["date"]), ("chat",), _slots),
    Tool("list_appointments", "예약 목록을 조회한다. 환자는 본인 예약만, 직원은 전체 또는 patient_id로 필터.",
         _obj({"patient_id": _INT}), ("appointment.read_own", "appointment.read_all"), _list_appts),
    Tool("book_appointment", "예약을 생성한다. slot은 'YYYY-MM-DD HH:MM'. 환자는 본인 명의로만, 원무는 patient_id 지정.",
         _obj({"slot": _STR, "reason": _STR, "patient_id": _INT}, ["slot"]),
         ("appointment.book_own", "appointment.manage_all"), _book),
    Tool("cancel_appointment", "예약을 취소한다. 환자는 진료 하루 전 18:00까지만 가능.",
         _obj({"appointment_id": _INT}, ["appointment_id"]), ("appointment.cancel_own", "appointment.manage_all"), _cancel),
    Tool("submit_intake", "환자가 본인의 증상 문진 내용을 접수한다.", _obj({"text": _STR}, ["text"]),
         ("intake.submit_own",), _intake_submit),
    Tool("get_patient_profile", "환자 인적사항 조회. 알레르기·복용약은 의료진에게만 표시된다.",
         _obj({"patient_id": _INT}, ["patient_id"]), ("patient.read_demographics",), _profile),
    Tool("get_patient_intake", "환자의 최신 문진 원문과 알레르기·복용약을 조회한다 (문진 요약용).",
         _obj({"patient_id": _INT}, ["patient_id"]), ("intake.read",), _intake),
    Tool("get_encounter", "진료 기록을 조회한다. encounter_id가 없으면 patient_id의 최신 진료를 조회 (SOAP 정리용).",
         _obj({"encounter_id": _INT, "patient_id": _INT}), ("encounter.read",), _encounter),
    Tool("save_soap_draft", "SOAP 노트를 '초안'으로 저장한다. Assessment는 확정 진단이 아닌 '의사 확인이 필요한 의심 소견'으로만 작성. 승인은 의사가 직접 한다.",
         _obj({"encounter_id": _INT, "subjective": _STR, "objective": _STR, "assessment": _STR, "plan": _STR},
              ["encounter_id", "subjective", "objective", "assessment", "plan"]), ("soap.draft",), _soap_draft),
]}


def tools_for(role: str) -> list[Tool]:
    return [t for t in TOOLS.values() if has_any(role, t.permissions)]


def schemas_for(role: str) -> list[dict]:
    return [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
            for t in tools_for(role)]


def execute(conn, user: User, name: str, raw_args) -> ToolResult:
    """도구 실행. 알 수 없는 도구, 권한 없음, 잘못된 인자, 서비스 오류를 모두 ToolResult로 돌려준다."""
    tool = TOOLS.get(name)
    if not tool:
        return ToolResult(False, error=f"알 수 없는 도구: {name}")
    if not has_any(user.role, tool.permissions):  # 노출 목록에 없는 도구를 LLM이 호출해도 여기서 차단
        services.audit(conn, user, "security.tool_denied", f"tool={name}")
        return ToolResult(False, error="이 역할에는 허용되지 않은 도구입니다", denied=True)
    try:
        args = json.loads(raw_args) if isinstance(raw_args, str) and raw_args.strip() else (raw_args or {})
        if not isinstance(args, dict):
            raise ValueError
        title, data = tool.run(conn, user, args)
        return ToolResult(True, title, data, refs=tuple(data.get("refs", ())) if isinstance(data, dict) else ())
    except services.PermissionDenied as e:
        services.audit(conn, user, "security.access_denied", f"tool={name} {e}")
        return ToolResult(False, error=str(e), denied=True)
    except services.ServiceError as e:
        return ToolResult(False, error=str(e))
    except (ValueError, KeyError, TypeError):
        return ToolResult(False, error="도구 인자가 올바르지 않습니다")
