"""Browser boundary for rendered page retrieval and session recovery."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from ai_scraper.errors import (
    BrowserCrashedError,
    ChallengeEvidence,
    ChallengeType,
    NetworkFetchError,
    UnsupportedChallengeError,
)
from ai_scraper.redaction import redact_url

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENTS = (
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
)

_CHALLENGE_MARKERS = (
    ("awswaf-captcha", ChallengeType.AWS_WAF),
    ("challenge-platform", ChallengeType.CLOUDFLARE),
    ("cf-chl-", ChallengeType.CLOUDFLARE),
    ("g-recaptcha", ChallengeType.CAPTCHA),
    ("hcaptcha", ChallengeType.CAPTCHA),
)


class BrowserEngine:
    """Manage a lazy Chrome session without claiming challenge bypass."""

    def __init__(
        self,
        headless: bool = True,
        timeout: int = 30,
        *,
        user_agents: tuple[str, ...] = DEFAULT_USER_AGENTS,
        driver_factory: Callable[[str], Any] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if not user_agents:
            raise ValueError("At least one user agent is required")
        self.headless = headless
        self.timeout = timeout
        self._driver = None
        self._driver_factory = driver_factory
        self._sleep = sleep
        self._user_agents = user_agents
        self._user_agent_index = 0

    @property
    def user_agent(self) -> str:
        """The user agent that the next browser session will use."""

        return self._user_agents[self._user_agent_index]

    def _init_driver(self) -> None:
        """Initialize Chrome with the currently selected user agent."""

        if self._driver_factory is not None:
            self._driver = self._driver_factory(self.user_agent)
        else:
            import undetected_chromedriver as uc

            options = uc.ChromeOptions()
            if self.headless:
                options.add_argument("--headless=new")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-gpu")
            options.add_argument("--window-size=1920,1080")
            options.add_argument(f"--user-agent={self.user_agent}")
            self._driver = uc.Chrome(options=options)

        self._driver.set_page_load_timeout(self.timeout)
        logger.info("Chrome initialized (headless=%s)", self.headless)

    @property
    def driver(self) -> Any:
        if self._driver is None:
            self._init_driver()
        return self._driver

    @staticmethod
    def detect_challenge(source: str) -> ChallengeEvidence | None:
        """Classify known challenge markers without trying to circumvent them."""

        lowered = source.lower()
        for marker, challenge_type in _CHALLENGE_MARKERS:
            if marker in lowered:
                return ChallengeEvidence(challenge_type, marker)
        return None

    def fetch(self, url: str, wait_seconds: float = 2.0) -> str:
        """Navigate to a URL, wait for rendering, and return page source."""

        safe_url = redact_url(url)
        logger.info("Fetching: %s", safe_url)
        try:
            driver = self.driver
            driver.get(url)
            self._sleep(max(0.0, wait_seconds))
            source = driver.page_source
        except Exception as error:
            error_name = type(error).__name__.lower()
            if any(
                marker in error_name
                for marker in ("invalidsession", "nosuchwindow", "webdriver")
            ):
                raise BrowserCrashedError(
                    f"Browser session failed with {type(error).__name__}"
                ) from error
            raise NetworkFetchError(
                f"Page fetch failed with {type(error).__name__}"
            ) from error

        challenge = self.detect_challenge(source)
        if challenge is not None:
            logger.warning(
                "Unsupported %s challenge detected on %s",
                challenge.challenge_type.value,
                safe_url,
            )
            raise UnsupportedChallengeError(challenge)
        return source

    def clear_state(self) -> bool:
        """Clear cookies and browser storage for a real fresh-session retry."""

        if self._driver is None:
            return True
        self._driver.delete_all_cookies()
        try:
            self._driver.execute_script(
                "window.localStorage.clear(); window.sessionStorage.clear();"
            )
        except Exception:
            logger.debug("Browser storage clear was unavailable", exc_info=True)
        return True

    def rotate_user_agent(self) -> bool:
        """Select a different user agent and force the next fetch to use it."""

        if len(self._user_agents) < 2:
            return False
        previous = self._user_agent_index
        self._user_agent_index = (self._user_agent_index + 1) % len(self._user_agents)
        if self._user_agent_index == previous:
            return False
        self.restart()
        logger.info("Browser user agent rotated for the next request")
        return True

    def restart(self) -> bool:
        """Close the active driver so the next access creates a new session."""

        self.close()
        return self._driver is None

    def screenshot(self, path: str) -> None:
        """Save a screenshot when explicitly requested by the caller."""

        if self._driver:
            self._driver.save_screenshot(path)
            logger.info("Screenshot saved to %s", path)

    def close(self) -> None:
        """Gracefully close the browser."""

        if self._driver:
            try:
                self._driver.quit()
            except Exception:
                logger.debug("Browser quit failed", exc_info=True)
            self._driver = None
            logger.info("Browser closed")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def __del__(self):
        self.close()
