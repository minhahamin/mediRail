"""MCP 클라이언트 브리지: 백엔드가 stdio MCP 서버(mcp_servers/*)를 서브프로세스로 띄워 호출한다.

- 에이전트 루프는 동기 코드라서, 전용 스레드의 asyncio 루프에 MCP 세션을 유지하고 call()이 이를 호출한다.
- 서버는 첫 호출 때 지연 기동한다 (앱 시작/테스트 속도에 영향 없음). 세션은 재사용한다.
- 서버는 개별로 기동한다. 한 서버가 시작에 실패해도 나머지는 정상 동작하고, 실패한 서버는 다음 호출 때 한 번 재시도한다.
- 서버 프로세스가 죽거나 통신이 끊기면 브리지를 리셋하고, 다음 호출에서 다시 기동한다.
- MCP 도구가 오류를 돌려주면(is_error) McpToolError, 통신/기동 문제면 McpError.
"""
import asyncio
import atexit
import concurrent.futures
import json
import os
import sys
import threading
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters, stdio_client

from .config import ROOT


class McpError(Exception):
    """MCP 서버 기동·통신 실패."""


class McpToolError(McpError):
    """MCP 도구가 오류를 반환 (입력 오류, 외부 API 오류 등). 메시지는 사용자에게 보여줘도 된다."""


class McpBridge:
    def __init__(self, servers: dict[str, StdioServerParameters], start_timeout: float = 60):
        self._servers = servers
        self._start_timeout = start_timeout
        self._sessions: dict[str, ClientSession] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._stop: asyncio.Event | None = None
        self._ready = threading.Event()
        self._error: Exception | None = None
        self._errors: dict[str, str] = {}  # 서버별 기동 실패 사유
        self._lock = threading.Lock()

    # ---------- 수명 주기 ----------
    def _ensure_started(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive() and self._error is None:
                return
            self._reset()
            self._ready.clear()
            self._thread = threading.Thread(target=lambda: asyncio.run(self._main()), daemon=True, name="mcp-bridge")
            self._thread.start()
            if not self._ready.wait(self._start_timeout):
                self._reset()
                raise McpError("MCP 서버 기동 시간이 초과되었습니다")
            if self._error is not None:
                err, self._error = self._error, None
                self._reset()
                raise McpError(f"MCP 서버를 시작할 수 없습니다: {err}")

    async def _main(self) -> None:
        self._loop, self._stop = asyncio.get_running_loop(), asyncio.Event()
        try:
            async with AsyncExitStack() as stack:
                for name, params in self._servers.items():
                    sub = AsyncExitStack()  # 서버별 격리: 실패 시 그 서버의 프로세스만 정리한다
                    try:
                        read, write = await sub.enter_async_context(stdio_client(params))
                        session = await sub.enter_async_context(ClientSession(read, write))
                        await session.initialize()
                    except BaseException as e:  # noqa: BLE001
                        self._errors[name] = f"{type(e).__name__}: {e}"[:200]
                        await sub.aclose()
                        continue
                    await stack.enter_async_context(sub)
                    self._sessions[name] = session
                self._ready.set()
                await self._stop.wait()
        except BaseException as e:  # noqa: BLE001 - 기동 실패도 호출자에게 전달해야 한다
            self._error = e
        finally:
            self._sessions.clear()
            self._ready.set()

    def _reset(self) -> None:
        if self._loop and self._stop and self._thread and self._thread.is_alive():
            self._loop.call_soon_threadsafe(self._stop.set)
            self._thread.join(timeout=5)
        self._thread = self._loop = self._stop = None
        self._sessions.clear()
        self._errors.clear()

    def close(self) -> None:
        with self._lock:
            self._reset()

    # ---------- 호출 ----------
    def call(self, server: str, tool: str, arguments: dict, timeout: float = 45) -> dict:
        if server not in self._servers:
            raise McpError(f"등록되지 않은 MCP 서버: {server}")
        self._ensure_started()
        session = self._sessions.get(server)
        if session is None:  # 이 서버만 기동에 실패했던 경우: 한 번 재기동해 본다
            self.close()
            self._ensure_started()
            session = self._sessions.get(server)
        if session is None or self._loop is None:
            raise McpError(f"{server} MCP 서버를 사용할 수 없습니다: {self._errors.get(server, '알 수 없는 오류')}")
        fut = asyncio.run_coroutine_threadsafe(session.call_tool(tool, arguments), self._loop)
        try:
            result = fut.result(timeout)
        except concurrent.futures.TimeoutError:
            fut.cancel()
            raise McpError(f"MCP 호출 시간 초과 ({server}.{tool})")
        except Exception as e:  # 세션/프로세스 이상 → 다음 호출에서 재기동
            self.close()
            raise McpError(f"MCP 통신 실패: {type(e).__name__}: {e}")
        text = " ".join(getattr(c, "text", "") for c in result.content if getattr(c, "text", None))
        if result.is_error:
            raise McpToolError(text or "MCP 도구 오류")
        if result.structured_content is not None:
            return result.structured_content
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            raise McpError("MCP 응답을 해석할 수 없습니다")
        return data if isinstance(data, dict) else {"result": data}


def default_servers() -> dict[str, StdioServerParameters]:
    """MediRail이 사용하는 MCP 서버 목록. 새 서버(예: 식약처 DUR)는 여기에 추가한다."""
    return {
        "pubmed": StdioServerParameters(
            command=sys.executable, args=["-m", "mcp_servers.pubmed.server"], cwd=str(ROOT), env=dict(os.environ)),
        "mfds_dur": StdioServerParameters(
            command=sys.executable, args=["-m", "mcp_servers.mfds_dur.server"], cwd=str(ROOT), env=dict(os.environ)),
    }


_bridge: McpBridge | None = None


def get_bridge() -> McpBridge:
    global _bridge
    if _bridge is None:
        _bridge = McpBridge(default_servers())
        atexit.register(_bridge.close)
    return _bridge
