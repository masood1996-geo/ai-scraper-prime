from __future__ import annotations

from pathlib import Path

from ai_scraper import __version__

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

ROOT = Path(__file__).parents[1]


def test_readme_rejects_previous_overclaims():
    readme = (ROOT / "README.md").read_text(encoding="utf-8").casefold()
    forbidden = (
        "gets smarter with every scrape",
        "zero maintenance",
        "undetected chrome bypass",
        "powers global apartment hunting",
        "universal ai-powered web data extraction engine",
    )
    assert not [phrase for phrase in forbidden if phrase in readme]
    assert "semantic_correctness_guaranteed: false" in readme
    assert "command safety" in readme
    assert "standalone" in readme


def test_package_metadata_and_license_are_consistent():
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")

    assert metadata["version"] == __version__
    assert metadata["license"] == "MIT"
    assert license_text.startswith("MIT License")
    assert (
        metadata["urls"]["Repository"]
        == "https://github.com/masood1996-geo/ai-scraper-prime"
    )


def test_insecure_legacy_installers_are_not_published():
    assert not (ROOT / "install.sh").exists()
    assert not (ROOT / "install.ps1").exists()
