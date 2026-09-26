"""OpenRouter 클라이언트. 모델은 설정(MEDIRAIL_MODEL)으로 교체한다."""
import time

import httpx

from .config import get_settings

URL = "https://openrouter.ai/api/v1/chat/completions"


class LLMError(Exception):
    pass


def chat(messages: list[dict], tools: list[dict] | None = None, *, model: str | None = None) -> dict:
    """반환: {"message": assistant message, "usage": {...}, "model": str}"""
    s = get_settings()
    if not s.openrouter_api_key:
        raise LLMError("OPENROUTER_API_KEY가 설정되지 않았습니다")
    body = {"model": model or s.model, "messages": messages, "temperature": 0, "max_tokens": s.max_tokens}
    if not s.reasoning_enabled:
        body["reasoning"] = {"enabled": False}
    if tools:
        body["tools"], body["tool_choice"] = tools, "auto"
    last = ""
    for attempt in range(3):
        try:
            r = httpx.post(URL, json=body, headers={"Authorization": f"Bearer {s.openrouter_api_key}"}, timeout=90)
        except httpx.HTTPError as e:
            last = str(e)
        else:
            if r.status_code == 200:
                data = r.json()
                if "choices" in data:
                    return {"message": data["choices"][0]["message"], "usage": data.get("usage", {}), "model": body["model"]}
                last = str(data.get("error", data))[:200]
            elif r.status_code in (429, 500, 502, 503):
                last = f"HTTP {r.status_code}"
            else:
                raise LLMError(f"HTTP {r.status_code}: {r.text[:200]}")
        time.sleep(2 * (attempt + 1))
    raise LLMError(f"LLM 호출 실패: {last}")
