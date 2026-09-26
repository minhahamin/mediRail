"""MCP 브리지: 실제 stdio 서브프로세스로 프로토콜 왕복을 검증."""
import sys
from pathlib import Path

import pytest
from mcp import StdioServerParameters

from app.mcp_bridge import McpBridge, McpError, McpToolError, default_servers

FAKE = str(Path(__file__).with_name("fake_mcp_server.py"))


def make_bridge(**kw) -> McpBridge:
    return McpBridge({"fake": StdioServerParameters(command=sys.executable, args=[FAKE])}, **kw)


@pytest.fixture(scope="module")
def bridge():
    b = make_bridge()
    yield b
    b.close()


def test_call_returns_structured_content(bridge):
    r = bridge.call("fake", "echo", {"text": "안녕"})
    assert r["echo"] == "안녕"


def test_session_is_reused_across_calls(bridge):
    assert bridge.call("fake", "echo", {"text": "a"})["pid"] == bridge.call("fake", "echo", {"text": "b"})["pid"]


def test_tool_error_is_mapped(bridge):
    with pytest.raises(McpToolError, match="의도된 오류"):
        bridge.call("fake", "boom", {})


def test_unknown_server_and_unknown_tool(bridge):
    with pytest.raises(McpError, match="등록되지 않은"):
        bridge.call("nope", "echo", {})
    with pytest.raises(McpError):
        bridge.call("fake", "does_not_exist", {})


def test_timeout(bridge):
    with pytest.raises(McpError, match="시간 초과"):
        bridge.call("fake", "slow", {"seconds": 5}, timeout=0.5)


def test_recovers_after_server_crash():
    b = make_bridge()
    try:
        first = b.call("fake", "echo", {"text": "x"})["pid"]
        with pytest.raises(McpError):
            b.call("fake", "crash", {}, timeout=10)
        second = b.call("fake", "echo", {"text": "y"})["pid"]   # 자동 재기동
        assert second != first
    finally:
        b.close()


def test_startup_failure_is_reported():
    b = McpBridge({"bad": StdioServerParameters(command=sys.executable, args=["-c", "import sys; sys.exit(3)"])}, start_timeout=20)
    with pytest.raises(McpError):
        b.call("bad", "x", {})
    b.close()


def test_default_servers_registers_pubmed():
    s = default_servers()["pubmed"]
    assert s.args == ["-m", "mcp_servers.pubmed.server"] and s.cwd
