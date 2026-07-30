"""Typed failures shared by the browser, LLM, and recovery layers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class AIScraperError(Exception):
    """Base class for observable AI Scraper failures."""


class NetworkFetchError(AIScraperError):
    """A page could not be fetched because of a network failure."""


class BrowserCrashedError(AIScraperError):
    """The browser session became unusable."""


class EmptyPageError(AIScraperError):
    """The fetched page did not contain enough extractable content."""


class LLMError(AIScraperError):
    """Base class for LLM boundary failures."""


class LLMProviderError(LLMError):
    """The configured LLM provider rejected or failed a request."""

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class LLMParseError(LLMError):
    """The provider returned a response that was not valid extraction JSON."""


class LLMExtractionError(LLMError):
    """The provider response could not be used as an extraction result."""


class RateLimitError(AIScraperError):
    """A page or provider rate limit was reached."""

    def __init__(self, message: str, *, status_code: int = 429):
        super().__init__(message)
        self.status_code = status_code


class ChallengeType(Enum):
    """Challenge categories detected without attempting circumvention."""

    CAPTCHA = "captcha"
    CLOUDFLARE = "cloudflare"
    AWS_WAF = "aws_waf"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ChallengeEvidence:
    """Non-sensitive evidence supporting a challenge classification."""

    challenge_type: ChallengeType
    marker: str


class UnsupportedChallengeError(AIScraperError):
    """A challenge requires a managed provider, pause, or human review."""

    def __init__(self, evidence: ChallengeEvidence):
        self.evidence = evidence
        super().__init__(
            f"Unsupported {evidence.challenge_type.value} challenge detected"
        )


class ScrapeRecoveryError(AIScraperError):
    """Automatic recovery could not produce a verified successful retry."""

    def __init__(self, message: str, *, cause: Exception | None = None):
        super().__init__(message)
        self.cause = cause


def status_code_from_error(error: BaseException) -> int | None:
    """Return a provider/HTTP status without depending on English messages."""

    direct = getattr(error, "status_code", None)
    if isinstance(direct, int):
        return direct

    response: Any = getattr(error, "response", None)
    response_status = getattr(response, "status_code", None)
    return response_status if isinstance(response_status, int) else None
