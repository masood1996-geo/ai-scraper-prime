"""Measured extraction-quality proxy and domain-scoped strategy proposals."""

from __future__ import annotations

import json
import logging
import re
import time
from collections import Counter
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from ai_scraper.memory import Memory

logger = logging.getLogger(__name__)

QUALITY_EXCELLENT = 0.85
QUALITY_GOOD = 0.60
QUALITY_POOR = 0.35
MAX_IMPROVEMENT_ATTEMPTS = 1

_GARBAGE_PATTERNS = (
    "lorem ipsum",
    "placeholder",
    "test data",
    "click here",
    "read more",
    "loading...",
)
_NOISE_CLASS_TOKENS = re.compile(
    r"(?:^|[-_])(ad|advert|promo|sponsor|newsletter|related|recommend)(?:$|[-_])",
    re.IGNORECASE,
)


def _is_present(value: Any) -> bool:
    return value is not None and str(value).strip() not in {
        "",
        "N/A",
        "null",
        "undefined",
        "None",
        "-",
    }


class Learner:
    """Record heuristics and accept strategies only after measured improvement."""

    def __init__(self, memory: Memory, llm_client=None):
        self.memory = memory
        self._llm = llm_client

    def set_llm(self, llm_client) -> None:
        self._llm = llm_client

    @staticmethod
    def _validate_value(
        field: str,
        value: Any,
        specification: Any,
    ) -> tuple[bool, str | None]:
        """Run deterministic plausibility checks where a schema provides clues."""

        if not _is_present(value):
            if isinstance(specification, dict) and specification.get("required"):
                return False, f"{field}:required"
            return True, None

        text = str(value).strip()
        field_lower = field.lower()
        spec_type = (
            str(specification.get("type", "")).lower()
            if isinstance(specification, dict)
            else ""
        )

        if "url" in field_lower or spec_type == "url":
            parsed = urlparse(text)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                return False, f"{field}:invalid_url"
        elif "email" in field_lower or spec_type == "email":
            if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", text):
                return False, f"{field}:invalid_email"
        elif (
            "date" in field_lower
            or field_lower.endswith("_from")
            or spec_type == "date"
        ):
            normalized = text.replace("Z", "+00:00")
            try:
                datetime.fromisoformat(normalized)
            except ValueError:
                if not re.search(
                    r"\b(?:19|20)\d{2}\b|\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b",
                    text,
                ):
                    return False, f"{field}:implausible_date"
        elif field_lower in {"price", "salary", "original_price"}:
            if not re.search(r"\d", text):
                return False, f"{field}:missing_number"
            if re.search(r"(?:^|\s)-\s*\d", text):
                return False, f"{field}:negative_value"
        elif spec_type in {"number", "integer"}:
            try:
                number = float(value)
            except (TypeError, ValueError):
                return False, f"{field}:invalid_number"
            minimum = specification.get("min")
            maximum = specification.get("max")
            if minimum is not None and number < float(minimum):
                return False, f"{field}:below_minimum"
            if maximum is not None and number > float(maximum):
                return False, f"{field}:above_maximum"
        elif field_lower in {"rooms", "rating", "reviews_count"}:
            match = re.search(r"-?\d+(?:[.,]\d+)?", text)
            if match and float(match.group(0).replace(",", ".")) < 0:
                return False, f"{field}:negative_value"

        return True, None

    def score_results(
        self,
        results: list[dict],
        schema: dict[str, Any],
        url: str = "",
    ) -> tuple[float, dict[str, Any]]:
        """Return a heuristic extraction-quality proxy, not a truth score."""

        diagnostics: dict[str, Any] = {
            "score_kind": "extraction_quality_proxy",
            "semantic_correctness_guaranteed": False,
            "results_count": len(results),
            "components": {
                "fill_rate": 0.0,
                "basic_validity": 0.0,
                "uniqueness": 0.0,
                "content_quality": 0.0,
                "deterministic_validation": 0.0,
                "result_count": 0.0,
            },
            "fill_rate": 0.0,
            "validity_rate": 0.0,
            "uniqueness_rate": 0.0,
            "content_quality": 0.0,
            "deterministic_validation_rate": 0.0,
            "confidence": 0.0,
            "uncertainty": 1.0,
            "validation_errors": [],
            "issues": [],
        }
        if not results:
            diagnostics["issues"].append("NO_RESULTS")
            return 0.0, diagnostics

        fields = list(schema)
        total_fields = max(1, len(fields) * len(results))
        filled = 0
        basic_valid = 0
        deterministic_valid = 0
        validation_checks = 0
        validation_errors: list[str] = []

        for item in results:
            for field in fields:
                value = item.get(field)
                if _is_present(value):
                    filled += 1
                    text = str(value).strip()
                    if len(text) > 1 and text.casefold() != field.casefold():
                        basic_valid += 1
                valid, error = self._validate_value(
                    field,
                    value,
                    schema[field],
                )
                validation_checks += 1
                deterministic_valid += int(valid)
                if error:
                    validation_errors.append(error)

        fill_rate = filled / total_fields
        validity_rate = basic_valid / total_fields
        deterministic_rate = deterministic_valid / max(1, validation_checks)

        identity_field = next(
            (
                field
                for field in fields
                if field in {"url", "title", "name", "headline"}
            ),
            None,
        )
        if identity_field:
            identities = [
                str(item.get(identity_field, "")).strip().casefold() for item in results
            ]
            nonempty = [value for value in identities if value]
            uniqueness = len(set(nonempty)) / max(1, len(results))
        else:
            serialized = [
                json.dumps(item, sort_keys=True, default=str) for item in results
            ]
            uniqueness = len(set(serialized)) / len(results)

        garbage_count = sum(
            any(
                pattern in json.dumps(item, default=str).casefold()
                for pattern in _GARBAGE_PATTERNS
            )
            for item in results
        )
        content_quality = 1 - (garbage_count / len(results))
        result_count = min(len(results) / 5.0, 1.0)
        components = {
            "fill_rate": fill_rate,
            "basic_validity": validity_rate,
            "uniqueness": uniqueness,
            "content_quality": content_quality,
            "deterministic_validation": deterministic_rate,
            "result_count": result_count,
        }
        score = (
            fill_rate * 0.25
            + validity_rate * 0.20
            + uniqueness * 0.15
            + content_quality * 0.10
            + deterministic_rate * 0.20
            + result_count * 0.10
        )
        score = round(min(max(score, 0.0), 1.0), 3)

        evidence_coverage = min(1.0, len(results) / 5.0)
        confidence = round(
            min(1.0, 0.35 + 0.35 * evidence_coverage + 0.30 * deterministic_rate),
            3,
        )
        diagnostics.update(
            {
                "components": {
                    key: round(value, 3) for key, value in components.items()
                },
                "fill_rate": round(fill_rate, 3),
                "validity_rate": round(validity_rate, 3),
                "uniqueness_rate": round(uniqueness, 3),
                "content_quality": round(content_quality, 3),
                "deterministic_validation_rate": round(
                    deterministic_rate,
                    3,
                ),
                "confidence": confidence,
                "uncertainty": round(1 - confidence, 3),
                "validation_errors": sorted(set(validation_errors)),
            }
        )
        if fill_rate < 0.3:
            diagnostics["issues"].append("LOW_FILL_RATE")
        if validity_rate < 0.3:
            diagnostics["issues"].append("LOW_VALIDITY")
        if uniqueness < 0.5:
            diagnostics["issues"].append("MANY_DUPLICATES")
        if content_quality < 0.5:
            diagnostics["issues"].append("GARBAGE_CONTENT")
        if deterministic_rate < 0.7:
            diagnostics["issues"].append("SCHEMA_VALIDATION_FAILED")
        if len(results) == 1:
            diagnostics["issues"].append("ONLY_ONE_RESULT")
        return score, diagnostics

    def get_optimized_settings(
        self,
        url: str,
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        domain = urlparse(url).netloc
        schema_name = self._schema_name(schema)
        settings: dict[str, Any] = {
            "wait_seconds": 2.0,
            "extra_instructions": "",
            "cleaning_rules": [],
            "learned": False,
        }
        profile = self.memory.get_domain_profile(domain)
        if profile:
            settings["wait_seconds"] = profile["wait_seconds"]
            settings["learned"] = True
        prompt = self.memory.get_best_prompt(domain, schema_name)
        if prompt:
            settings["extra_instructions"] = prompt
            self.memory.increment_prompt_usage(domain, schema_name)
        settings["cleaning_rules"] = self.memory.get_cleaning_rules(domain)
        return settings

    def learn_from_results(
        self,
        url: str,
        schema: dict[str, Any],
        results: list[dict],
        duration: float,
        model_used: str = "",
    ) -> tuple[float, dict[str, Any]]:
        domain = urlparse(url).netloc
        quality, diagnostics = self.score_results(results, schema, url)
        self.memory.log_extraction(
            url=url,
            schema_name=self._schema_name(schema),
            results_count=len(results),
            quality_score=quality,
            confidence=diagnostics["confidence"],
            uncertainty=diagnostics["uncertainty"],
            fill_rate=diagnostics["fill_rate"],
            duration_secs=duration,
            model_used=model_used,
            error=", ".join(diagnostics["issues"]),
        )
        self.memory.update_domain_profile(
            domain,
            success=quality >= QUALITY_POOR,
            quality_score=quality,
        )
        logger.info(
            "Extraction-quality proxy %.0f%% (confidence %.0f%%, issues=%s)",
            quality * 100,
            diagnostics["confidence"] * 100,
            diagnostics["issues"] or "none",
        )
        return quality, diagnostics

    def should_retry(self, quality: float, attempt: int) -> bool:
        return quality < QUALITY_GOOD and attempt < MAX_IMPROVEMENT_ATTEMPTS

    def generate_improvement_strategy(
        self,
        url: str,
        schema: dict[str, Any],
        results: list[dict],
        diagnostics: dict[str, Any],
        cleaned_text_sample: str = "",
    ) -> dict[str, Any]:
        issues = diagnostics.get("issues", [])
        strategy: dict[str, Any] = {
            "extra_instructions": "",
            "wait_seconds_adjust": 0.0,
            "retry": True,
            "prompt_candidate": None,
        }
        if "NO_RESULTS" in issues:
            strategy["wait_seconds_adjust"] = 3.0
            strategy["extra_instructions"] = (
                "Look for repeated content records after dynamic rendering. "
                "Return an empty array if no matching records exist."
            )
        elif "LOW_FILL_RATE" in issues:
            strategy["extra_instructions"] = (
                "Previous output omitted schema fields. Search for synonymous "
                "labels and use null only when the source truly omits a value."
            )
        elif "GARBAGE_CONTENT" in issues:
            strategy["extra_instructions"] = (
                "Ignore navigation, promotions, newsletters, related content, "
                "and placeholders. Extract only records matching the schema."
            )
        elif "MANY_DUPLICATES" in issues:
            strategy["extra_instructions"] = (
                "Return each source record once, preferring its canonical URL."
            )

        if self._llm and cleaned_text_sample and diagnostics["fill_rate"] < 0.5:
            candidate = self._generate_prompt_candidate(
                schema,
                results,
                diagnostics,
                cleaned_text_sample,
            )
            if candidate:
                strategy["extra_instructions"] = candidate["text"]
                strategy["prompt_candidate"] = candidate
        return strategy

    def _generate_prompt_candidate(
        self,
        schema: dict[str, Any],
        results: list[dict],
        diagnostics: dict[str, Any],
        text_sample: str,
    ) -> dict[str, Any] | None:
        llm = self._llm
        if llm is None:
            return None
        prompt = f"""Analyze this extraction and propose concise retry instructions.

Schema:
{json.dumps(schema, indent=2)}

Sample output:
{json.dumps(results[:3], indent=2)}

Proxy diagnostics:
{json.dumps(diagnostics, indent=2)}

Page sample:
{text_sample[:3000]}

Return only the improved extraction instructions."""
        started = time.perf_counter()
        response = llm.ask(prompt)
        latency_ms = (time.perf_counter() - started) * 1000
        if not response or len(response) <= 20:
            return None
        usage = getattr(llm, "last_usage", {})
        return {
            "text": response,
            "latency_ms": latency_ms,
            "input_tokens": int(usage.get("input_tokens", 0)),
            "output_tokens": int(usage.get("output_tokens", 0)),
        }

    @staticmethod
    def propose_cleaning_rules(
        html: str,
        diagnostics: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Propose bounded class-removal candidates from repeated noise blocks."""

        if not {
            "GARBAGE_CONTENT",
            "LOW_VALIDITY",
        }.intersection(diagnostics.get("issues", [])):
            return []
        soup = BeautifulSoup(html, "lxml")
        counts: Counter[str] = Counter()
        for tag in soup.find_all(class_=True):
            class_names = tag.attrs.get("class")
            if not isinstance(class_names, list):
                continue
            for class_name in class_names:
                if _NOISE_CLASS_TOKENS.search(class_name):
                    counts[class_name] += 1
        return [
            {
                "rule_type": "class",
                "selector": class_name,
                "reason": "Repeated likely-noise blocks correlated with poor output",
                "evidence": f"class={class_name};count={count}",
                "confidence": min(0.8, 0.45 + count * 0.05),
            }
            for class_name, count in counts.most_common(3)
            if count >= 2
        ]

    def learn_optimal_wait(
        self,
        domain: str,
        quality: float,
        current_wait: float,
    ) -> float:
        profile = self.memory.get_domain_profile(domain)
        if not profile:
            return current_wait
        new_wait = current_wait
        if quality < QUALITY_POOR:
            new_wait = min(current_wait + 2.0, 15.0)
        elif quality >= QUALITY_EXCELLENT:
            new_wait = max(current_wait - 0.5, 1.0)
        if new_wait != current_wait:
            self.memory.set_domain_wait_seconds(domain, new_wait)
        return new_wait

    def diagnose_domain(self, domain: str) -> dict[str, Any]:
        history = self.memory.get_domain_history(domain, limit=50)
        report: dict[str, Any] = {
            "domain": domain,
            "total_attempts": len(history),
            "success_rate": 0.0,
            "avg_quality": 0.0,
            "common_issues": [],
            "recommendations": [],
            "trend": "unknown",
            "score_kind": "extraction_quality_proxy",
        }
        if not history:
            report["recommendations"].append(
                "No observations yet; run at least one scrape."
            )
            return report
        qualities = [item["quality_score"] for item in history]
        report["avg_quality"] = sum(qualities) / len(qualities)
        report["success_rate"] = self.memory.get_success_rate(domain)
        issue_counts: Counter[str] = Counter()
        for item in history:
            issue_counts.update(
                issue for issue in (item.get("error", "") or "").split(", ") if issue
            )
        report["common_issues"] = issue_counts.most_common()
        if len(qualities) >= 10:
            recent = sum(qualities[:5]) / 5
            older = sum(qualities[5:10]) / 5
            if recent > older + 0.1:
                report["trend"] = "improving"
            elif recent < older - 0.1:
                report["trend"] = "declining"
            else:
                report["trend"] = "stable"
        if report["success_rate"] < 0.5:
            report["recommendations"].append(
                "Inspect authentication, challenge, and rendering requirements."
            )
        if issue_counts["LOW_FILL_RATE"]:
            report["recommendations"].append(
                "Review the domain-specific schema field labels."
            )
        return report

    @staticmethod
    def _schema_name(schema: dict[str, Any]) -> str:
        return "_".join(sorted(schema)[:4])
