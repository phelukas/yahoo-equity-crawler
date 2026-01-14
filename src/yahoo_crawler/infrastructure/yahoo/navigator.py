from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from urllib.parse import urlencode

from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from yahoo_crawler.infrastructure.browser.waits import wait

logger = logging.getLogger(__name__)

YAHOO_URL = "https://finance.yahoo.com/research-hub/screener/equity/"

REGION_MAP = {
    "United States": "US",
    "Argentina": "AR",
    "Brazil": "BR",
    "Chile": "CL",
    "Mexico": "MX",
}


def _save_artifacts(driver: WebDriver, tag: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = Path("artifacts")
    out.mkdir(exist_ok=True)

    (out / f"{tag}_{ts}.html").write_text(driver.page_source, encoding="utf-8")
    driver.save_screenshot(str(out / f"{tag}_{ts}.png"))


@dataclass(frozen=True)
class NavigationResult:
    page_source: str


class YahooNavigator:
    def __init__(self, driver: WebDriver, timeout: int = 25) -> None:
        self._driver = driver
        self._timeout = timeout

    def _assert_on_screener(self) -> None:
        url = self._driver.current_url
        if "research-hub/screener/equity" not in url:
            _save_artifacts(self._driver, "unexpected_url")
            raise RuntimeError(f"Unexpected URL (not screener): {url}")

    def open(self, region: str) -> None:
        """
        Opens Yahoo Equity Screener already filtered by region using query params.
        This is more stable than interacting with UI filters.
        """
        region_code = REGION_MAP.get(region)
        if not region_code:
            raise ValueError(
                f"Unsupported region: {region}. Supported: {', '.join(sorted(REGION_MAP.keys()))}"
            )

        params = {"region": region_code}
        url = f"{YAHOO_URL}?{urlencode(params)}"

        logger.info("Opening Yahoo screener page | region=%s | url=%s", region, url)
        self._driver.get(url)

        # Espera a página finalizar o carregamento
        wait(self._driver, self._timeout).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )

        self._handle_consent_if_present()

        # Guard rail: garante que continua no screener
        self._assert_on_screener()

        logger.info("Opened screener | url=%s", self._driver.current_url)

    def get_page_source(self) -> NavigationResult:
        return NavigationResult(page_source=self._driver.page_source)

    def wait_for_screener_seed(self) -> bool:
        try:
            wait(self._driver, self._timeout).until(
                lambda d: d.execute_script(
                    "return !!document.querySelector('script[data-sveltekit-fetched][data-url*=\"predefined/saved\"]')"
                )
            )
            return True
        except TimeoutException:
            return False
        except WebDriverException:
            logger.exception("Failed while waiting for screener seed")
            return False

    def get_screener_seed(self) -> tuple[str | None, str | None]:
        script = (
            "const node = document.querySelector('script[data-sveltekit-fetched][data-url*=\"predefined/saved\"]');"
            "if (!node) return null;"
            "return {url: node.getAttribute('data-url'), body: node.textContent};"
        )
        try:
            result = self._driver.execute_script(script)
        except WebDriverException:
            logger.exception("Failed to read screener seed from DOM")
            return None, None
        if isinstance(result, dict):
            return result.get("url"), result.get("body")
        return None, None

    def get_cookies(self) -> list[dict]:
        return self._driver.get_cookies()

    def get_user_agent(self) -> str:
        try:
            return str(self._driver.execute_script("return navigator.userAgent"))
        except WebDriverException:
            logger.exception("Failed to read navigator.userAgent")
            return ""

    def get_runtime_state(self) -> dict | None:
        """
        Attempts to fetch state from runtime JS variables when HTML lacks embedded JSON.
        """
        candidates = [
            ("__NEXT_DATA__", "return window.__NEXT_DATA__ || null;"),
            ("__PRELOADED_STATE__", "return window.__PRELOADED_STATE__ || null;"),
            ("root.App.main", "return (window.root && root.App && root.App.main) || null;"),
            ("App.main", "return (window.App && App.main) || null;"),
            ("YAHOO.context", "return (window.YAHOO && YAHOO.context) || null;"),
        ]
        for name, script in candidates:
            try:
                value = self._driver.execute_script(script)
            except WebDriverException:
                continue
            if isinstance(value, dict):
                logger.info("Runtime state found | source=%s", name)
                return value
        return None

    def _handle_consent_if_present(self) -> None:
        url = self._driver.current_url.lower()
        consent_hint = "consent" in url or "guce" in url
        if not consent_hint:
            try:
                frames = self._driver.find_elements(By.CSS_SELECTOR, "iframe[src*='consent'],iframe[src*='guce']")
            except WebDriverException:
                frames = []
            consent_hint = bool(frames)

        if not consent_hint:
            return

        logger.info("Consent flow detected | url=%s", self._driver.current_url)
        selectors = [
            "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'accept')]",
            "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'agree')]",
            "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'consent')]",
            "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'continue')]",
            "//button[contains(translate(@aria-label, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'accept')]",
            "//button[contains(translate(@aria-label, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'agree')]",
        ]
        for selector in selectors:
            try:
                elements = self._driver.find_elements(By.XPATH, selector)
            except WebDriverException:
                continue
            for element in elements:
                try:
                    if element.is_displayed() and element.is_enabled():
                        element.click()
                        wait(self._driver, self._timeout).until(
                            lambda d: d.execute_script("return document.readyState") == "complete"
                        )
                        logger.info("Consent accepted via selector | selector=%s", selector)
                        return
                except WebDriverException:
                    continue
