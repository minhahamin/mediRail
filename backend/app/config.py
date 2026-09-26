"""환경 설정. 모델은 MEDIRAIL_MODEL 환경변수로 교체할 수 있다."""
import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()


@dataclass(frozen=True)
class Settings:
    openrouter_api_key: str
    model: str
    db_path: str
    jwt_secret: str
    token_ttl_min: int
    max_tokens: int
    max_agent_steps: int
    reasoning_enabled: bool
    database_url: str
    env: str
    cors_origins: tuple
    chat_per_user_hour: int
    chat_per_ip_hour: int
    daily_chat_limit: int
    login_per_ip_min: int

    @property
    def is_production(self) -> bool:
        return self.env == "production"


def get_settings() -> Settings:
    e = os.environ.get
    return Settings(
        openrouter_api_key=e("OPENROUTER_API_KEY", ""),
        model=e("MEDIRAIL_MODEL", "qwen/qwen3.7-flash"),
        db_path=e("MEDIRAIL_DB", str(ROOT / "data" / "medirail.db")),
        jwt_secret=e("MEDIRAIL_JWT_SECRET", "dev-only-secret-change-me-0123456789"),
        token_ttl_min=int(e("MEDIRAIL_TOKEN_TTL_MIN", "480")),
        max_tokens=int(e("MEDIRAIL_MAX_TOKENS", "1200")),
        max_agent_steps=int(e("MEDIRAIL_MAX_AGENT_STEPS", "6")),
        reasoning_enabled=e("MEDIRAIL_REASONING", "0") == "1",
        database_url=e("DATABASE_URL", "") or e("MEDIRAIL_DATABASE_URL", ""),   # Railway가 주입 (postgresql://...)
        env=e("MEDIRAIL_ENV", "development"),
        cors_origins=tuple(o.strip() for o in e("MEDIRAIL_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o.strip()),
        # 공개 배포 시 LLM 비용 남용 방지 (사용자별/IP별/일일 전체 상한)
        chat_per_user_hour=int(e("MEDIRAIL_CHAT_PER_USER_HOUR", "30")),
        chat_per_ip_hour=int(e("MEDIRAIL_CHAT_PER_IP_HOUR", "60")),
        daily_chat_limit=int(e("MEDIRAIL_DAILY_CHAT_LIMIT", "300")),
        login_per_ip_min=int(e("MEDIRAIL_LOGIN_PER_IP_MIN", "10")),
    )
