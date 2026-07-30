from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai_scraper.errors import LLMParseError, LLMProviderError
from ai_scraper.llm import LLMClient, strip_code_fence


class Completions:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=outcome))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=4),
        )


def client_with(outcomes):
    completions = Completions(outcomes)
    transport = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return LLMClient(client=transport, model="model-a"), completions


def test_code_fence_stripping_and_json_parsing():
    client, completions = client_with(['```json\n[{"title": "One"}]\n```'])
    result = client.extract("page", {"title": "Title"})
    assert result == [{"title": "One"}]
    assert completions.calls[0]["max_tokens"] == 4096
    assert client.last_usage == {"input_tokens": 10, "output_tokens": 4}
    assert strip_code_fence("```text\nhello\n```") == "hello"


def test_invalid_json_is_typed():
    client, _ = client_with(["not json"])
    with pytest.raises(LLMParseError):
        client.extract("page", {"title": "Title"})


def test_provider_failure_is_typed_without_leaking_message():
    client, _ = client_with([RuntimeError("secret token=abc")])
    with pytest.raises(LLMProviderError) as captured:
        client.extract("page", {"title": "Title"})
    assert "abc" not in str(captured.value)


def test_ask_uses_selected_model_and_max_tokens():
    client, completions = client_with(["answer"])
    assert client.switch_model("fallback")
    assert client.ask("question") == "answer"
    call = completions.calls[0]
    assert call["model"] == "fallback"
    assert call["max_tokens"] == 4096
