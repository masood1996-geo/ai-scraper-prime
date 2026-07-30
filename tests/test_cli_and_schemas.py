from __future__ import annotations

from click.testing import CliRunner

from ai_scraper.cli import main
from ai_scraper.schemas import Schema


def test_schema_retrieval_and_unknown_schema():
    assert Schema.get("apartments") is Schema.APARTMENTS
    assert "JOB_LISTINGS" in Schema.list_all()


def test_cli_help_and_schema_listing_smoke():
    runner = CliRunner()
    help_result = runner.invoke(main, ["--help"])
    assert help_result.exit_code == 0
    assert "schemas" in help_result.output

    schemas_result = runner.invoke(main, ["schemas"])
    assert schemas_result.exit_code == 0
    assert "APARTMENTS" in schemas_result.output


class FakeScraper:
    def __init__(self):
        self.last_batch_failures = {"https://bad.example": "RuntimeError"}
        self.saved = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def scrape(self, url, schema, instructions):
        return [{"name": "Example", "url": "/one"}]

    def scrape_multiple(self, urls, schema):
        return [{"title": "Example"}]

    def save_json(self, results, path):
        self.saved.append(("json", path, results))

    def save_csv(self, results, path):
        self.saved.append(("csv", path, results))


def test_cli_scrape_and_batch_paths(monkeypatch):
    runner = CliRunner()
    fake = FakeScraper()
    monkeypatch.setattr(
        "ai_scraper.cli._get_scraper",
        lambda *args, **kwargs: fake,
    )

    scrape_result = runner.invoke(
        main,
        [
            "scrape",
            "https://example.com",
            "--fields",
            "name,url",
            "--output",
            "records.json",
        ],
    )
    assert scrape_result.exit_code == 0
    assert "Example" in scrape_result.output
    assert fake.saved[0][0:2] == ("json", "records.json")

    batch_result = runner.invoke(
        main,
        [
            "batch",
            "https://good.example",
            "https://bad.example",
            "--output",
            "records.csv",
        ],
    )
    assert batch_result.exit_code == 0
    assert "1 URL(s) failed" in batch_result.output
    assert fake.saved[1][0:2] == ("csv", "records.csv")
