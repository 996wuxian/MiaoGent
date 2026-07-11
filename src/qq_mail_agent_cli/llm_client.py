import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from qq_mail_agent_cli.config import DeepSeekConfig


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str


class DeepSeekClient:
    def __init__(self, config: DeepSeekConfig):
        self._config = config

    def chat(self, messages: list[ChatMessage], *, temperature: float = 0.0) -> str:
        if not self._config.api_key:
            raise RuntimeError("DEEPSEEK_API_KEY is missing in environment or .env.")

        endpoint = self._config.base_url.rstrip("/") + "/chat/completions"
        payload = {
            "model": self._config.model,
            "messages": [message.__dict__ for message in messages],
            "temperature": temperature,
        }
        request = Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urlopen(request, timeout=self._config.timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"DeepSeek API returned HTTP {error.code}: {detail}") from error
        except URLError as error:
            raise RuntimeError(f"DeepSeek API request failed: {error.reason}") from error

        return _extract_content(data)


def parse_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise RuntimeError(f"Expected a JSON object from LLM, got: {text[:200]}")
    return json.loads(stripped[start : end + 1])


def _extract_content(data: dict[str, Any]) -> str:
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise RuntimeError(f"Unexpected DeepSeek API response shape: {data}") from error
