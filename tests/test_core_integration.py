from __future__ import annotations

import pytest
from conftest import FakeBrowser, FakeLLM

from ai_scraper.core import AIScraper
from ai_scraper.errors import (
    BrowserCrashedError,
    LLMParseError,
    LLMProviderError,
    ScrapeRecoveryError,
)
from ai_scraper.memory import Memory
from ai_scraper.recovery import RecoveryEngine


def records(count=5):
    return [
        {
            "title": f"Listing {index}",
            "url": f"https://example.com/{index}",
            "price": f"{1000 + index} EUR",
        }
        for index in range(count)
    ]


SCHEMA = {"title": "Title", "url": "URL", "price": "Price"}


def test_inline_hidden_content_is_removed_case_insensitively():
    scraper = AIScraper(
        learning=False,
        browser=FakeBrowser(),
        llm_client=FakeLLM(),
    )

    cleaned, applied_rules = scraper._clean_html_with_rules(
        "<main><p style='DISPLAY: none'>hidden</p><p>visible</p></main>"
    )

    assert "hidden" not in cleaned
    assert "visible" in cleaned
    assert applied_rules == []


def test_successful_scrape_with_prefetched_html(substantial_html):
    llm = FakeLLM(outputs=[records()])
    scraper = AIScraper(
        learning=False,
        browser=FakeBrowser(),
        llm_client=llm,
    )
    assert (
        scraper.scrape(
            "https://example.com/listings",
            SCHEMA,
            raw_html=substantial_html,
        )
        == records()
    )


def test_prompt_candidate_is_accepted_only_after_better_retry(
    tmp_path,
    substantial_html,
):
    memory = Memory(str(tmp_path / "memory.db"))
    baseline = [{"title": "x", "url": "", "price": ""}]
    llm = FakeLLM(
        outputs=[baseline, records()],
        answers=["Use each repeated listing card and require its canonical URL."],
    )
    scraper = AIScraper(
        browser=FakeBrowser(),
        llm_client=llm,
        memory=memory,
    )

    result = scraper.scrape(
        "https://example.com/listings",
        SCHEMA,
        raw_html=substantial_html,
    )

    assert result == records()
    assert (
        memory.get_best_prompt("example.com", "price_title_url")
        == "Use each repeated listing card and require its canonical URL."
    )


def test_prompt_regression_is_rejected(tmp_path, substantial_html):
    memory = Memory(str(tmp_path / "memory.db"))
    baseline = [{"title": "x", "url": "", "price": ""}]
    llm = FakeLLM(outputs=[baseline, []])
    scraper = AIScraper(
        browser=FakeBrowser(),
        llm_client=llm,
        memory=memory,
    )

    result = scraper.scrape(
        "https://example.com/listings",
        SCHEMA,
        raw_html=substantial_html,
    )

    assert result == baseline
    assert memory.get_best_prompt("example.com", "price_title_url") is None
    assert memory.get_stats()["total_refinements"] == 0


def test_fallback_model_is_used_by_the_real_retry(substantial_html):
    llm = FakeLLM(
        outputs=[LLMProviderError("down"), records()],
        model="primary",
    )
    recovery = RecoveryEngine(sleep=lambda _: None)
    scraper = AIScraper(
        learning=False,
        browser=FakeBrowser(),
        llm_client=llm,
        fallback_model="fallback",
        recovery_engine=recovery,
    )

    result = scraper.scrape(
        "https://example.com/listings",
        SCHEMA,
        raw_html=substantial_html,
    )

    assert result == records()
    assert [call["model"] for call in llm.extract_calls] == [
        "primary",
        "fallback",
    ]


def test_reduced_content_limit_is_consumed_by_retry(substantial_html):
    llm = FakeLLM(outputs=[LLMParseError("bad"), records()])
    scraper = AIScraper(
        learning=False,
        browser=FakeBrowser(),
        llm_client=llm,
        recovery_engine=RecoveryEngine(sleep=lambda _: None),
    )
    scraper.scrape(
        "https://example.com/listings",
        SCHEMA,
        raw_html=substantial_html,
    )
    assert [call["max_chars"] for call in llm.extract_calls] == [
        50_000,
        25_000,
    ]


def test_browser_restart_and_increased_wait_affect_retry(substantial_html):
    browser = FakeBrowser(outcomes=[BrowserCrashedError("crash"), substantial_html])
    scraper = AIScraper(
        learning=False,
        browser=browser,
        llm_client=FakeLLM(outputs=[records()]),
        recovery_engine=RecoveryEngine(sleep=lambda _: None),
    )
    assert scraper.scrape("https://example.com", SCHEMA) == records()
    assert browser.restart_calls == 1

    empty_then_good = FakeBrowser(
        outcomes=["<html><body>x</body></html>", substantial_html]
    )
    scraper = AIScraper(
        learning=False,
        browser=empty_then_good,
        llm_client=FakeLLM(outputs=[records()]),
        recovery_engine=RecoveryEngine(sleep=lambda _: None),
    )
    assert scraper.scrape("https://example.com", SCHEMA) == records()
    assert [call[1] for call in empty_then_good.fetch_calls] == [2.0, 7.0]
    assert empty_then_good.clear_calls == 1
    assert empty_then_good.restart_calls == 1


def test_unsupported_challenge_escalates_without_retry():
    scraper = AIScraper(
        learning=False,
        browser=FakeBrowser(),
        llm_client=FakeLLM(),
        recovery_engine=RecoveryEngine(sleep=lambda _: None),
    )
    with pytest.raises(ScrapeRecoveryError):
        scraper.scrape(
            "https://example.com",
            SCHEMA,
            raw_html="<div class='g-recaptcha'>challenge</div>",
        )
    assert scraper.recovery_stats()["verified_recoveries"] == 0


def test_cleaning_rule_learning_changes_a_later_scrape(tmp_path):
    html = (
        "<html><body>"
        "<div class='promo-card'>PROMO NOISE PLACEHOLDER ONE</div>"
        "<div class='promo-card'>PROMO NOISE PLACEHOLDER TWO</div>"
        "<main>" + "Real listing details and address. " * 4 + "</main>"
        "</body></html>"
    )
    poor = [{"title": "placeholder", "url": "", "price": ""}]
    llm = FakeLLM(outputs=[poor, poor, records()])
    memory = Memory(str(tmp_path / "memory.db"))
    scraper = AIScraper(
        browser=FakeBrowser(),
        llm_client=llm,
        memory=memory,
    )
    scraper._learner.should_retry = lambda quality, attempt: False

    scraper.scrape("https://example.com/one", SCHEMA, raw_html=html)
    assert memory.get_cleaning_rules("example.com") == []
    scraper.scrape("https://example.com/two", SCHEMA, raw_html=html)
    assert len(memory.get_cleaning_rules("example.com")) == 1
    scraper.scrape("https://example.com/three", SCHEMA, raw_html=html)

    assert "PROMO NOISE" not in llm.extract_calls[2]["text"]
    history = memory.get_domain_history("example.com")
    assert history[0]["quality_score"] > history[-1]["quality_score"]


def test_batch_keeps_good_domains_and_reports_one_failure(monkeypatch):
    scraper = AIScraper(
        learning=False,
        browser=FakeBrowser(),
        llm_client=FakeLLM(),
    )

    def fake_scrape(url, schema, instructions=""):
        if "bad" in url:
            raise RuntimeError("failed")
        return [{"title": "good"}]

    monkeypatch.setattr(scraper, "scrape", fake_scrape)
    result = scraper.scrape_multiple(
        ["https://good.example", "https://bad.example"],
        {"title": "Title"},
    )
    assert result == [
        {
            "title": "good",
            "_source_url": "https://good.example",
        }
    ]
    assert scraper.last_batch_failures == {"https://bad.example": "RuntimeError"}
