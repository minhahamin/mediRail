"""메모리 기반 요청 제한 (단일 인스턴스 배포용).

공개 데모에서 LLM 호출 비용이 남용되지 않도록 세 겹으로 제한한다: 사용자별 / IP별 / 하루 전체.
로그인 시도도 IP별로 제한한다. 응급 안내(LLM 호출 없음)는 제한 대상이 아니다 (안전이 우선).
재시작하면 초기화된다 — 여러 인스턴스로 확장하려면 Redis 등 공유 저장소가 필요하다.
"""
import threading
import time
from collections import defaultdict, deque

from .config import get_settings


class RateLimitExceeded(Exception):
    def __init__(self, message: str, retry_after: int = 60):
        super().__init__(message)
        self.message, self.retry_after = message, retry_after


class SlidingWindow:
    def __init__(self, clock=time.monotonic):
        self._hits: dict = defaultdict(deque)
        self._lock = threading.Lock()
        self._clock = clock

    def hit(self, key: str, limit: int, window_s: int, what: str = "요청") -> None:
        now = self._clock()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] >= window_s:
                q.popleft()
            if len(q) >= limit:
                wait = int(window_s - (now - q[0])) + 1
                minutes = max(1, -(-wait // 60))
                raise RateLimitExceeded(f"{what}이 너무 많습니다. 약 {minutes}분 후 다시 시도해 주세요.", wait)
            q.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


class DailyCounter:
    def __init__(self, today=lambda: time.strftime("%Y-%m-%d")):
        self._today, self._day, self._n = today, None, 0
        self._lock = threading.Lock()

    def hit(self, limit: int) -> None:
        with self._lock:
            day = self._today()
            if day != self._day:
                self._day, self._n = day, 0
            if self._n >= limit:
                raise RateLimitExceeded("오늘의 데모 AI 사용 한도에 도달했습니다. 내일 다시 이용해 주세요.", 3600)
            self._n += 1

    def reset(self) -> None:
        with self._lock:
            self._day, self._n = None, 0


_windows = SlidingWindow()
_daily = DailyCounter()


def check_chat(user_id: int, ip: str) -> None:
    s = get_settings()
    _windows.hit(f"chat:user:{user_id}", s.chat_per_user_hour, 3600, "AI 요청")
    _windows.hit(f"chat:ip:{ip}", s.chat_per_ip_hour, 3600, "AI 요청")
    _daily.hit(s.daily_chat_limit)


def check_login(ip: str) -> None:
    _windows.hit(f"login:ip:{ip}", get_settings().login_per_ip_min, 60, "로그인 시도")


def check_register(ip: str) -> None:
    _windows.hit(f"register:ip:{ip}", get_settings().register_per_ip_hour, 3600, "회원가입 시도")


def reset_all() -> None:
    _windows.reset()
    _daily.reset()
