from __future__ import annotations

import pytest

from ai_scraper.browser import BrowserEngine
from ai_scraper.errors import UnsupportedChallengeError


class Driver:
    def __init__(self, user_agent: str):
        self.user_agent = user_agent
        self.page_source = "<html><body>Rendered content</body></html>"
        self.urls = []
        self.timeout = None
        self.cookies_cleared = 0
        self.scripts = []
        self.quit_calls = 0

    def set_page_load_timeout(self, timeout):
        self.timeout = timeout

    def get(self, url):
        self.urls.append(url)

    def delete_all_cookies(self):
        self.cookies_cleared += 1

    def execute_script(self, script):
        self.scripts.append(script)

    def quit(self):
        self.quit_calls += 1


def test_wait_state_clear_and_user_agent_rotation_are_real():
    drivers = []
    waits = []

    def factory(user_agent):
        driver = Driver(user_agent)
        drivers.append(driver)
        return driver

    browser = BrowserEngine(
        user_agents=("ua-one", "ua-two"),
        driver_factory=factory,
        sleep=waits.append,
    )
    assert browser.fetch("https://example.com", wait_seconds=4.5)
    assert waits == [4.5]
    assert browser.clear_state()
    assert drivers[0].cookies_cleared == 1
    assert browser.rotate_user_agent()
    assert drivers[0].quit_calls == 1

    browser.fetch("https://example.com/next")
    assert drivers[1].user_agent == "ua-two"


def test_challenge_detection_escalates_instead_of_bypassing():
    driver = Driver("ua")
    driver.page_source = "<div class='g-recaptcha'></div>"
    browser = BrowserEngine(
        driver_factory=lambda _: driver,
        sleep=lambda _: None,
    )
    with pytest.raises(UnsupportedChallengeError):
        browser.fetch("https://example.com")
