from __future__ import annotations

from ai_scraper.memory import Memory


def test_domain_profile_uses_ema_without_double_counting(tmp_path):
    memory = Memory(str(tmp_path / "memory.db"))
    memory.update_domain_profile("example.com", True, 1.0, wait_seconds=2.0)
    memory.update_domain_profile("example.com", False, 0.0)

    profile = memory.get_domain_profile("example.com")
    assert profile["total_scrapes"] == 2
    assert profile["total_successes"] == 1
    assert profile["avg_quality"] == 0.7

    memory.set_domain_wait_seconds("example.com", 4.0)
    profile = memory.get_domain_profile("example.com")
    assert profile["total_scrapes"] == 2
    assert profile["wait_seconds"] == 4.0


def test_prompt_candidates_are_scored_isolated_and_reversible(tmp_path):
    memory = Memory(str(tmp_path / "memory.db"))
    rejected = memory.save_prompt_candidate(
        "a.example",
        "title_url",
        "candidate regression",
        0.5,
        minimum_improvement=0.1,
    )
    assert not memory.evaluate_prompt_candidate(rejected, 0.55)
    assert memory.get_best_prompt("a.example", "title_url") is None

    accepted = memory.save_prompt_candidate(
        "a.example",
        "title_url",
        "verified refinement",
        0.5,
        minimum_improvement=0.1,
        latency_ms=12,
        input_tokens=20,
        output_tokens=5,
    )
    assert memory.evaluate_prompt_candidate(accepted, 0.7)
    assert memory.get_best_prompt("a.example", "title_url") == "verified refinement"
    assert memory.get_best_prompt("b.example", "title_url") is None
    assert memory.rollback_prompt(accepted)
    assert memory.get_best_prompt("a.example", "title_url") is None


def test_cleaning_rules_need_repeated_evidence_and_can_roll_back(tmp_path):
    memory = Memory(str(tmp_path / "memory.db"))
    first = memory.record_cleaning_rule_evidence(
        "example.com",
        "class",
        "promo-card",
        reason="Repeated likely-noise block",
        evidence="run-one",
        confidence=0.55,
    )
    assert first["status"] == "candidate"
    assert memory.get_cleaning_rules("example.com") == []

    second = memory.record_cleaning_rule_evidence(
        "example.com",
        "class",
        "promo-card",
        reason="Repeated likely-noise block",
        evidence="run-two",
        confidence=0.55,
    )
    assert second["status"] == "active"
    assert len(memory.get_cleaning_rules("example.com")) == 1

    assert memory.rollback_cleaning_rule(second["id"])
    assert memory.get_cleaning_rules("example.com") == []


def test_regressive_cleaning_rule_is_automatically_disabled(tmp_path):
    memory = Memory(str(tmp_path / "memory.db"))
    rule_id = memory.save_cleaning_rule(
        "example.com",
        "class",
        "content",
    )
    assert (
        memory.record_cleaning_rule_outcome(
            rule_id,
            quality=0.3,
            baseline_quality=0.8,
        )
        == "active"
    )
    assert (
        memory.record_cleaning_rule_outcome(
            rule_id,
            quality=0.2,
            baseline_quality=0.8,
        )
        == "disabled"
    )
