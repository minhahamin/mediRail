"""브리지 테스트용 최소 MCP 서버 (stdio)."""
import os
import time

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

mcp = MCPServer("fake")


@mcp.tool()
def echo(text: str) -> dict:
    """입력을 그대로 돌려준다."""
    return {"echo": text, "pid": os.getpid()}


@mcp.tool()
def boom() -> dict:
    """항상 도구 오류."""
    raise ToolError("의도된 오류입니다")


@mcp.tool()
def slow(seconds: float) -> dict:
    """지정한 시간 동안 대기."""
    time.sleep(seconds)
    return {"slept": seconds}


@mcp.tool()
def crash() -> dict:
    """프로세스를 강제 종료 (서버 비정상 종료 시뮬레이션)."""
    os._exit(1)


if __name__ == "__main__":
    mcp.run()
