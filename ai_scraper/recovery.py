"""Bounded recovery with typed side-effect and retry verification results."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ai_scraper.errors import (
    BrowserCrashedError,
    EmptyPageError,
    LLMExtractionError,
    LLMParseError,
    LLMProviderError,
    NetworkFetchError,
    RateLimitError,
    UnsupportedChallengeError,
    status_code_from_error,
)

logger = logging.getLogger(__name__)


class FailureScenario(Enum):
    """Stable failure categories consumed by recovery selection."""

    NETWORK_TIMEOUT = "network_timeout"
    RATE_LIMITED = "rate_limited"
    CAPTCHA_BLOCKED = "captcha_blocked"
    LLM_EXTRACTION_FAILED = "llm_extraction_failed"
    LLM_PROVIDER_ERROR = "llm_provider_error"
    STALE_SELECTOR = "stale_selector"
    EMPTY_PAGE = "empty_page"
    BROWSER_CRASH = "browser_crash"
    CLOUDFLARE_CHALLENGE = "cloudflare_challenge"
    JSON_PARSE_ERROR = "json_parse_error"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class FailureClassification:
    """A failure category plus non-sensitive root-cause metadata."""

    scenario: FailureScenario
    metadata: dict[str, Any]


class EscalationPolicy(Enum):
    ALERT_HUMAN = "alert_human"
    LOG_AND_CONTINUE = "log_and_continue"
    ABORT = "abort"


class RecoveryStepType(Enum):
    RETRY_WITH_BACKOFF = "retry_with_backoff"
    WAIT_COOLDOWN = "wait_cooldown"
    RETRY_REQUEST = "retry_request"
    RESTART_BROWSER = "restart_browser"
    INCREASE_WAIT = "increase_wait"
    REDUCE_CONTENT = "reduce_content"
    RETRY_WITH_FALLBACK_MODEL = "retry_with_fallback_model"
    CLEAR_COOKIES = "clear_cookies"
    ROTATE_USER_AGENT = "rotate_user_agent"
    WAIT_FOR_CHALLENGE = "wait_for_challenge"
    SKIP_AND_LOG = "skip_and_log"


class RecoveryStepStatus(Enum):
    """Observable outcome for one requested recovery action."""

    APPLIED = "applied"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"
    SKIPPED_BY_POLICY = "skipped_by_policy"


@dataclass(frozen=True)
class RecoveryStep:
    step_type: RecoveryStepType
    params: dict[str, Any] = field(default_factory=dict)
    description: str = ""


@dataclass(frozen=True)
class RecoveryStepResult:
    status: RecoveryStepStatus
    detail: str = ""
    changed: dict[str, Any] = field(default_factory=dict)

    @property
    def applied(self) -> bool:
        return self.status is RecoveryStepStatus.APPLIED


@dataclass(frozen=True)
class RecoveryRecipe:
    scenario: FailureScenario
    steps: list[RecoveryStep]
    max_attempts: int
    escalation_policy: EscalationPolicy


class RecoveryResultType(Enum):
    RETRY_READY = "retry_ready"
    RECOVERED = "recovered"
    PARTIAL_RECOVERY = "partial_recovery"
    ESCALATION_REQUIRED = "escalation_required"


@dataclass
class RecoveryResult:
    result_type: RecoveryResultType
    steps_taken: int = 0
    step_results: list[RecoveryStepResult] = field(default_factory=list)
    remaining_steps: list[RecoveryStep] = field(default_factory=list)
    reason: str = ""
    value: Any = None
    classification: FailureClassification | None = None

    @property
    def success(self) -> bool:
        """True only after the subsequent operation independently succeeded."""

        return self.result_type is RecoveryResultType.RECOVERED

    @property
    def ready_for_retry(self) -> bool:
        return self.result_type is RecoveryResultType.RETRY_READY


class RecoveryEventType(Enum):
    RECOVERY_ATTEMPTED = "recovery.attempted"
    RECOVERY_SUCCEEDED = "recovery.succeeded"
    RECOVERY_FAILED = "recovery.failed"
    RECOVERY_ESCALATED = "recovery.escalated"
    STEP_APPLIED = "recovery.step.applied"
    STEP_UNSUPPORTED = "recovery.step.unsupported"
    STEP_FAILED = "recovery.step.failed"
    STEP_SKIPPED = "recovery.step.skipped_by_policy"


@dataclass(frozen=True)
class RecoveryEvent:
    event_type: RecoveryEventType
    scenario: FailureScenario | None = None
    step: RecoveryStep | None = None
    result_type: RecoveryResultType | None = None
    detail: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event": self.event_type.value,
            "scenario": self.scenario.value if self.scenario else None,
            "step": self.step.step_type.value if self.step else None,
            "result": self.result_type.value if self.result_type else None,
            "detail": self.detail,
            "timestamp": self.timestamp,
        }


def _step(
    step_type: RecoveryStepType,
    description: str,
    **params: Any,
) -> RecoveryStep:
    return RecoveryStep(step_type, params=params, description=description)


def _build_recipes() -> dict[FailureScenario, RecoveryRecipe]:
    """Build conservative recipes; challenges never attempt circumvention."""

    return {
        FailureScenario.NETWORK_TIMEOUT: RecoveryRecipe(
            FailureScenario.NETWORK_TIMEOUT,
            [
                _step(
                    RecoveryStepType.RETRY_WITH_BACKOFF,
                    "Bounded network backoff",
                    max_wait=30,
                    base_delay=2,
                ),
                _step(RecoveryStepType.RETRY_REQUEST, "Retry the fetch"),
            ],
            3,
            EscalationPolicy.LOG_AND_CONTINUE,
        ),
        FailureScenario.RATE_LIMITED: RecoveryRecipe(
            FailureScenario.RATE_LIMITED,
            [
                _step(
                    RecoveryStepType.WAIT_COOLDOWN,
                    "Respect provider cooldown",
                    duration=60,
                ),
                _step(RecoveryStepType.RETRY_REQUEST, "Retry after cooldown"),
            ],
            2,
            EscalationPolicy.ALERT_HUMAN,
        ),
        FailureScenario.CAPTCHA_BLOCKED: RecoveryRecipe(
            FailureScenario.CAPTCHA_BLOCKED,
            [
                _step(
                    RecoveryStepType.SKIP_AND_LOG,
                    "Pause and escalate unsupported CAPTCHA",
                )
            ],
            1,
            EscalationPolicy.ALERT_HUMAN,
        ),
        FailureScenario.CLOUDFLARE_CHALLENGE: RecoveryRecipe(
            FailureScenario.CLOUDFLARE_CHALLENGE,
            [
                _step(
                    RecoveryStepType.SKIP_AND_LOG,
                    "Pause and escalate unsupported Cloudflare challenge",
                )
            ],
            1,
            EscalationPolicy.ALERT_HUMAN,
        ),
        FailureScenario.LLM_EXTRACTION_FAILED: RecoveryRecipe(
            FailureScenario.LLM_EXTRACTION_FAILED,
            [
                _step(
                    RecoveryStepType.REDUCE_CONTENT,
                    "Reduce the next LLM input",
                    max_chars=25_000,
                ),
                _step(RecoveryStepType.RETRY_REQUEST, "Retry extraction"),
            ],
            2,
            EscalationPolicy.LOG_AND_CONTINUE,
        ),
        FailureScenario.LLM_PROVIDER_ERROR: RecoveryRecipe(
            FailureScenario.LLM_PROVIDER_ERROR,
            [
                _step(
                    RecoveryStepType.RETRY_WITH_BACKOFF,
                    "Bounded provider backoff",
                    max_wait=15,
                    base_delay=1,
                ),
                _step(
                    RecoveryStepType.RETRY_WITH_FALLBACK_MODEL,
                    "Select the configured fallback model",
                ),
                _step(RecoveryStepType.RETRY_REQUEST, "Retry extraction"),
            ],
            2,
            EscalationPolicy.ABORT,
        ),
        FailureScenario.STALE_SELECTOR: RecoveryRecipe(
            FailureScenario.STALE_SELECTOR,
            [
                _step(
                    RecoveryStepType.INCREASE_WAIT,
                    "Increase the next browser wait",
                    additional_seconds=3,
                ),
                _step(RecoveryStepType.RETRY_REQUEST, "Retry the fetch"),
            ],
            2,
            EscalationPolicy.LOG_AND_CONTINUE,
        ),
        FailureScenario.EMPTY_PAGE: RecoveryRecipe(
            FailureScenario.EMPTY_PAGE,
            [
                _step(
                    RecoveryStepType.INCREASE_WAIT,
                    "Increase the next browser wait",
                    additional_seconds=5,
                ),
                _step(
                    RecoveryStepType.CLEAR_COOKIES,
                    "Clear cookies and browser storage",
                ),
                _step(
                    RecoveryStepType.RESTART_BROWSER,
                    "Restart the browser session",
                ),
                _step(RecoveryStepType.RETRY_REQUEST, "Retry from scratch"),
            ],
            2,
            EscalationPolicy.ALERT_HUMAN,
        ),
        FailureScenario.BROWSER_CRASH: RecoveryRecipe(
            FailureScenario.BROWSER_CRASH,
            [
                _step(
                    RecoveryStepType.RESTART_BROWSER,
                    "Restart the browser session",
                ),
                _step(RecoveryStepType.RETRY_REQUEST, "Retry the fetch"),
            ],
            2,
            EscalationPolicy.ABORT,
        ),
        FailureScenario.JSON_PARSE_ERROR: RecoveryRecipe(
            FailureScenario.JSON_PARSE_ERROR,
            [
                _step(
                    RecoveryStepType.REDUCE_CONTENT,
                    "Reduce input before retrying JSON extraction",
                    max_chars=25_000,
                ),
                _step(RecoveryStepType.RETRY_REQUEST, "Retry extraction"),
            ],
            2,
            EscalationPolicy.LOG_AND_CONTINUE,
        ),
        FailureScenario.UNKNOWN: RecoveryRecipe(
            FailureScenario.UNKNOWN,
            [
                _step(
                    RecoveryStepType.SKIP_AND_LOG,
                    "Unknown failure requires operator review",
                )
            ],
            1,
            EscalationPolicy.ALERT_HUMAN,
        ),
    }


DEFAULT_RECIPES = _build_recipes()


class RecoveryContext:
    """Track per-job attempts and a process-local structured event history."""

    def __init__(self):
        self._attempts: dict[tuple[str, FailureScenario], int] = {}
        self._events: list[RecoveryEvent] = []

    @property
    def events(self) -> list[RecoveryEvent]:
        return list(self._events)

    def attempt_count(
        self,
        scenario: FailureScenario,
        job_id: str = "global",
    ) -> int:
        return self._attempts.get((job_id, scenario), 0)

    def reset(
        self,
        scenario: FailureScenario | None = None,
        job_id: str | None = None,
    ) -> None:
        if scenario is None and job_id is None:
            self._attempts.clear()
            return
        self._attempts = {
            key: value
            for key, value in self._attempts.items()
            if not (
                (scenario is None or key[1] is scenario)
                and (job_id is None or key[0] == job_id)
            )
        }

    def emit(self, event: RecoveryEvent) -> None:
        self._events.append(event)
        logger.info("[%s] %s", event.event_type.value, event.detail)

    def increment(self, scenario: FailureScenario, job_id: str) -> int:
        key = (job_id, scenario)
        count = self._attempts.get(key, 0) + 1
        self._attempts[key] = count
        return count


Handler = Callable[
    [RecoveryStep, dict[str, Any]],
    RecoveryStepResult | bool,
]


class RecoveryEngine:
    """Prepare recovery effects, run a retry, and verify its outcome."""

    def __init__(
        self,
        recipes: dict[FailureScenario, RecoveryRecipe] | None = None,
        *,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._recipes = recipes or DEFAULT_RECIPES
        self._context = RecoveryContext()
        self._handlers: dict[RecoveryStepType, Handler] = {}
        self._sleep = sleep

    @property
    def context(self) -> RecoveryContext:
        return self._context

    def register_handler(
        self,
        step_type: RecoveryStepType,
        handler: Handler,
    ) -> None:
        self._handlers[step_type] = handler

    def recipe_for(self, scenario: FailureScenario) -> RecoveryRecipe:
        try:
            return self._recipes[scenario]
        except KeyError as error:
            raise ValueError(
                f"No recovery recipe for scenario: {scenario.value}"
            ) from error

    def classify(
        self,
        error: BaseException,
        context: dict[str, Any] | None = None,
    ) -> FailureClassification:
        """Classify by typed error/status first, with an unknown safe fallback."""

        context = context or {}
        status_code = status_code_from_error(error)
        error_type = type(error).__name__
        metadata = {
            "error_type": error_type,
            "error_module": type(error).__module__,
            "status_code": status_code,
        }

        if isinstance(error, UnsupportedChallengeError):
            scenario = (
                FailureScenario.CLOUDFLARE_CHALLENGE
                if error.evidence.challenge_type.value == "cloudflare"
                else FailureScenario.CAPTCHA_BLOCKED
            )
        elif isinstance(error, RateLimitError) or status_code == 429:
            scenario = FailureScenario.RATE_LIMITED
        elif isinstance(error, LLMParseError) or isinstance(
            error, json.JSONDecodeError
        ):
            scenario = FailureScenario.JSON_PARSE_ERROR
        elif isinstance(error, LLMExtractionError):
            scenario = FailureScenario.LLM_EXTRACTION_FAILED
        elif isinstance(error, LLMProviderError):
            scenario = FailureScenario.LLM_PROVIDER_ERROR
        elif isinstance(error, EmptyPageError):
            scenario = FailureScenario.EMPTY_PAGE
        elif isinstance(error, BrowserCrashedError) or error_type in {
            "InvalidSessionIdException",
            "NoSuchWindowException",
            "WebDriverException",
        }:
            scenario = FailureScenario.BROWSER_CRASH
        elif isinstance(
            error,
            (NetworkFetchError, TimeoutError, ConnectionError),
        ) or error_type in {"TimeoutException", "ReadTimeout", "ConnectTimeout"}:
            scenario = FailureScenario.NETWORK_TIMEOUT
        elif status_code in {408, 504}:
            scenario = FailureScenario.NETWORK_TIMEOUT
        elif status_code is not None and status_code >= 500:
            scenario = (
                FailureScenario.LLM_PROVIDER_ERROR
                if context.get("component") == "llm"
                else FailureScenario.UNKNOWN
            )
        else:
            scenario = FailureScenario.UNKNOWN

        return FailureClassification(scenario, metadata)

    def classify_error(
        self,
        error: BaseException,
        context: dict[str, Any] | None = None,
    ) -> FailureScenario:
        """Compatibility helper returning only the stable scenario."""

        return self.classify(error, context).scenario

    @staticmethod
    def _normalize_handler_result(
        value: RecoveryStepResult | bool,
    ) -> RecoveryStepResult:
        if isinstance(value, RecoveryStepResult):
            return value
        return RecoveryStepResult(
            RecoveryStepStatus.APPLIED if value else RecoveryStepStatus.FAILED
        )

    def _execute_default(
        self,
        step: RecoveryStep,
        context: dict[str, Any],
        attempt: int,
    ) -> RecoveryStepResult:
        if step.step_type is RecoveryStepType.RETRY_WITH_BACKOFF:
            base_delay = float(step.params.get("base_delay", 2))
            max_wait = float(step.params.get("max_wait", 30))
            delay = min(base_delay * (2 ** max(0, attempt - 1)), max_wait)
            self._sleep(delay)
            return RecoveryStepResult(
                RecoveryStepStatus.APPLIED,
                f"Waited {delay:.1f}s",
                {"backoff_seconds": delay},
            )
        if step.step_type is RecoveryStepType.WAIT_COOLDOWN:
            duration = float(step.params.get("duration", 30))
            self._sleep(duration)
            return RecoveryStepResult(
                RecoveryStepStatus.APPLIED,
                f"Waited {duration:.1f}s",
                {"cooldown_seconds": duration},
            )
        if step.step_type is RecoveryStepType.INCREASE_WAIT:
            additional = float(step.params.get("additional_seconds", 3))
            context["wait_seconds"] = (
                float(context.get("wait_seconds", 0.0)) + additional
            )
            return RecoveryStepResult(
                RecoveryStepStatus.APPLIED,
                "Browser wait updated",
                {"wait_seconds": context["wait_seconds"]},
            )
        if step.step_type is RecoveryStepType.REDUCE_CONTENT:
            max_chars = int(step.params.get("max_chars", 25_000))
            context["max_content_chars"] = max_chars
            return RecoveryStepResult(
                RecoveryStepStatus.APPLIED,
                "LLM content limit updated",
                {"max_content_chars": max_chars},
            )
        if step.step_type is RecoveryStepType.RETRY_REQUEST:
            context["retry_requested"] = True
            return RecoveryStepResult(
                RecoveryStepStatus.APPLIED,
                "Caller will execute and verify one retry",
                {"retry_requested": True},
            )
        if step.step_type in {
            RecoveryStepType.SKIP_AND_LOG,
            RecoveryStepType.WAIT_FOR_CHALLENGE,
        }:
            return RecoveryStepResult(
                RecoveryStepStatus.SKIPPED_BY_POLICY,
                "Automatic challenge handling is disabled by policy",
            )
        return RecoveryStepResult(
            RecoveryStepStatus.UNSUPPORTED,
            f"No handler registered for {step.step_type.value}",
        )

    @staticmethod
    def _event_type_for(
        step_result: RecoveryStepResult,
    ) -> RecoveryEventType:
        return {
            RecoveryStepStatus.APPLIED: RecoveryEventType.STEP_APPLIED,
            RecoveryStepStatus.UNSUPPORTED: RecoveryEventType.STEP_UNSUPPORTED,
            RecoveryStepStatus.FAILED: RecoveryEventType.STEP_FAILED,
            RecoveryStepStatus.SKIPPED_BY_POLICY: RecoveryEventType.STEP_SKIPPED,
        }[step_result.status]

    def attempt(
        self,
        scenario: FailureScenario,
        context: dict[str, Any] | None = None,
        *,
        job_id: str = "global",
        classification: FailureClassification | None = None,
    ) -> RecoveryResult:
        """Apply a recipe; this alone never reports recovery success."""

        context = context if context is not None else {}
        recipe = self.recipe_for(scenario)
        current_attempts = self._context.attempt_count(scenario, job_id)
        if current_attempts >= recipe.max_attempts:
            reason = (
                f"Max attempts ({recipe.max_attempts}) exhausted for {scenario.value}"
            )
            self._context.emit(
                RecoveryEvent(
                    RecoveryEventType.RECOVERY_ATTEMPTED,
                    scenario,
                    result_type=RecoveryResultType.ESCALATION_REQUIRED,
                    detail=reason,
                )
            )
            self._context.emit(
                RecoveryEvent(
                    RecoveryEventType.RECOVERY_ESCALATED,
                    scenario,
                    result_type=RecoveryResultType.ESCALATION_REQUIRED,
                    detail=recipe.escalation_policy.value,
                )
            )
            return RecoveryResult(
                RecoveryResultType.ESCALATION_REQUIRED,
                reason=reason,
                classification=classification,
            )

        attempt_number = self._context.increment(scenario, job_id)
        self._context.emit(
            RecoveryEvent(
                RecoveryEventType.RECOVERY_ATTEMPTED,
                scenario,
                detail=(
                    f"Attempt {attempt_number}/{recipe.max_attempts} for job {job_id}"
                ),
            )
        )

        step_results: list[RecoveryStepResult] = []
        for index, step in enumerate(recipe.steps):
            handler = self._handlers.get(step.step_type)
            try:
                if handler is None:
                    step_result = self._execute_default(
                        step,
                        context,
                        attempt_number,
                    )
                else:
                    step_result = self._normalize_handler_result(handler(step, context))
            except Exception as error:
                step_result = RecoveryStepResult(
                    RecoveryStepStatus.FAILED,
                    f"Handler failed with {type(error).__name__}",
                )

            step_results.append(step_result)
            self._context.emit(
                RecoveryEvent(
                    self._event_type_for(step_result),
                    scenario,
                    step=step,
                    detail=step_result.detail or step.description,
                )
            )
            if not step_result.applied:
                result_type = (
                    RecoveryResultType.PARTIAL_RECOVERY
                    if any(item.applied for item in step_results[:-1])
                    else RecoveryResultType.ESCALATION_REQUIRED
                )
                result = RecoveryResult(
                    result_type,
                    steps_taken=sum(item.applied for item in step_results),
                    step_results=step_results,
                    remaining_steps=recipe.steps[index + 1 :],
                    reason=step_result.detail,
                    classification=classification,
                )
                terminal_event = (
                    RecoveryEventType.RECOVERY_FAILED
                    if result_type is RecoveryResultType.PARTIAL_RECOVERY
                    else RecoveryEventType.RECOVERY_ESCALATED
                )
                self._context.emit(
                    RecoveryEvent(
                        terminal_event,
                        scenario,
                        result_type=result_type,
                        detail=step_result.detail,
                    )
                )
                return result

        if not context.get("retry_requested"):
            result = RecoveryResult(
                RecoveryResultType.ESCALATION_REQUIRED,
                steps_taken=len(step_results),
                step_results=step_results,
                reason="Recipe applied no retry request",
                classification=classification,
            )
            self._context.emit(
                RecoveryEvent(
                    RecoveryEventType.RECOVERY_ESCALATED,
                    scenario,
                    result_type=result.result_type,
                    detail=result.reason,
                )
            )
            return result

        return RecoveryResult(
            RecoveryResultType.RETRY_READY,
            steps_taken=len(step_results),
            step_results=step_results,
            classification=classification,
        )

    def recover_from_error(
        self,
        error: BaseException,
        context: dict[str, Any],
        retry: Callable[[], Any],
        *,
        job_id: str,
    ) -> RecoveryResult:
        """Apply recovery and emit success only after ``retry`` returns."""

        classification = self.classify(error, context)
        prepared = self.attempt(
            classification.scenario,
            context,
            job_id=job_id,
            classification=classification,
        )
        if not prepared.ready_for_retry:
            return prepared

        try:
            value = retry()
        except Exception as retry_error:
            reason = f"Retry failed with {type(retry_error).__name__}"
            result = RecoveryResult(
                RecoveryResultType.PARTIAL_RECOVERY,
                steps_taken=prepared.steps_taken,
                step_results=prepared.step_results,
                reason=reason,
                classification=self.classify(retry_error, context),
            )
            self._context.emit(
                RecoveryEvent(
                    RecoveryEventType.RECOVERY_FAILED,
                    classification.scenario,
                    result_type=result.result_type,
                    detail=reason,
                )
            )
            return result

        result = RecoveryResult(
            RecoveryResultType.RECOVERED,
            steps_taken=prepared.steps_taken,
            step_results=prepared.step_results,
            value=value,
            classification=classification,
        )
        self._context.emit(
            RecoveryEvent(
                RecoveryEventType.RECOVERY_SUCCEEDED,
                classification.scenario,
                result_type=result.result_type,
                detail="Subsequent retry completed successfully",
            )
        )
        self._context.reset(classification.scenario, job_id)
        return result

    def attempt_from_error(
        self,
        error: BaseException,
        context: dict[str, Any] | None = None,
        *,
        job_id: str = "global",
    ) -> RecoveryResult:
        """Prepare recovery without making an unverifiable success claim."""

        context = context if context is not None else {}
        classification = self.classify(error, context)
        return self.attempt(
            classification.scenario,
            context,
            job_id=job_id,
            classification=classification,
        )

    def should_retry(
        self,
        scenario: FailureScenario,
        *,
        job_id: str = "global",
    ) -> bool:
        recipe = self._recipes.get(scenario)
        return bool(
            recipe
            and self._context.attempt_count(scenario, job_id) < recipe.max_attempts
        )
