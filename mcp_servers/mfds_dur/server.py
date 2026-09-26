"""식약처 DUR MCP 서버 (stdio). 병용금기·임부금기·노인주의 등 의약품 안전사용 정보를 제공한다.

    python -m mcp_servers.mfds_dur.server          # MediRail 루트에서 실행

환경변수: DATA_GO_KR_API_KEY (공공데이터포털 발급 키, 필수), MEDIRAIL_DUR_CACHE (SQLite 캐시 경로, 선택)
"""
import logging
import os
from pathlib import Path

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from .client import DurClient, DurError

logging.getLogger("httpx").setLevel(logging.WARNING)  # 요청 URL에 서비스 키가 포함되므로 로그에 남기지 않는다
mcp = MCPServer("medirail-mfds-dur")
_client: DurClient | None = None
ROOT = Path(__file__).resolve().parents[2]


def client() -> DurClient:
    global _client
    if _client is None:
        _client = DurClient(os.environ.get("DATA_GO_KR_API_KEY"),
                            cache_path=os.environ.get("MEDIRAIL_DUR_CACHE", str(ROOT / "data" / "dur_cache.db")))
    return _client


def _run(fn, *args):
    try:
        return fn(*args)
    except DurError as e:
        raise ToolError(str(e))


@mcp.tool()
def check_drug_interaction(drug_a: str, drug_b: str) -> dict:
    """두 약물의 식약처 DUR 병용금기 여부를 조회한다.

    약물명은 성분명(한글, 식약처 표기)으로 쓴다. 상품명이면 성분명으로 바꿔서 호출한다 (예: 타이레놀 → 아세트아미노펜).
    상대 약물은 영문 성분명도 인식한다. status가 'not_listed'이면 병용금기 고시에 없다는 뜻이지 안전하다는 뜻이 아니다.
    'not_listed'일 때 listed_partners 목록에 사용자가 말한 계열의 성분(예: 질산염 → 니트로글리세린)이 있는지 확인한다.
    """
    return _run(client().check_interaction, drug_a, drug_b)


@mcp.tool()
def get_drug_safety_info(drug: str) -> dict:
    """한 약물의 임부금기·노인주의·특정연령대금기·용량주의·투여기간주의·효능군중복 DUR 정보를 조회한다. 약물명은 성분명(한글)."""
    return _run(client().drug_safety, drug)


if __name__ == "__main__":
    mcp.run()
