from __future__ import annotations

from typing import Any

import pytest

from ai_scraper.browser import BrowserEngine


class FakeBrowser:
    def __init__(self, outcomes: list[Any] | None = None):
        self.outcomes = list(outcomes or [])
        self.fetch_calls: list[tuple[str, float]] = []
        self.restart_calls = 0
        self.clear_calls = 0
        self.rotate_calls = 0
        self.close_calls = 0
        self.user_agent = "ua-one"

    @staticmethod
    def detect_challenge(source: str):
        return BrowserEngine.detect_challenge(source)

    def fetch(self, url: str, wait_seconds: float = 2.0) -> str:
        self.fetch_calls.append((url, wait_seconds))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def restart(self) -> bool:
        self.restart_calls += 1
        return True

    def clear_state(self) -> bool:
        self.clear_calls += 1
        return True

    def rotate_user_agent(self) -> bool:
        self.rotate_calls += 1
        self.user_agent = "ua-two"
        return True

    def close(self) -> None:
        self.close_calls += 1


class FakeLLM:
    def __init__(
        self,
        outputs: list[Any] | None = None,
        answers: list[Any] | None = None,
        model: str = "primary-model",
    ):
        self.outputs = list(outputs or [])
        self.answers = list(answers or [])
        self.model = model
        self.extract_calls: list[dict[str, Any]] = []
        self.ask_calls: list[str] = []
        self.last_usage = {"input_tokens": 11, "output_tokens": 7}

    def extract(
        self,
        text: str,
        schema: dict[str, Any],
        instructions: str = "",
        *,
        max_chars: int = 50_000,
    ) -> list[dict]:
        self.extract_calls.append(
            {
                "text": text,
                "schema": schema,
                "instructions": instructions,
                "max_chars": max_chars,
                "model": self.model,
            }
        )
        outcome = self.outputs.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def ask(self, question: str) -> str:
        self.ask_calls.append(question)
        outcome = (
            self.answers.pop(0)
            if self.answers
            else "Use the canonical record container and map every field carefully."
        )
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def switch_model(self, model: str) -> bool:
        if model == self.model:
            return False
        self.model = model
        return True


@pytest.fixture
def substantial_html() -> str:
    return (
        "<html><body><main>"
        + "Useful listing content with enough text for extraction. " * 3
        + "</main></body></html>"
    )
