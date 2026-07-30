"""
title: AI Scraper — Universal Web Data Extraction
author: masood1996-geo
author_url: https://github.com/masood1996-geo/ai-scraper-prime
description: Standalone Open WebUI compatibility tool for AI-assisted schema extraction. It does not include the Prime recovery and measured-strategy pipeline.
required_open_webui_version: 0.4.0
requirements: openai>=1.0, beautifulsoup4>=4.12, lxml>=4.9, requests>=2.31, undetected-chromedriver>=3.5
version: 1.0.0
license: MIT
"""

import json
import logging
import os
import re
import time
import traceback
from typing import Dict, List
from urllib.parse import urljoin

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Inline core components — self-contained so no external package import
# is required beyond the pip requirements listed above.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


# ── Schema Definitions ────────────────────────────────────────────────

SCHEMAS = {
    "apartments": {
        "title": "Listing title / headline",
        "price": "Monthly rent price with currency",
        "rooms": "Number of rooms",
        "size": "Apartment size in m² or sqft",
        "address": "Full address or neighborhood",
        "url": "Direct link to the listing",
        "image_url": "Main image URL",
        "available_from": "Move-in date if mentioned",
    },
    "job_listings": {
        "title": "Job title",
        "company": "Company name",
        "location": "Job location",
        "salary": "Salary range if listed",
        "type": "Full-time, part-time, contract, remote",
        "url": "Link to job posting",
        "posted_date": "When the job was posted",
        "description_summary": "Brief 1-2 sentence summary of the role",
    },
    "products": {
        "name": "Product name",
        "price": "Current price with currency",
        "original_price": "Original price before discount (if any)",
        "rating": "Star rating (e.g., 4.5/5)",
        "reviews_count": "Number of reviews",
        "url": "Link to the product page",
        "image_url": "Product image URL",
        "in_stock": "Whether the item is in stock (true/false)",
    },
    "articles": {
        "headline": "Article headline",
        "author": "Author name",
        "published_date": "Publication date",
        "summary": "Brief 2-3 sentence summary",
        "url": "Link to the full article",
        "category": "Topic category (politics, tech, sports, etc.)",
    },
    "profiles": {
        "name": "Person's name",
        "title": "Professional title or role",
        "company": "Current company or affiliation",
        "location": "City or country",
        "bio": "Brief bio or description",
        "url": "Profile URL",
    },
    "events": {
        "name": "Event name",
        "date": "Event date and time",
        "location": "Venue or address",
        "price": "Ticket price or 'Free'",
        "url": "Event page URL",
        "description": "Brief event description",
    },
    "restaurants": {
        "name": "Restaurant name",
        "cuisine": "Type of cuisine",
        "rating": "Rating (e.g., 4.5/5)",
        "price_range": "Price level (€, €€, €€€)",
        "address": "Restaurant address",
        "phone": "Phone number",
        "url": "Restaurant page URL",
    },
    "contacts": {
        "name": "Person or business name",
        "phone": "Phone number",
        "email": "Email address",
        "address": "Physical address",
        "website": "Website URL",
    },
    "links": {
        "text": "Link text",
        "url": "Link URL",
        "context": "Surrounding text or description",
    },
    "real_estate_agents": {
        "name": "Agent or agency name",
        "phone": "Phone number",
        "email": "Email address",
        "website": "Website URL",
        "address": "Office address",
        "working_hours": "Office hours or availability",
        "specialty": "Area of expertise (e.g., rental, commercial, luxury)",
    },
}


# ── LLM Client (OpenAI-compatible) ───────────────────────────────────

PROVIDERS = {
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "default_model": "google/gemini-2.5-flash",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
    },
    "kilo": {
        "base_url": "https://api.kilo.ai/api/gateway",
        "default_model": "claude-sonnet-4-5",
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "default_model": "llama3.1",
    },
}


class _LLMClient:
    """Lightweight LLM client for structured extraction."""

    def __init__(self, provider: str, api_key: str, model: str = ""):
        provider = provider.lower()
        cfg = PROVIDERS.get(provider, {})
        self.base_url = cfg.get("base_url", "https://openrouter.ai/api/v1")
        self.model = model or cfg.get("default_model", "gpt-4o-mini")

        import openai

        self._client = openai.OpenAI(base_url=self.base_url, api_key=api_key)

    def extract(self, text: str, schema: Dict, instructions: str = "") -> List[Dict]:
        schema_desc = json.dumps(schema, indent=2)
        system_prompt = (
            "You are a precise data extraction engine. "
            "Extract structured data from the provided content. "
            "Output ONLY a valid JSON array of objects matching the schema below. "
            "No markdown formatting, no explanation, no commentary — just the raw JSON array.\n\n"
            f"Schema (extract these fields for each item found):\n{schema_desc}"
        )
        if instructions:
            system_prompt += f"\n\nAdditional instructions:\n{instructions}"

        max_chars = 50_000
        if len(text) > max_chars:
            text = text[:max_chars]

        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text},
                ],
                temperature=0.0,
                max_tokens=4096,
            )
            raw = response.choices[0].message.content.strip()
            for prefix in ["```json", "```"]:
                if raw.startswith(prefix):
                    raw = raw[len(prefix) :]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()
            result = json.loads(raw)
            if isinstance(result, dict):
                result = [result]
            return result if isinstance(result, list) else []
        except Exception as e:
            logger.error("LLM extraction failed: %s", e)
            return []

    def ask(self, question: str) -> str:
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": question}],
                temperature=0.0,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            return f"Error: {e}"


# ── Browser Engine ────────────────────────────────────────────────────


class _BrowserEngine:
    """Headless Chrome renderer for the standalone Open WebUI tool."""

    def __init__(self, headless: bool = True, timeout: int = 30):
        self.headless = headless
        self.timeout = timeout
        self._driver = None

    def _init_driver(self):
        import undetected_chromedriver as uc

        options = uc.ChromeOptions()
        if self.headless:
            options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument(
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        )
        self._driver = uc.Chrome(options=options)
        self._driver.set_page_load_timeout(self.timeout)

    @property
    def driver(self):
        if self._driver is None:
            self._init_driver()
        return self._driver

    def fetch(self, url: str, wait_seconds: float = 2.0) -> str:
        self.driver.get(url)
        time.sleep(wait_seconds)
        source = self.driver.page_source
        if "challenge-platform" in source:
            time.sleep(5)
            source = self.driver.page_source
        return source

    def close(self):
        if self._driver:
            try:
                self._driver.quit()
            except Exception:
                pass
            self._driver = None


# ── HTML Cleaner ──────────────────────────────────────────────────────


def _clean_html(html: str) -> str:
    """Strip scripts, styles, nav, footer, ads from HTML."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")

    for tag_name in [
        "script",
        "style",
        "noscript",
        "svg",
        "iframe",
        "nav",
        "footer",
        "header",
        "aside",
    ]:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    for tag in soup.find_all(attrs={"style": re.compile(r"display\s*:\s*none")}):
        tag.decompose()

    for pattern in [
        r"cookie",
        r"consent",
        r"modal",
        r"popup",
        r"overlay",
        r"banner",
        r"gdpr",
    ]:
        for tag in soup.find_all(class_=re.compile(pattern, re.I)):
            tag.decompose()

    text = soup.get_text(separator="\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Open WebUI Tool Class
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class Tools:
    """
    AI Scraper — universal web data extraction tool for Open WebUI.

    Point at any website and extract structured data using AI.
    Supports predefined schemas (jobs, apartments, products, etc.)
    and custom field extraction.
    """

    class Valves(BaseModel):
        llm_provider: str = Field(
            default="openrouter",
            description="LLM provider: 'openrouter', 'openai', 'kilo', or 'ollama'",
        )
        api_key: str = Field(
            default="",
            description="API key for the LLM provider (or set via env vars: OPENROUTER_API_KEY, OPENAI_API_KEY, etc.)",
        )
        model: str = Field(
            default="",
            description="Specific model to use (leave empty for provider default). Examples: 'google/gemini-2.5-flash', 'gpt-4o-mini'",
        )
        page_load_timeout: int = Field(
            default=30,
            description="Page load timeout in seconds",
        )
        wait_after_load: float = Field(
            default=2.0,
            description="Seconds to wait after page load for JS rendering",
        )

    def __init__(self):
        self.valves = self.Valves()

    def _resolve_api_key(self) -> str:
        """Resolve API key from valves or environment variables."""
        if self.valves.api_key:
            return self.valves.api_key
        env_map = {
            "openrouter": "OPENROUTER_API_KEY",
            "openai": "OPENAI_API_KEY",
            "kilo": "KILO_API_KEY",
        }
        provider = self.valves.llm_provider.lower()
        key = os.environ.get(env_map.get(provider, ""), "")
        if not key:
            key = os.environ.get("AI_SCRAPER_API_KEY", "")
        return key

    def _get_llm(self) -> _LLMClient:
        """Create an LLM client from current valve settings."""
        api_key = self._resolve_api_key()
        if not api_key and self.valves.llm_provider.lower() != "ollama":
            raise ValueError(
                "No API key configured. Set it in Tool Settings (Valves) "
                "or via environment variable (OPENROUTER_API_KEY, OPENAI_API_KEY, etc.)."
            )
        return _LLMClient(
            provider=self.valves.llm_provider,
            api_key=api_key,
            model=self.valves.model,
        )

    def _get_browser(self) -> _BrowserEngine:
        """Create a headless browser engine."""
        return _BrowserEngine(
            headless=True,
            timeout=self.valves.page_load_timeout,
        )

    def _format_results(self, results: List[Dict], schema: Dict, url: str) -> str:
        """Format extraction results as a readable string for the LLM to present."""
        if not results:
            return "⚠️ **No results found.** The page may require authentication, have anti-bot protection, or use a different content structure."

        lines = []
        lines.append(f"## 🔍 Extracted {len(results)} item(s) from `{url}`\n")

        # Summary table header
        fields = list(schema.keys())

        for i, item in enumerate(results[:30], 1):  # Cap at 30 items
            lines.append(f"### Item {i}")
            for field in fields:
                val = item.get(field, "—")
                if val is None or str(val).strip() == "":
                    val = "—"
                display_name = field.replace("_", " ").title()
                lines.append(f"- **{display_name}:** {val}")
            lines.append("")

        if len(results) > 30:
            lines.append(
                f"*...and {len(results) - 30} more items (showing first 30)*\n"
            )

        # Raw JSON block
        lines.append("<details>")
        lines.append("<summary>📋 Raw JSON Data (click to expand)</summary>\n")
        lines.append("```json")
        lines.append(json.dumps(results, indent=2, ensure_ascii=False))
        lines.append("```")
        lines.append("</details>")

        return "\n".join(lines)

    # ─── Tool Methods ─────────────────────────────────────────────────

    async def scrape_url(
        self,
        url: str,
        schema_name: str = "job_listings",
        instructions: str = "",
    ) -> str:
        """
        Scrape a website and extract structured data using AI.
        Fetches the page with a headless browser, cleans the HTML, and uses an LLM to extract data matching the chosen schema.

        :param url: The full URL of the webpage to scrape (e.g., 'https://example.com/jobs').
        :param schema_name: Predefined schema to use. Options: apartments, job_listings, products, articles, profiles, events, restaurants, contacts, links, real_estate_agents. Default: job_listings.
        :param instructions: Optional extra instructions for the AI extractor (e.g., 'Only extract remote positions' or 'Ignore sponsored listings').
        :return: Extracted structured data formatted as a readable summary with raw JSON.
        """
        try:
            # Validate schema
            schema_key = schema_name.lower().replace("-", "_").replace(" ", "_")
            schema = SCHEMAS.get(schema_key)
            if not schema:
                available = ", ".join(sorted(SCHEMAS.keys()))
                return f"❌ **Unknown schema:** `{schema_name}`\n\n**Available schemas:** {available}"

            llm = self._get_llm()
            browser = self._get_browser()

            try:
                # Fetch page
                html = browser.fetch(url, wait_seconds=self.valves.wait_after_load)
                cleaned = _clean_html(html)

                if len(cleaned) < 50:
                    return f"⚠️ **Very little content found** on `{url}`. The page may be blocking scrapers, require login, or load content dynamically via JavaScript."

                # Extract data
                results = llm.extract(
                    text=cleaned,
                    schema=schema,
                    instructions=instructions,
                )

                # Resolve relative URLs
                for item in results:
                    for key in ("url", "image_url", "link", "website"):
                        if (
                            key in item
                            and item[key]
                            and not str(item[key]).startswith("http")
                        ):
                            item[key] = urljoin(url, item[key])

                return self._format_results(results, schema, url)

            finally:
                browser.close()

        except Exception as e:
            logger.error("Scrape failed: %s", traceback.format_exc())
            return f"❌ **Scraping failed:** {str(e)}"

    async def scrape_with_custom_fields(
        self,
        url: str,
        fields: str,
        instructions: str = "",
    ) -> str:
        """
        Scrape a website with custom field names you define. Use this when none of the predefined schemas match your needs.

        :param url: The full URL of the webpage to scrape.
        :param fields: Comma-separated list of field names to extract (e.g., 'name, price, rating, location').
        :param instructions: Optional extra instructions for the AI extractor.
        :return: Extracted data matching your custom fields.
        """
        try:
            # Build schema from field list
            field_list = [f.strip() for f in fields.split(",") if f.strip()]
            if not field_list:
                return "❌ **No fields specified.** Provide a comma-separated list like: `name, price, rating`"

            schema = {f: f"The {f} value" for f in field_list}

            llm = self._get_llm()
            browser = self._get_browser()

            try:
                html = browser.fetch(url, wait_seconds=self.valves.wait_after_load)
                cleaned = _clean_html(html)

                if len(cleaned) < 50:
                    return f"⚠️ **Very little content found** on `{url}`."

                results = llm.extract(
                    text=cleaned,
                    schema=schema,
                    instructions=instructions,
                )

                for item in results:
                    for key in ("url", "image_url", "link", "website"):
                        if (
                            key in item
                            and item[key]
                            and not str(item[key]).startswith("http")
                        ):
                            item[key] = urljoin(url, item[key])

                return self._format_results(results, schema, url)

            finally:
                browser.close()

        except Exception as e:
            logger.error("Custom scrape failed: %s", traceback.format_exc())
            return f"❌ **Scraping failed:** {str(e)}"

    async def ask_page(
        self,
        url: str,
        question: str,
    ) -> str:
        """
        Fetch a webpage and ask an AI-powered question about its content. Great for quick analysis without defining a schema.

        :param url: The URL of the page to analyze.
        :param question: Your question about the page content (e.g., 'What products are listed?' or 'What is the main topic?').
        :return: AI-generated answer based on the page content.
        """
        try:
            llm = self._get_llm()
            browser = self._get_browser()

            try:
                html = browser.fetch(url, wait_seconds=self.valves.wait_after_load)
                cleaned = _clean_html(html)

                if len(cleaned) < 50:
                    return f"⚠️ **Very little content found** on `{url}`."

                full_question = (
                    f"Based on the following web page content, answer this question:\n\n"
                    f"Question: {question}\n\n"
                    f"Page content:\n{cleaned[:30000]}"
                )
                answer = llm.ask(full_question)

                return (
                    f"## 💡 Answer\n\n"
                    f"**Page:** `{url}`\n"
                    f"**Question:** {question}\n\n"
                    f"---\n\n"
                    f"{answer}"
                )

            finally:
                browser.close()

        except Exception as e:
            logger.error("Ask page failed: %s", traceback.format_exc())
            return f"❌ **Failed to analyze page:** {str(e)}"

    async def list_schemas(self) -> str:
        """
        List all available predefined extraction schemas and their fields. Use this to discover what schema_name to pass to the scrape_url tool.

        :return: A formatted list of all available schemas with their field descriptions.
        """
        lines = []
        lines.append("## 📋 Available Extraction Schemas\n")
        lines.append("Use any of these schema names with the `scrape_url` tool.\n")

        for name, fields in sorted(SCHEMAS.items()):
            lines.append(f"### 📦 `{name}`")
            for field, desc in fields.items():
                lines.append(f"- **{field}** — {desc}")
            lines.append("")

        lines.append("---")
        lines.append(
            "*💡 Need different fields? Use `scrape_with_custom_fields` "
            "to define your own extraction schema.*"
        )

        return "\n".join(lines)

    async def show_brain_stats(self) -> str:
        """
        Show the AI Scraper's learning brain statistics — how many pages it has scraped, quality scores, and what it has learned. Requires the ai-scraper package to be installed with its learning database.

        :return: Formatted learning statistics and domain knowledge.
        """
        try:
            # Try to import the full ai_scraper package's Memory
            try:
                from ai_scraper.memory import Memory

                mem = Memory()
                stats = mem.get_stats()
                mem.close()
            except ImportError:
                # Fallback: try reading the SQLite database directly
                import sqlite3

                db_path = os.path.join(
                    os.path.expanduser("~"), ".ai_scraper", "memory.db"
                )
                if not os.path.exists(db_path):
                    return (
                        "## 🧠 Learning Brain\n\n"
                        "No learning data found yet. The brain starts learning "
                        "after your first scrape!\n\n"
                        f"*Database location:* `{db_path}`"
                    )

                conn = sqlite3.connect(db_path)
                conn.row_factory = sqlite3.Row

                stats = {}
                stats["total_scrapes"] = conn.execute(
                    "SELECT COUNT(*) FROM extraction_history"
                ).fetchone()[0]
                stats["unique_domains"] = conn.execute(
                    "SELECT COUNT(DISTINCT domain) FROM extraction_history"
                ).fetchone()[0]
                stats["avg_quality"] = (
                    conn.execute(
                        "SELECT AVG(quality_score) FROM extraction_history"
                    ).fetchone()[0]
                    or 0.0
                )
                stats["total_refinements"] = conn.execute(
                    "SELECT COUNT(*) FROM prompt_refinements"
                ).fetchone()[0]
                stats["total_feedback"] = conn.execute(
                    "SELECT COUNT(*) FROM feedback"
                ).fetchone()[0]

                top = conn.execute(
                    """SELECT domain, total_scrapes, avg_quality,
                              total_successes, total_failures
                       FROM domain_profiles
                       ORDER BY total_scrapes DESC LIMIT 10"""
                ).fetchall()
                stats["top_domains"] = [dict(r) for r in top]
                conn.close()

            # Format output
            lines = []
            lines.append("## 🧠 AI Scraper — Learning Brain\n")
            lines.append(f"- **Total Scrapes:** {stats.get('total_scrapes', 0)}")
            lines.append(f"- **Unique Domains:** {stats.get('unique_domains', 0)}")
            lines.append(f"- **Average Quality:** {stats.get('avg_quality', 0):.0%}")
            lines.append(
                f"- **Prompt Refinements:** {stats.get('total_refinements', 0)}"
            )
            lines.append(
                f"- **User Feedback Entries:** {stats.get('total_feedback', 0)}"
            )
            lines.append("")

            top_domains = stats.get("top_domains", [])
            if top_domains:
                lines.append("### 🌐 Known Domains\n")
                lines.append(
                    "| Domain | Scrapes | Successes | Failures | Avg Quality |"
                )
                lines.append(
                    "|--------|---------|-----------|----------|-------------|"
                )
                for d in top_domains:
                    q = d.get("avg_quality", 0)
                    indicator = "🟢" if q > 0.6 else "🟡" if q > 0.35 else "🔴"
                    lines.append(
                        f"| {d['domain']} | {d['total_scrapes']} | "
                        f"{d['total_successes']} | {d['total_failures']} | "
                        f"{indicator} {q:.0%} |"
                    )
                lines.append("")
            else:
                lines.append(
                    "*No domain data yet — the brain starts learning after your first scrape!*"
                )

            return "\n".join(lines)

        except Exception as e:
            logger.error("Brain stats failed: %s", traceback.format_exc())
            return f"❌ **Failed to load brain stats:** {str(e)}"
