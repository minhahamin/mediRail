"""안전장치: 응급 감지(LLM 호출 전), 출력 검증(LLM 호출 후).

설계 원칙
- 응급은 LLM이 판단하지 않는다. 규칙 기반으로 즉시 119를 안내한다 (결정적, 빠름, 비용 0).
- 환자가 쓴 자유 텍스트에만 즉시 차단을 적용한다. 의료진의 임상 메모("흉통 호소")를 막으면 안 되므로 경고 플래그만 단다.
- 응급 감지는 재현율 우선(과탐 허용). 부정 표현("흉통 없음")을 구분하지 않는다.
- 출력은 항상 사후 검증한다: 없는 출처 인용, 확정 진단/처방 표현, 면책 문구 누락.
"""
import re
from dataclasses import dataclass, field

DISCLAIMER = "※ 최종 판단은 반드시 의사와 상담하세요."

EMERGENCY_PATTERNS: dict[str, re.Pattern] = {
    "cardiac": re.compile(r"흉통|가슴.{0,8}(쥐어짜|쥐어 짜|조이|짓누르|압박|찢어)|가슴.{0,6}(통증|아프|아파)"),
    "stroke": re.compile(r"(한쪽|편측).{0,10}(마비|힘이 (빠|없)|저리)|말이 (어눌|안 나|꼬)|얼굴.{0,8}(처지|비뚤|마비)|갑자기.{0,10}(시야|앞이).{0,6}(안 보|흐려|캄캄)"),
    "breathing": re.compile(r"호흡\s?곤란|숨(쉬기|을 쉬기|쉬는 게|이).{0,10}(힘들|못 쉬|막혀|막히|안 쉬|가빠)|숨이 (답답|안 쉬)|입술.{0,6}(파래|파랗|보라|푸르)"),
    "consciousness": re.compile(r"경련|발작|의식.{0,6}(없|잃|저하|흐려|불명)|쓰러졌|기절|깨어나지"),
    "anaphylaxis": re.compile(r"아나필락시스|(목|혀|입술|얼굴).{0,6}(붓|부었|부어)|(쏘인|먹은|맞은).{0,20}(두드러기|숨)"),
    "bleeding": re.compile(r"(피|출혈).{0,8}(멈추지|안 멎|안 멈|철철|많이 (나|흘))|토혈|피를 (토|쏟)|다량.{0,4}출혈"),
    "suicide": re.compile(r"죽고 (싶|만 싶)|자살|자해|목숨을 끊|살고 싶지 않|사라지고 싶|스스로 (목숨|생을)"),
}

_BASE = (
    "⚠️ **응급 상황일 수 있습니다.**\n\n"
    "지금 바로 **119**에 전화하거나 가까운 응급실로 가세요. 혼자 계시다면 주변 사람에게 즉시 도움을 요청하세요.\n\n"
    "이 서비스는 응급 상황을 판단하거나 치료할 수 없습니다."
)
_SUICIDE = (
    "\n\n지금 많이 힘드시군요. 혼자 견디지 않으셔도 됩니다. 위급하면 **119**, 마음이 힘들 때는 "
    "**자살예방 상담전화 109**(24시간, 무료)로 바로 연락하세요."
)


def detect_emergency(text: str) -> list[str]:
    """매칭된 응급 카테고리 목록. 없으면 빈 리스트."""
    return [name for name, pat in EMERGENCY_PATTERNS.items() if pat.search(text or "")]


def emergency_response(categories: list[str]) -> str:
    return _BASE + (_SUICIDE if "suicide" in categories else "") + "\n\n" + DISCLAIMER


CITATION = re.compile(r"\[(D\d+)\]")
FORBIDDEN_CLAIM = re.compile(
    r"확진(입니다|됩니다|했습니다|이에요)|진단합니다|처방합니다|처방해 드리겠습니다|\d+\s?(mg|mL|정|알)(을|를|씩)?\s?(복용|투여|드시)하세요"
)
SAFE_REPLACEMENT = (
    "진단·처방·용량 결정은 제가 할 수 없습니다. 증상과 상황을 담당 의사에게 알리고 진료를 받아 주세요."
)
CITATION_FAIL = "근거를 확인할 수 없는 내용이 포함되어 답변을 제공하지 않습니다. 담당 의사에게 문의해 주세요."


@dataclass
class Checked:
    text: str
    events: list[str] = field(default_factory=list)


def check_output(answer: str, sources: list[dict]) -> Checked:
    """LLM 출력 사후 검증. 위반 시 안전한 문구로 대체하고 이벤트를 남긴다."""
    events: list[str] = []
    allowed = {s["id"] for s in sources}
    cited = set(CITATION.findall(answer))
    if cited - allowed:
        events.append("invalid_citation")
        answer = CITATION_FAIL
    elif FORBIDDEN_CLAIM.search(answer):
        events.append("forbidden_claim")
        answer = SAFE_REPLACEMENT
    elif sources and not cited:
        events.append("uncited")
        lines = "\n".join(f"- [{s['id']}] {s['title']}" for s in sources)
        answer = f"{answer.rstrip()}\n\n**근거(조회된 자료)**\n{lines}"
    if DISCLAIMER not in answer:
        answer = f"{answer.rstrip()}\n\n{DISCLAIMER}"
        events.append("disclaimer_added")
    return Checked(answer, events)
