from __future__ import annotations

from ai_scraper.learner import Learner
from ai_scraper.memory import Memory


def test_empty_output_has_zero_proxy_and_full_uncertainty(tmp_path):
    learner = Learner(Memory(str(tmp_path / "memory.db")))
    score, diagnostics = learner.score_results([], {"url": "URL"})
    assert score == 0
    assert diagnostics["score_kind"] == "extraction_quality_proxy"
    assert diagnostics["semantic_correctness_guaranteed"] is False
    assert diagnostics["uncertainty"] == 1


def test_duplicate_garbage_output_scores_below_high_quality(tmp_path):
    learner = Learner(Memory(str(tmp_path / "memory.db")))
    schema = {"title": "Title", "url": "URL", "price": "Price"}
    garbage = [
        {
            "title": "placeholder",
            "url": "not-a-url",
            "price": "unknown",
        },
        {
            "title": "placeholder",
            "url": "not-a-url",
            "price": "unknown",
        },
    ]
    good = [
        {
            "title": f"Apartment {index}",
            "url": f"https://example.com/{index}",
            "price": f"{1000 + index} EUR",
        }
        for index in range(5)
    ]
    garbage_score, garbage_diagnostics = learner.score_results(
        garbage,
        schema,
    )
    good_score, good_diagnostics = learner.score_results(good, schema)

    assert garbage_score < good_score
    assert "GARBAGE_CONTENT" in garbage_diagnostics["issues"]
    assert "SCHEMA_VALIDATION_FAILED" in garbage_diagnostics["issues"]
    assert good_diagnostics["components"]["deterministic_validation"] == 1


def test_schema_ranges_catch_structurally_valid_implausible_values(tmp_path):
    learner = Learner(Memory(str(tmp_path / "memory.db")))
    schema = {
        "rating": {"type": "number", "min": 0, "max": 5, "required": True},
        "url": {"type": "url", "required": True},
    }
    score, diagnostics = learner.score_results(
        [{"rating": 99, "url": "https://example.com/item"}],
        schema,
    )
    assert score < 0.9
    assert "rating:above_maximum" in diagnostics["validation_errors"]
    assert diagnostics["uncertainty"] > 0
