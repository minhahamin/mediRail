"""PubMed MCP 서버 (stdio).

Claude Desktop / Claude Code / MediRail 백엔드 등 MCP 클라이언트라면 어디서나 붙일 수 있다.

    python -m mcp_servers.pubmed.server            # MediRail 루트에서 실행

Claude Code 등록 예:
    claude mcp add pubmed -- python -m mcp_servers.pubmed.server
환경변수(선택): NCBI_API_KEY, NCBI_EMAIL
"""
import os

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from .client import PubMedClient, PubMedError

mcp = MCPServer("medirail-pubmed")
_client: PubMedClient | None = None


def client() -> PubMedClient:
    global _client
    if _client is None:
        _client = PubMedClient(api_key=os.environ.get("NCBI_API_KEY"), email=os.environ.get("NCBI_EMAIL"))
    return _client


@mcp.tool()
def search_pubmed(query: str, max_results: int = 5, recent_years: int | None = None, sort: str = "relevance") -> dict:
    """PubMed에서 의학 논문을 검색하고 제목·저널·연도·논문 유형·초록을 반환한다.

    query는 영어 키워드나 MeSH 용어를 쓴다 (예: "warfarin aspirin bleeding risk", "metformin contrast nephropathy").
    논문 유형(pub_types)으로 근거 수준(Meta-Analysis, Randomized Controlled Trial, Review 등)을 가늠할 수 있다.
    recent_years를 주면 최근 N년으로 제한한다. sort는 'relevance' 또는 'pub_date'.
    """
    try:
        return client().search(query, max_results, recent_years, sort)
    except PubMedError as e:
        raise ToolError(str(e))


@mcp.tool()
def get_pubmed_article(pmid: str) -> dict:
    """PMID로 논문 한 편의 상세(초록 포함)를 조회한다."""
    try:
        return client().get_article(pmid)
    except PubMedError as e:
        raise ToolError(str(e))


if __name__ == "__main__":
    mcp.run()
