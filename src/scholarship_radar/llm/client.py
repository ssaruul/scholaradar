from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..config import LlmConfig


@dataclass(frozen=True)
class Completion:
    data: dict[str, Any] | None
    raw: str
    prompt_tokens: int
    completion_tokens: int
    seconds: float
    error: str | None = None


@dataclass
class LlmClient:
    config: LlmConfig
    model: str | None = None
    client: httpx.Client = field(init=False)

    def __post_init__(self) -> None:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        self.client = httpx.Client(base_url=self.config.base_url.rstrip("/"), headers=headers, timeout=self.config.timeout_seconds)

    def close(self) -> None:
        self.client.close()

    def healthy(self) -> bool:
        try:
            response = self.client.get("/models", timeout=5)
        except httpx.HTTPError:
            return False
        return response.status_code == 200

    def complete_json(self, system: str, user: str, schema: dict[str, Any], schema_name: str = "opportunity") -> Completion:
        payload: dict[str, Any] = {
            "model": self.model or self.config.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "response_format": {"type": "json_schema", "json_schema": {"name": schema_name, "schema": schema, "strict": True}},
            **self.config.extra_body,
        }
        started = time.monotonic()
        try:
            response = self.client.post("/chat/completions", json=payload)
        except httpx.TimeoutException:
            return Completion(None, "", 0, 0, time.monotonic() - started, error="timeout")
        except httpx.HTTPError as exc:
            return Completion(None, "", 0, 0, time.monotonic() - started, error=f"http_error:{type(exc).__name__}")
        seconds = time.monotonic() - started
        if response.status_code != 200:
            return Completion(None, response.text[:500], 0, 0, seconds, error=f"status_{response.status_code}")
        body = response.json()
        content = body["choices"][0]["message"].get("content") or ""
        usage = body.get("usage", {})
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            return Completion(None, content, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0), seconds, error="invalid_json")
        if not isinstance(data, dict):
            return Completion(None, content, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0), seconds, error="not_object")
        return Completion(data, content, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0), seconds)
