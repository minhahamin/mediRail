"""가상 클리닉 운영 규칙 (진료시간, 슬롯, 취소 마감). 공휴일은 다루지 않는다."""
from datetime import date, datetime, time, timedelta

SLOT_MIN = 30
LUNCH = (time(12, 30), time(13, 30))
CLINIC_INFO = (
    "MediRail 클리닉 안내(가상): 진료시간 평일 09:00-18:00(점심 12:30-13:30), 토요일 09:00-13:00, 일요일·공휴일 휴진. "
    "예약 변경·취소는 진료 하루 전 18:00까지 가능하며 이후에는 전화로 문의. "
    "초진 환자는 접수 시 신분증과 건강보험증을 지참."
)
FMT = "%Y-%m-%d %H:%M"


def hours_for(d: date) -> tuple[time, time] | None:
    if d.weekday() < 5:
        return time(9, 0), time(18, 0)
    if d.weekday() == 5:
        return time(9, 0), time(13, 0)
    return None


def parse_slot(s: str) -> datetime:
    return datetime.strptime(s.strip().replace("T", " ")[:16], FMT)


def is_bookable(dt: datetime) -> bool:
    h = hours_for(dt.date())
    if not h or dt.minute % SLOT_MIN:
        return False
    end = (dt + timedelta(minutes=SLOT_MIN)).time()
    if dt.time() < h[0] or end > h[1] and end != time(0, 0):
        return False
    return dt.weekday() == 5 or not (LUNCH[0] <= dt.time() < LUNCH[1])  # 점심시간은 평일에만 적용


def slots_for(d: date) -> list[datetime]:
    h = hours_for(d)
    if not h:
        return []
    out, cur = [], datetime.combine(d, h[0])
    while cur.time() < h[1]:
        if is_bookable(cur):
            out.append(cur)
        cur += timedelta(minutes=SLOT_MIN)
    return out


def cancel_deadline(slot: datetime) -> datetime:
    return datetime.combine(slot.date() - timedelta(days=1), time(18, 0))
