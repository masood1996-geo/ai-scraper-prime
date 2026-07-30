from __future__ import annotations

import json

import pytest

from ai_scraper.errors import (
    BrowserCrashedError,
    ChallengeEvidence,
    ChallengeType,
    LLMParseError,
    LLMProviderError,
    UnsupportedChallengeError,
)
from ai_scraper.recovery import (
    FailureScenario,
    RecoveryEngine,
    RecoveryEventType,
    RecoveryResultType,
    RecoveryStepStatus,
)


@pytest.mark.parametrize(
    ("error", "scenario"),
    [
        (TimeoutError(), FailureScenario.NETWORK_TIMEOUT),
        (BrowserCrashedError(), FailureScenario.BROWSER_CRASH),
        (LLMParseError(), FailureScenario.JSON_PARSE_ERROR),
        (
            LLMProviderError("provider", status_code=503),
            FailureScenario.LLM_PROVIDER_ERROR,
        ),
        (
            UnsupportedChallengeError(
                ChallengeEvidence(ChallengeType.CLOUDFLARE, "cf-chl-")
            ),
            FailureScenario.CLOUDFLARE_CHALLENGE,
        ),
        (RuntimeError("timeout is only a word"), FailureScenario.UNKNOWN),
    ],
)
def test_typed_failure_classification(error, scenario):
    engine = RecoveryEngine(sleep=lambda _: None)
    classification = engine.classify(error)
    assert classification.scenario is scenario
    assert classification.metadata["error_type"] == type(error).__name__


def test_missing_handler_is_unsupported_never_success():
    engine = RecoveryEngine(sleep=lambda _: None)
    result = engine.attempt(
        FailureScenario.BROWSER_CRASH,
        {},
        job_id="job",
    )
    assert not result.success
    assert result.step_results[0].status is RecoveryStepStatus.UNSUPPORTED
    assert not any(
        event.event_type is RecoveryEventType.RECOVERY_SUCCEEDED
        for event in engine.context.events
    )


def test_context_mutations_are_consumed_by_verified_retry():
    engine = RecoveryEngine(sleep=lambda _: None)
    context = {"wait_seconds": 2.0, "max_content_chars": 50_000}
    observed = {}

    result = engine.recover_from_error(
        LLMParseError("invalid"),
        context,
        lambda: observed.update(context) or ["ok"],
        job_id="job",
    )

    assert result.success
    assert observed["max_content_chars"] == 25_000
    event_types = [event.event_type for event in engine.context.events]
    assert event_types[0] is RecoveryEventType.RECOVERY_ATTEMPTED
    assert event_types[-1] is RecoveryEventType.RECOVERY_SUCCEEDED


def test_failed_retry_does_not_emit_success():
    engine = RecoveryEngine(sleep=lambda _: None)
    result = engine.recover_from_error(
        json.JSONDecodeError("bad", "x", 0),
        {"max_content_chars": 50_000},
        lambda: (_ for _ in ()).throw(RuntimeError("still broken")),
        job_id="job",
    )
    assert result.result_type is RecoveryResultType.PARTIAL_RECOVERY
    assert not any(
        event.event_type is RecoveryEventType.RECOVERY_SUCCEEDED
        for event in engine.context.events
    )


def test_recovery_attempt_limit_escalates():
    engine = RecoveryEngine(sleep=lambda _: None)
    context = {"max_content_chars": 50_000}
    engine.attempt(FailureScenario.JSON_PARSE_ERROR, context, job_id="job")
    engine.attempt(FailureScenario.JSON_PARSE_ERROR, context, job_id="job")
    exhausted = engine.attempt(
        FailureScenario.JSON_PARSE_ERROR,
        context,
        job_id="job",
    )
    assert exhausted.result_type is RecoveryResultType.ESCALATION_REQUIRED


def test_unsupported_challenge_is_skipped_by_policy():
    engine = RecoveryEngine(sleep=lambda _: None)
    result = engine.attempt(
        FailureScenario.CAPTCHA_BLOCKED,
        {},
        job_id="job",
    )
    assert result.step_results[0].status is RecoveryStepStatus.SKIPPED_BY_POLICY
    assert result.result_type is RecoveryResultType.ESCALATION_REQUIRED
