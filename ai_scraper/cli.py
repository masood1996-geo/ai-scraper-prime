"""Command-line interface for AI Scraper Prime."""

from __future__ import annotations

import logging
import os
from typing import Any

import click
from rich.console import Console
from rich.table import Table

from ai_scraper import __version__

console = Console()

_PROVIDER_ENV = {
    "openrouter": "OPENROUTER_API_KEY",
    "openai": "OPENAI_API_KEY",
    "kilo": "KILO_API_KEY",
}


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )


def _get_scraper(
    provider: str,
    api_key: str,
    model: str | None,
    fallback_model: str | None,
    headless: bool,
    learning: bool = True,
):
    from ai_scraper.core import AIScraper

    key_name = _PROVIDER_ENV.get(provider, "AI_SCRAPER_API_KEY")
    resolved_key = (
        api_key
        or os.environ.get(key_name, "")
        or os.environ.get("AI_SCRAPER_API_KEY", "")
    )
    if not resolved_key and provider != "ollama":
        raise click.ClickException(
            f"No API key configured. Set {key_name} or AI_SCRAPER_API_KEY."
        )
    return AIScraper(
        provider=provider,
        api_key=resolved_key,
        model=model,
        fallback_model=fallback_model,
        headless=headless,
        learning=learning,
    )


def _schema_from_options(
    schema_name: str,
    fields: str | None = None,
) -> dict[str, Any]:
    if fields:
        names = [name.strip() for name in fields.split(",") if name.strip()]
        if not names:
            raise click.ClickException("--fields must contain at least one name")
        return {name: f"The {name} value" for name in names}
    from ai_scraper.schemas import Schema

    try:
        return Schema.get(schema_name)
    except ValueError as error:
        raise click.ClickException(str(error)) from error


@click.group()
@click.version_option(__version__)
def main() -> None:
    """Extract schema-shaped data with measured, bounded adaptation."""


@main.command()
@click.argument("url")
@click.option("--schema", "-s", default="apartments", show_default=True)
@click.option("--fields", "-f", default=None, help="Comma-separated custom fields")
@click.option("--instructions", "-i", default="", help="Extra LLM instructions")
@click.option("--output", "-o", default=None, help="JSON or CSV output path")
@click.option("--provider", "-p", default="openrouter", show_default=True)
@click.option(
    "--api-key", "-k", default="", help="Prefer the provider environment variable"
)
@click.option("--model", "-m", default=None)
@click.option("--fallback-model", default=None)
@click.option("--no-headless", is_flag=True, help="Show the Chrome window")
@click.option("--no-learning", is_flag=True, help="Disable SQLite strategy memory")
@click.option("--verbose", "-v", is_flag=True)
def scrape(
    url: str,
    schema: str,
    fields: str | None,
    instructions: str,
    output: str | None,
    provider: str,
    api_key: str,
    model: str | None,
    fallback_model: str | None,
    no_headless: bool,
    no_learning: bool,
    verbose: bool,
) -> None:
    """Extract records from one URL."""

    _setup_logging(verbose)
    extraction_schema = _schema_from_options(schema, fields)
    with _get_scraper(
        provider,
        api_key,
        model,
        fallback_model,
        not no_headless,
        not no_learning,
    ) as scraper:
        try:
            results = scraper.scrape(url, extraction_schema, instructions)
        except Exception as error:
            raise click.ClickException(
                f"Scrape failed with {type(error).__name__}"
            ) from error

        _display_results(results, extraction_schema)
        if output:
            if output.lower().endswith(".csv"):
                scraper.save_csv(results, output)
            else:
                scraper.save_json(results, output)
            console.print(f"Saved {len(results)} records to {output}")


@main.command()
@click.argument("url")
@click.argument("question")
@click.option("--provider", "-p", default="openrouter", show_default=True)
@click.option("--api-key", "-k", default="")
@click.option("--model", "-m", default=None)
@click.option("--verbose", "-v", is_flag=True)
def ask(
    url: str,
    question: str,
    provider: str,
    api_key: str,
    model: str | None,
    verbose: bool,
) -> None:
    """Ask a question using one rendered page as context."""

    _setup_logging(verbose)
    with _get_scraper(provider, api_key, model, None, True, False) as scraper:
        try:
            console.print(scraper.ask_page(url, question))
        except Exception as error:
            raise click.ClickException(
                f"Question failed with {type(error).__name__}"
            ) from error


@main.command()
def schemas() -> None:
    """List built-in extraction schemas."""

    from ai_scraper.schemas import Schema

    for name, fields in Schema.list_all().items():
        table = Table(title=name)
        table.add_column("Field")
        table.add_column("Description")
        for field, description in fields.items():
            table.add_row(field, str(description))
        console.print(table)


@main.command()
@click.argument("urls", nargs=-1, required=True)
@click.option("--schema", "-s", default="apartments", show_default=True)
@click.option("--output", "-o", default="results.json", show_default=True)
@click.option("--provider", "-p", default="openrouter", show_default=True)
@click.option("--api-key", "-k", default="")
@click.option("--model", "-m", default=None)
@click.option("--fallback-model", default=None)
@click.option("--verbose", "-v", is_flag=True)
def batch(
    urls: tuple[str, ...],
    schema: str,
    output: str,
    provider: str,
    api_key: str,
    model: str | None,
    fallback_model: str | None,
    verbose: bool,
) -> None:
    """Extract records from multiple independent URLs."""

    _setup_logging(verbose)
    extraction_schema = _schema_from_options(schema)
    with _get_scraper(
        provider,
        api_key,
        model,
        fallback_model,
        True,
    ) as scraper:
        results = scraper.scrape_multiple(list(urls), extraction_schema)
        _display_results(results, extraction_schema)
        if output.lower().endswith(".csv"):
            scraper.save_csv(results, output)
        else:
            scraper.save_json(results, output)
        if scraper.last_batch_failures:
            console.print(
                f"{len(scraper.last_batch_failures)} URL(s) failed; "
                "inspect redacted logs for failure types."
            )


@main.command(name="brain")
def strategy_stats() -> None:
    """Show local strategy-memory statistics."""

    from ai_scraper.memory import Memory

    with Memory() as memory:
        stats = memory.get_stats()
    for key in (
        "total_scrapes",
        "unique_domains",
        "avg_quality",
        "total_refinements",
        "candidate_refinements",
        "active_cleaning_rules",
        "total_feedback",
    ):
        console.print(f"{key}: {stats.get(key, 0)}")


@main.command()
@click.argument("domain")
def diagnose(domain: str) -> None:
    """Show domain history based on the extraction-quality proxy."""

    from ai_scraper.learner import Learner
    from ai_scraper.memory import Memory

    with Memory() as memory:
        report = Learner(memory).diagnose_domain(domain)
    console.print_json(data=report)


def _display_results(
    results: list[dict[str, Any]],
    schema: dict[str, Any],
) -> None:
    if not results:
        console.print("No matching records returned.")
        return
    columns = list(schema)[:6]
    table = Table(title=f"{len(results)} record(s)")
    for column in columns:
        table.add_column(column.replace("_", " ").title(), max_width=40)
    for item in results[:25]:
        table.add_row(*[str(item.get(column, ""))[:40] for column in columns])
    console.print(table)


if __name__ == "__main__":
    main()
