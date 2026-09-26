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
    )
