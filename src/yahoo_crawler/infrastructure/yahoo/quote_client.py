from __future__ import annotations

import json
import logging
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

QUOTE_URL = "https://query1.finance.yahoo.com/v7/finance/quote"
CRUMB_URL = "https://query1.finance.yahoo.com/v1/test/getcrumb"
REFERER_URL = "https://finance.yahoo.com/research-hub/screener/equity/?region={region}"

REGION_MAP = {
    "United States": "US",
    "Argentina": "AR",
    "Brazil": "BR",
    "Chile": "CL",
    "Mexico": "MX",
}


@dataclass(frozen=True)
class EnrichmentStats:
    total_symbols: int
    batches: int
    enriched_currency: int
    enriched_market_cap: int
    failures: int
    elapsed_seconds: float


class YahooQuoteClient:
    def __init__(
        self,
        region: str,
        user_agent: str,
        cookies: list[dict],
        timeout: int = 20,
        batch_size: int = 50,
        max_attempts: int = 5,
    ) -> None:
        self._region = _normalize_region(region)
        self._timeout = timeout
        self._batch_size = batch_size
        self._max_attempts = max_attempts
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": user_agent or "Mozilla/5.0",
                "Accept": "application/json,text/plain,*/*",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": REFERER_URL.format(region=self._region),
            }
        )
        self._set_cookies(cookies)

    def get_crumb(self) -> str | None:
        params = {"lang": "en-US", "region": self._region}
        response = self._request_with_retry(CRUMB_URL, params)
        if response is None:
            return None
        if response.status_code != 200:
            self._save_http_artifact(response, CRUMB_URL, params)
            return None
        crumb = response.text.strip()
        return crumb or None

    def fetch_quotes(self, symbols: list[str], crumb: str | None) -> dict[str, dict]:
        params = {"symbols": ",".join(symbols)}
        if crumb:
            params["crumb"] = crumb
        response = self._request_with_retry(QUOTE_URL, params)
        if response is None:
            return {}
        if response.status_code != 200:
            self._save_http_artifact(response, QUOTE_URL, params)
            return {}
        try:
            payload = response.json()
        except json.JSONDecodeError:
            self._save_http_artifact(response, QUOTE_URL, params)
            return {}
        results = payload.get("quoteResponse", {}).get("result", [])
        quotes: dict[str, dict] = {}
        for item in results:
            symbol = item.get("symbol")
            if symbol:
                quotes[symbol] = item
        return quotes

    def enrich_rows(self, rows: list[dict]) -> tuple[list[dict], dict]:
        start = time.time()
        symbols = [row.get("symbol") for row in rows if row.get("symbol")]
        total = len(symbols)
        if not symbols:
            stats = EnrichmentStats(0, 0, 0, 0, 0, 0.0)
            return rows, stats.__dict__

        crumb = self.get_crumb()
        batches = [symbols[i : i + self._batch_size] for i in range(0, total, self._batch_size)]
        quote_map: dict[str, dict] = {}
        failures = 0
        for batch in batches:
            quotes = self.fetch_quotes(batch, crumb)
            if not quotes:
                failures += 1
            quote_map.update(quotes)

        enriched_currency = 0
        enriched_market_cap = 0
        for row in rows:
            symbol = row.get("symbol")
            quote = quote_map.get(symbol)
            if not quote:
                continue
            currency = quote.get("currency") or quote.get("financialCurrency")
            if currency and not row.get("currency"):
                row["currency"] = currency
                enriched_currency += 1
            market_cap = _normalize_market_cap(quote.get("marketCap"))
            if market_cap and not row.get("market_cap"):
                row["market_cap"] = market_cap
                enriched_market_cap += 1

        elapsed = time.time() - start
        stats = EnrichmentStats(
            total_symbols=total,
            batches=len(batches),
            enriched_currency=enriched_currency,
            enriched_market_cap=enriched_market_cap,
            failures=failures,
            elapsed_seconds=elapsed,
        )
        return rows, stats.__dict__

    def _set_cookies(self, cookies: list[dict]) -> None:
        for cookie in cookies:
            name = cookie.get("name")
            value = cookie.get("value")
            domain = cookie.get("domain")
            path = cookie.get("path", "/")
            if not name or value is None:
                continue
            self._session.cookies.set(name, value, domain=domain, path=path)

    def _request_with_retry(
        self, url: str, params: dict[str, Any]
    ) -> requests.Response | None:
        for attempt in range(1, self._max_attempts + 1):
            try:
                response = self._session.get(url, params=params, timeout=self._timeout)
            except requests.RequestException as exc:
                logger.warning("Requisição HTTP falhou | tentativa=%s | erro=%s", attempt, exc)
                if attempt == self._max_attempts:
                    self._save_error_artifact(url, params, str(exc))
                    return None
                self._sleep_backoff(attempt, None)
                continue

            if response.status_code in (429, 503):
                retry_after = response.headers.get("Retry-After")
                if attempt == self._max_attempts:
                    self._save_http_artifact(response, url, params)
                    return response
                self._sleep_backoff(attempt, retry_after)
                continue

            return response
        return None

    def _sleep_backoff(self, attempt: int, retry_after: str | None) -> None:
        if retry_after and retry_after.isdigit():
            delay = int(retry_after)
        else:
            base = 2 ** (attempt - 1)
            delay = base + random.uniform(0, 0.5)
        time.sleep(delay)

    def _save_http_artifact(self, response: requests.Response, url: str, params: dict[str, Any]) -> None:
        artifacts = Path("artifacts")
        artifacts.mkdir(exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        status = response.status_code
        out = artifacts / f"quote_http_{status}_{ts}.txt"
        snippet = response.text[:1000] if response.text else ""
        payload = {
            "url": response.url or url,
            "params": params,
            "status": status,
            "headers": dict(response.headers),
            "body_snippet": snippet,
        }
        out.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")

    def _save_error_artifact(self, url: str, params: dict[str, Any], error: str) -> None:
        artifacts = Path("artifacts")
        artifacts.mkdir(exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        out = artifacts / f"quote_http_000_{ts}.txt"
        payload = {"url": url, "params": params, "error": error}
        out.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


def _normalize_region(region: str) -> str:
    if len(region) == 2:
        return region.upper()
    return REGION_MAP.get(region, region.upper())


def _normalize_market_cap(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict):
        value = value.get("raw") or value.get("fmt")
    try:
        return str(int(value))
    except (TypeError, ValueError):
        return str(value)
