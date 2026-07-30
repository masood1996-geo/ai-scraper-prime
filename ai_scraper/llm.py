"""OpenAI-compatible LLM boundary with typed, observable failures."""

from __future__ import annotations

import json
import logging
from typing import Any

from ai_scraper.errors import (
    LLMExtractionError,
    LLMParseError,
    LLMProviderError,
    status_code_from_error,
)

logger = logging.getLogger(__name__)

PROVIDERS = {
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "default_model": "google/gemini-2.5-flash",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
    },
    "kilo": {
        "base_url": "https://api.kilo.ai/api/gateway",
        "default_model": "kilo-auto/free",
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "default_model": "llama3.1",
    },
}


def strip_code_fence(value: str) -> str:
    """Remove one surrounding Markdown code fence from an LLM response."""

    stripped = value.strip()
    if not stripped.startswith("```"):
        return stripped
    first_newline = stripped.find("\n")
    if first_newline == -1:
        return stripped.removeprefix("```").removesuffix("```").strip()
    body = stripped[first_newline + 1 :]
    if body.rstrip().endswith("```"):
        body = body.rstrip()[:-3]
    return body.strip()


class LLMClient:
    """Route structured extraction to a configured OpenAI-compatible API."""

    def __init__(
        self,
        provider: str = "openrouter",
        api_key: str = "",
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        *,
        client: Any | None = None,
    ):
        self.provider = provider.lower()
        self.api_key = api_key
        self.temperature = temperature
        self.max_tokens = max_tokens
        provider_config = PROVIDERS.get(self.provider, {})
        self.base_url = provider_config.get("base_url")
        self.model = model or provider_config.get("default_model", "gpt-4o-mini")
        self.last_usage = {"input_tokens": 0, "output_tokens": 0}
        self.last_request = {"model": "", "content_chars": 0}

        if client is None:
            import openai

            client = openai.OpenAI(
                base_url=self.base_url,
                api_key=self.api_key,
            )
        self._client = client
        logger.info("LLM client ready: %s / %s", self.provider, self.model)

    def switch_model(self, model: str) -> bool:
        """Change the model used by subsequent requests."""

        model = model.strip()
        if not model or model == self.model:
            return False
        self.model = model
        logger.info("LLM fallback model selected: %s", model)
        return True

    def _record_usage(self, response: Any) -> None:
        usage = getattr(response, "usage", None)
        self.last_usage = {
            "input_tokens": int(
                getattr(usage, "prompt_tokens", 0)
                or getattr(usage, "input_tokens", 0)
                or 0
            ),
            "output_tokens": int(
                getattr(usage, "completion_tokens", 0)
                or getattr(usage, "output_tokens", 0)
                or 0
            ),
        }

    def extract(
        self,
        text: str,
        schema: dict[str, Any],
        instructions: str = "",
        *,
        max_chars: int = 50_000,
    ) -> list[dict]:
        """Extract a JSON list matching ``schema`` or raise a typed failure."""

        system_prompt = (
            "You are a precise data extraction engine. "
            "Extract structured data from the provided content. "
            "Output only a valid JSON array of objects matching this schema:\n"
            f"{json.dumps(schema, indent=2)}"
        )
        if instructions:
            system_prompt += f"\n\nAdditional instructions:\n{instructions}"

        bounded_text = text[:max_chars]
        if len(text) > max_chars:
            logger.warning("Content truncated to %d characters", max_chars)
        self.last_request = {
            "model": self.model,
            "content_chars": len(bounded_text),
        }

        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": bounded_text},
                ],
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
        except Exception as error:
            raise LLMProviderError(
                f"LLM request failed with {type(error).__name__}",
                status_code=status_code_from_error(error),
            ) from error

        self._record_usage(response)
        raw_output = getattr(response.choices[0].message, "content", None)
        if not isinstance(raw_output, str) or not raw_output.strip():
            raise LLMExtractionError("LLM response contained no text")

        try:
            result = json.loads(strip_code_fence(raw_output))
        except json.JSONDecodeError as error:
            raise LLMParseError("LLM response was not valid JSON") from error

        if isinstance(result, dict):
            result = [result]
        if not isinstance(result, list) or any(
            not isinstance(item, dict) for item in result
        ):
            raise LLMExtractionError("LLM JSON must be an object or a list of objects")
        logger.info("Extracted %d items from LLM response", len(result))
        return result

    def ask(self, question: str) -> str:
        """Ask a text question or raise a typed provider failure."""

        self.last_request = {
            "model": self.model,
            "content_chars": len(question),
        }
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": question}],
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
        except Exception as error:
            raise LLMProviderError(
                f"LLM request failed with {type(error).__name__}",
                status_code=status_code_from_error(error),
            ) from error

        self._record_usage(response)
        content = getattr(response.choices[0].message, "content", None)
        if not isinstance(content, str) or not content.strip():
            raise LLMExtractionError("LLM response contained no text")
        return content.strip()
