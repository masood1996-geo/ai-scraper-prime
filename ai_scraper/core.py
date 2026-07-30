"""Reachable AI Scraper pipeline with measured, bounded adaptation."""

from __future__ import annotations

import csv
import json
import logging
import re
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ai_scraper.browser import BrowserEngine
from ai_scraper.errors import (
    EmptyPageError,
    ScrapeRecoveryError,
    UnsupportedChallengeError,
)
from ai_scraper.learner import Learner
from ai_scraper.llm import LLMClient
from ai_scraper.memory import Memory
from ai_scraper.recovery import (
    RecoveryEngine,
    RecoveryStep,
    RecoveryStepResult,
    RecoveryStepStatus,
    RecoveryStepType,
)
from ai_scraper.redaction import redact_url

logger = logging.getLogger(__name__)


class AIScraper:
    """Extract structured records and retain only measured domain strategies."""

    def __init__(
        self,
        provider: str = "openrouter",
        api_key: str = "",
        model: str | None = None,
        headless: bool = True,
        timeout: int = 30,
        wait_seconds: float = 2.0,
        learning: bool = True,
        memory_path: str | None = None,
        *,
        fallback_model: str | None = None,
        minimum_refinement_improvement: float = 0.05,
        browser: BrowserEngine | None = None,
        llm_client: LLMClient | None = None,
        memory: Memory | None = None,
        recovery_engine: RecoveryEngine | None = None,
    ):
        self.default_wait = wait_seconds
        self.learning_enabled = learning
        self.fallback_model = fallback_model
        self.minimum_refinement_improvement = minimum_refinement_improvement
        self._browser = browser or BrowserEngine(
            headless=headless,
            timeout=timeout,
        )
        self._llm = llm_client or LLMClient(
            provider=provider,
            api_key=api_key,
            model=model,
        )
        if learning:
            self._memory = memory or Memory(
                **({"db_path": memory_path} if memory_path else {})
            )
            self._learner = Learner(self._memory, self._llm)
        else:
            self._memory = memory
            self._learner = Learner(self._memory, self._llm) if self._memory else None

        self._recovery = recovery_engine or RecoveryEngine()
        self._register_recovery_handlers()
        self.last_batch_failures: dict[str, str] = {}

    def _register_recovery_handlers(self) -> None:
        self._recovery.register_handler(
            RecoveryStepType.RESTART_BROWSER,
            self._handle_restart_browser,
        )
        self._recovery.register_handler(
            RecoveryStepType.CLEAR_COOKIES,
            self._handle_clear_cookies,
        )
        self._recovery.register_handler(
            RecoveryStepType.ROTATE_USER_AGENT,
            self._handle_rotate_user_agent,
        )
        self._recovery.register_handler(
            RecoveryStepType.RETRY_WITH_FALLBACK_MODEL,
            self._handle_fallback_model,
        )

    @staticmethod
    def _resolve_schema(
        schema: dict[str, Any] | str,
    ) -> dict[str, Any]:
        if isinstance(schema, dict):
            return schema
        from ai_scraper.schemas import Schema

        return Schema.get(schema)

    def scrape(
        self,
        url: str,
        schema: dict[str, Any] | str,
        instructions: str = "",
        raw_html: str | None = None,
    ) -> list[dict]:
        """Run the five-stage extraction path and return structured records."""

        extraction_schema = self._resolve_schema(schema)
        domain = urlparse(url).netloc
        if not domain:
            raise ValueError(f"URL must include a host: {url}")

        learned = {
            "wait_seconds": self.default_wait,
            "extra_instructions": "",
            "cleaning_rules": [],
            "learned": False,
        }
        profile_before = None
        if self._learner:
            assert self._memory is not None
            learned = self._learner.get_optimized_settings(
                url,
                extraction_schema,
            )
            profile_before = self._memory.get_domain_profile(domain)

        combined_instructions = instructions
        if learned["extra_instructions"]:
            combined_instructions = (
                f"{instructions}\n\n"
                "[Accepted domain-specific refinement]\n"
                f"{learned['extra_instructions']}"
            ).strip()

        runtime: dict[str, Any] = {
            "url": url,
            "wait_seconds": (
                learned["wait_seconds"] if learned["learned"] else self.default_wait
            ),
            "max_content_chars": 50_000,
            "fallback_model": self.fallback_model,
            "model": self._llm.model,
            "component": "browser",
            "retry_requested": False,
        }
        job_id = uuid.uuid4().hex
        started = time.perf_counter()

        def run_once():
            return self._run_once(
                url,
                extraction_schema,
                combined_instructions,
                runtime,
                raw_html,
            )

        try:
            results, html, cleaned, applied_rule_ids = run_once()
        except Exception as error:
            recovery = self._recovery.recover_from_error(
                error,
                runtime,
                run_once,
                job_id=job_id,
            )
            if not recovery.success:
                scenario = (
                    recovery.classification.scenario.value
                    if recovery.classification
                    else "unknown"
                )
                raise ScrapeRecoveryError(
                    f"Scrape failed after bounded recovery ({scenario}): "
                    f"{recovery.reason or recovery.result_type.value}",
                    cause=error,
                ) from error
            results, html, cleaned, applied_rule_ids = recovery.value

        learner = self._learner
        memory = self._memory
        if learner is None or memory is None:
            return results

        quality, diagnostics = learner.learn_from_results(
            url,
            extraction_schema,
            results,
            time.perf_counter() - started,
            self._llm.model,
        )
        prior_quality = (
            float(profile_before["avg_quality"]) if profile_before else quality
        )
        for rule_id in applied_rule_ids:
            memory.record_cleaning_rule_outcome(
                rule_id,
                quality=quality,
                baseline_quality=prior_quality,
            )

        self._record_cleaning_candidates(domain, html, diagnostics)
        learner.learn_optimal_wait(
            domain,
            quality,
            float(runtime["wait_seconds"]),
        )

        if not learner.should_retry(quality, attempt=0):
            return results

        improved = self._try_measured_refinement(
            url=url,
            schema=extraction_schema,
            original_results=results,
            baseline_quality=quality,
            diagnostics=diagnostics,
            cleaned_text=cleaned,
            html=html,
            runtime=runtime,
            raw_html=raw_html,
            original_instructions=instructions,
        )
        return improved if improved is not None else results

    def _run_once(
        self,
        url: str,
        schema: dict[str, Any],
        instructions: str,
        runtime: dict[str, Any],
        raw_html: str | None,
    ) -> tuple[list[dict], str, str, list[int]]:
        if raw_html is None:
            runtime["component"] = "browser"
            html = self._browser.fetch(
                url,
                wait_seconds=float(runtime["wait_seconds"]),
            )
        else:
            challenge = self._browser.detect_challenge(raw_html)
            if challenge is not None:
                raise UnsupportedChallengeError(challenge)
            html = raw_html

        cleaned, applied_rule_ids = self._clean_html_with_rules(
            html,
            urlparse(url).netloc,
        )
        if len(cleaned) < 50:
            raise EmptyPageError("Page contained too little extractable text")

        runtime["component"] = "llm"
        results = self._llm.extract(
            text=cleaned,
            schema=schema,
            instructions=instructions,
            max_chars=int(runtime["max_content_chars"]),
        )
        self._resolve_relative_urls(results, url)
        return results, html, cleaned, applied_rule_ids

    def _try_measured_refinement(
        self,
        *,
        url: str,
        schema: dict[str, Any],
        original_results: list[dict],
        baseline_quality: float,
        diagnostics: dict[str, Any],
        cleaned_text: str,
        html: str,
        runtime: dict[str, Any],
        raw_html: str | None,
        original_instructions: str,
    ) -> list[dict] | None:
        learner = self._learner
        memory = self._memory
        assert learner is not None and memory is not None
        try:
            strategy = learner.generate_improvement_strategy(
                url,
                schema,
                original_results,
                diagnostics,
                cleaned_text[:5000],
            )
        except Exception as error:
            logger.warning(
                "Prompt candidate generation failed with %s",
                type(error).__name__,
            )
            return None
        if not strategy.get("retry"):
            return None

        if strategy["wait_seconds_adjust"] > 0 and raw_html is None:
            runtime["wait_seconds"] += strategy["wait_seconds_adjust"]
            html = self._browser.fetch(
                url,
                wait_seconds=float(runtime["wait_seconds"]),
            )
            cleaned_text, _ = self._clean_html_with_rules(
                html,
                urlparse(url).netloc,
            )

        retry_instructions = (
            f"{original_instructions}\n\n"
            "[Candidate retry instructions]\n"
            f"{strategy['extra_instructions']}"
        ).strip()
        retry_started = time.perf_counter()
        try:
            new_results = self._llm.extract(
                text=cleaned_text,
                schema=schema,
                instructions=retry_instructions,
                max_chars=int(runtime["max_content_chars"]),
            )
        except Exception as error:
            logger.warning(
                "Measured refinement retry failed with %s",
                type(error).__name__,
            )
            return None
        retry_latency_ms = (time.perf_counter() - retry_started) * 1000
        self._resolve_relative_urls(new_results, url)
        new_quality, new_diagnostics = learner.score_results(
            new_results,
            schema,
            url,
        )

        accepted = new_quality - baseline_quality >= self.minimum_refinement_improvement
        prompt_candidate = strategy.get("prompt_candidate")
        if prompt_candidate:
            usage = getattr(self._llm, "last_usage", {})
            candidate_id = memory.save_prompt_candidate(
                domain=urlparse(url).netloc,
                schema_name=learner._schema_name(schema),
                extra_instructions=prompt_candidate["text"],
                baseline_quality=baseline_quality,
                minimum_improvement=self.minimum_refinement_improvement,
                latency_ms=(prompt_candidate["latency_ms"] + retry_latency_ms),
                input_tokens=(
                    prompt_candidate["input_tokens"] + int(usage.get("input_tokens", 0))
                ),
                output_tokens=(
                    prompt_candidate["output_tokens"]
                    + int(usage.get("output_tokens", 0))
                ),
            )
            accepted = memory.evaluate_prompt_candidate(
                candidate_id,
                new_quality,
            )

        learner.learn_from_results(
            url,
            schema,
            new_results,
            retry_latency_ms / 1000,
            self._llm.model,
        )
        logger.info(
            "Candidate refinement %s (proxy %.3f -> %.3f, confidence %.3f)",
            "accepted" if accepted else "rejected",
            baseline_quality,
            new_quality,
            new_diagnostics["confidence"],
        )
        return new_results if accepted else None

    def _record_cleaning_candidates(
        self,
        domain: str,
        html: str,
        diagnostics: dict[str, Any],
    ) -> None:
        learner = self._learner
        memory = self._memory
        if learner is None or memory is None:
            return
        for candidate in learner.propose_cleaning_rules(
            html,
            diagnostics,
        ):
            memory.record_cleaning_rule_evidence(
                domain,
                candidate["rule_type"],
                candidate["selector"],
                reason=candidate["reason"],
                evidence=candidate["evidence"],
                confidence=candidate["confidence"],
            )

    @staticmethod
    def _resolve_relative_urls(results: list[dict], base_url: str) -> None:
        for item in results:
            for key in ("url", "image_url", "link"):
                value = item.get(key)
                if value and not str(value).startswith(("http://", "https://")):
                    item[key] = urljoin(base_url, str(value))

    def scrape_multiple(
        self,
        urls: list[str],
        schema: dict[str, Any] | str,
        instructions: str = "",
    ) -> list[dict]:
        """Scrape each URL independently and expose per-domain failures."""

        all_results: list[dict] = []
        self.last_batch_failures = {}
        for url in urls:
            try:
                results = self.scrape(url, schema, instructions)
            except Exception as error:
                self.last_batch_failures[url] = type(error).__name__
                logger.error(
                    "Batch item failed for %s with %s",
                    redact_url(url),
                    type(error).__name__,
                )
                continue
            for item in results:
                item["_source_url"] = url
            all_results.extend(results)
        return all_results

    def ask_page(self, url: str, question: str) -> str:
        html = self._browser.fetch(url, wait_seconds=self.default_wait)
        cleaned = self._clean_html(html, urlparse(url).netloc)
        return self._llm.ask(
            "Answer the question using only the supplied page content.\n\n"
            f"Question: {question}\n\nPage content:\n{cleaned[:30000]}"
        )

    def feedback(
        self,
        url: str,
        schema: dict[str, Any] | str,
        feedback_type: str,
        details: str = "",
    ) -> None:
        if not self._memory:
            logger.warning("Strategy memory is disabled; feedback was not saved")
            return
        assert self._learner is not None
        extraction_schema = self._resolve_schema(schema)
        self._memory.record_feedback(
            url,
            self._learner._schema_name(extraction_schema),
            feedback_type,
            details,
        )
        if feedback_type == "cleaning_rule":
            try:
                payload = json.loads(details)
                self._memory.save_cleaning_rule(
                    urlparse(url).netloc,
                    payload["rule_type"],
                    payload["selector"],
                )
            except (json.JSONDecodeError, KeyError, ValueError) as error:
                raise ValueError(
                    "cleaning_rule feedback requires JSON with rule_type and selector"
                ) from error

    def stats(self) -> dict[str, Any]:
        if not self._memory:
            return {"learning": "disabled"}
        return self._memory.get_stats()

    def diagnose(self, domain: str) -> dict[str, Any]:
        if not self._learner:
            return {"error": "Strategy memory is disabled"}
        return self._learner.diagnose_domain(domain)

    def _clean_html_with_rules(
        self,
        html: str,
        domain: str = "",
    ) -> tuple[str, list[int]]:
        soup = BeautifulSoup(html, "lxml")
        for name in (
            "script",
            "style",
            "noscript",
            "svg",
            "iframe",
            "nav",
            "footer",
            "header",
            "aside",
        ):
            for tag in soup.find_all(name):
                tag.decompose()
        for tag in soup.select("[style]"):
            if re.search(
                r"display\s*:\s*none",
                str(tag.get("style") or ""),
                re.IGNORECASE,
            ):
                tag.decompose()
        for pattern in (
            r"cookie",
            r"consent",
            r"modal",
            r"popup",
            r"overlay",
            r"gdpr",
        ):
            for tag in soup.find_all(class_=re.compile(pattern, re.I)):
                tag.decompose()

        applied_rule_ids: list[int] = []
        if domain and self._memory:
            for rule in self._memory.get_cleaning_rules(domain):
                removed = 0
                try:
                    if rule["rule_type"] == "class":
                        matches = [
                            tag
                            for tag in soup.find_all(class_=True)
                            if rule["selector"]
                            in (
                                tag.attrs.get("class")
                                if isinstance(
                                    tag.attrs.get("class"),
                                    list,
                                )
                                else []
                            )
                        ]
                    elif rule["rule_type"] == "id":
                        match = soup.find(id=rule["selector"])
                        matches = [match] if match else []
                    elif rule["rule_type"] == "tag":
                        matches = list(soup.find_all(rule["selector"]))
                    else:
                        matches = []
                    for tag in matches:
                        tag.decompose()
                        removed += 1
                except Exception as error:
                    logger.warning(
                        "Cleaning rule %s failed with %s",
                        rule["id"],
                        type(error).__name__,
                    )
                if removed:
                    applied_rule_ids.append(int(rule["id"]))

        text = soup.get_text(separator="\n", strip=True)
        return re.sub(r"\n{3,}", "\n\n", text).strip(), applied_rule_ids

    def _clean_html(self, html: str, domain: str = "") -> str:
        text, _ = self._clean_html_with_rules(html, domain)
        return text

    def save_json(self, results: list[dict], path: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(results, handle, indent=2, ensure_ascii=False)

    def save_csv(self, results: list[dict], path: str) -> None:
        if not results:
            return
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        fields = list(dict.fromkeys(key for row in results for key in row))
        with open(path, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(results)

    def recovery_stats(self) -> dict[str, Any]:
        events = self._recovery.context.events
        return {
            "total_events": len(events),
            "verified_recoveries": sum(
                event.event_type.value == "recovery.succeeded" for event in events
            ),
            "escalations": sum(
                event.event_type.value == "recovery.escalated" for event in events
            ),
            "events": [event.to_dict() for event in events[-10:]],
        }

    def _handle_restart_browser(
        self,
        step: RecoveryStep,
        context: dict[str, Any],
    ) -> RecoveryStepResult:
        applied = self._browser.restart()
        return RecoveryStepResult(
            RecoveryStepStatus.APPLIED if applied else RecoveryStepStatus.FAILED,
            "Browser session restarted" if applied else "Browser restart failed",
            {"browser_restarted": applied},
        )

    def _handle_clear_cookies(
        self,
        step: RecoveryStep,
        context: dict[str, Any],
    ) -> RecoveryStepResult:
        applied = self._browser.clear_state()
        return RecoveryStepResult(
            RecoveryStepStatus.APPLIED if applied else RecoveryStepStatus.FAILED,
            "Browser state cleared" if applied else "Browser state clear failed",
            {"browser_state_cleared": applied},
        )

    def _handle_rotate_user_agent(
        self,
        step: RecoveryStep,
        context: dict[str, Any],
    ) -> RecoveryStepResult:
        applied = self._browser.rotate_user_agent()
        return RecoveryStepResult(
            RecoveryStepStatus.APPLIED if applied else RecoveryStepStatus.UNSUPPORTED,
            (
                "User agent changed for the next browser session"
                if applied
                else "No alternate user agent configured"
            ),
            {"user_agent": self._browser.user_agent} if applied else {},
        )

    def _handle_fallback_model(
        self,
        step: RecoveryStep,
        context: dict[str, Any],
    ) -> RecoveryStepResult:
        fallback_model = context.get("fallback_model")
        if not fallback_model:
            return RecoveryStepResult(
                RecoveryStepStatus.UNSUPPORTED,
                "No fallback model configured",
            )
        applied = self._llm.switch_model(str(fallback_model))
        if applied:
            context["model"] = self._llm.model
        return RecoveryStepResult(
            RecoveryStepStatus.APPLIED if applied else RecoveryStepStatus.UNSUPPORTED,
            (
                "Fallback model selected"
                if applied
                else "Fallback model is already active"
            ),
            {"model": self._llm.model} if applied else {},
        )

    def close(self) -> None:
        self._browser.close()
        if self._memory:
            self._memory.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
