"""MiMo connector with JWT bootstrap for MiMo Auto free tier."""

import hashlib
import json
import logging
import os
import time
from typing import Any, AsyncGenerator

import httpx

from nanocode.llm.base import LLMBase, LLMResponse, Message, ToolCall
from nanocode.llm.events import FinishStepEvent, StreamEvent, TextDeltaEvent, ToolCallEvent

logger = logging.getLogger(__name__)


class MiMoConnector(LLMBase):
    """LLM connector for MiMo Auto with JWT bootstrap."""

    def __init__(
        self,
        api_key: str = "anonymous",
        base_url: str = "https://api.xiaomimimo.com",
        model: str = "mimo-auto",
        proxy: str = None,
        **kwargs,
    ):
        super().__init__(api_key=api_key, base_url=base_url, model=model, proxy=proxy, **kwargs)
        self._jwt: str | None = None
        self._jwt_exp: float = 0
        self._fingerprint = self._get_fingerprint()
        self._proxy = proxy or os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")

    def _get_fingerprint(self) -> str:
        """Generate client fingerprint for bootstrap."""
        fingerprint_file = os.path.expanduser("~/.local/share/nanocode/mimo-fingerprint")
        os.makedirs(os.path.dirname(fingerprint_file), exist_ok=True)

        try:
            with open(fingerprint_file) as f:
                return f.read().strip()
        except FileNotFoundError:
            pass

        import socket
        seed = f"{socket.gethostname()}|{os.name}|{os.getlogin()}"
        fingerprint = hashlib.sha256(seed.encode()).hexdigest()
        try:
            with open(fingerprint_file, "w") as f:
                f.write(fingerprint)
        except Exception:
            pass
        return fingerprint

    async def _bootstrap(self) -> str:
        """Get JWT from bootstrap endpoint."""
        url = f"{self.base_url}/api/free-ai/bootstrap"
        async with httpx.AsyncClient(proxy=self._proxy, timeout=30) as client:
            response = await client.post(
                url,
                json={"client": self._fingerprint},
            )
            response.raise_for_status()
            data = response.json()
            jwt = data.get("jwt")
            if not jwt:
                raise ValueError("No JWT in bootstrap response")
            return jwt

    async def _get_jwt(self) -> str:
        """Get valid JWT, refreshing if needed."""
        now = time.time()
        if self._jwt and self._jwt_exp > now + 300:
            return self._jwt

        self._jwt = await self._bootstrap()
        self._jwt_exp = now + 3600
        return self._jwt

    def get_tool_schema(self) -> list[dict]:
        """Get tool schema format for MiMo (OpenAI compatible)."""
        return []

    async def chat_stream(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs,
    ) -> AsyncGenerator[StreamEvent, None]:
        """Stream chat completion events."""
        jwt = await self._get_jwt()

        # MiMo uses /chat instead of /chat/completions
        url = f"{self.base_url}/api/free-ai/openai/chat"
        headers = {
            "Authorization": f"Bearer {jwt}",
            "Content-Type": "application/json",
            "X-Mimo-Source": "nanocode-cli-free",
        }

        payload = {
            "model": self.model,
            "messages": [m.to_dict() if hasattr(m, 'to_dict') else m for m in messages],
            "temperature": temperature,
            "stream": True,
        }

        if max_tokens:
            payload["max_tokens"] = max_tokens

        if tools:
            payload["tools"] = tools

        async with httpx.AsyncClient(proxy=self._proxy, timeout=120) as client:
            async with client.stream("POST", url, json=payload, headers=headers) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                        delta = data["choices"][0].get("delta", {})
                        content = delta.get("content")
                        if content:
                            yield TextDeltaEvent(text=content)
                        tool_calls = delta.get("tool_calls", [])
                        for tc in tool_calls:
                            if tc.get("function", {}).get("name"):
                                yield ToolCallEvent(
                                    tool_name=tc["function"]["name"],
                                    input=tc["function"].get("arguments", "{}"),
                                    tool_call_id=tc.get("id", ""),
                                )
                    except json.JSONDecodeError:
                        continue

        yield FinishStepEvent(finish_reason="stop")
