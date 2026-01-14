from __future__ import annotations

import json
import logging
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import requests

logger = logging.getLogger(__name__)

REFERER_URL = "https://finance.yahoo.com/research-hub/screener/equity/?region={region}"
SCREENER_URL = "https://query1.finance.yahoo.com/v1/finance/screener"
CRUMB_URL = "https://query1.finance.yahoo.com/v1/test/getcrumb"

REGION_MAP = {
    "United States": "US",
    "Argentina": "AR",
    "Brazil": "BR",
    "Chile": "CL",
    "Mexico": "MX",
}


@dataclass(frozen=True)
class ScreenerStats:
    total_items: int
    unique_symbols: int
    duplicates: int
    pages: int
    total_expected: int | None
    elapsed_seconds: float


class YahooScreenerClient:
    def __init__(
        self,
        region: str,
        user_agent: str,
        cookies: list[dict],
        base_url: str,
        criteria: dict | None = None,
        timeout: int = 20,
        count: int = 25,
        max_pages: int = 2000,
        max_items: int = 100_000,
        max_attempts: int = 5,
    ) -> None:
        self._region = _normalize_region(region)
        self._timeout = timeout
        self._count = count
        self._max_pages = max_pages
        self._max_items = max_items
        self._max_attempts = max_attempts
        self._base_url, self._base_params = _split_url(base_url)
        if criteria is None:
            self._criteria = _default_criteria(self._region)
        else:
            self._criteria = _prepare_criteria(criteria, self._region)
        if "count" in self._base_params:
            try:
                self._count = int(self._base_params["count"])
            except (TypeError, ValueError):
                pass
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
        self._last_total: int | None = None
        self._crumb: str | None = None

    def fetch_page(self, start: int) -> list[dict]:
        if self._criteria:
            params = _filter_params(self._base_params)
            params["region"] = self._region
            if self._crumb:
                params["crumb"] = self._crumb
            criteria = _apply_paging(self._criteria, start, self._count)
            response = self._request_with_retry("POST", SCREENER_URL, params, criteria)
        else:
            params = dict(self._base_params)
            params["region"] = self._region
            if self._crumb:
                params["crumb"] = self._crumb
            params["start"] = str(start)
            params["count"] = str(self._count)
            response = self._request_with_retry("GET", self._base_url, params, None)
        if response is None:
            raise RuntimeError("Screener request failed without response.")
        if response.status_code != 200:
            self._save_http_artifact(response, response.url or self._base_url, params)
            raise RuntimeError(f"Screener request failed with status {response.status_code}.")

        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            self._save_json_artifact(response.text, self._base_url, params, str(exc))
            raise RuntimeError("Screener JSON decode failed.") from exc

        records = _extract_items(payload)
        self._last_total = _extract_total(payload)
        return records

    def fetch_all(self) -> tuple[list[dict], dict]:
        start = time.time()
        seen: dict[str, dict] = {}
        total_items = 0
        duplicates = 0
        pages = 0
        total_expected: int | None = None
        self._crumb = self._get_crumb()
        if not self._crumb:
            logger.warning("Screener crumb not available; request may fail")

        offset = 0
        while pages < self._max_pages and len(seen) < self._max_items:
            records = self.fetch_page(offset)
            items = len(records)
            total_items += items
            if total_expected is None:
                total_expected = self._last_total
            pages += 1
            if items == 0:
                logger.info("Screener page empty | page=%s | start=%s", pages - 1, offset)
                break

            new_items = 0
            page_dups = 0
            for item in records:
                row = _normalize_item(item)
                if not row:
                    continue
                symbol = row["symbol"]
                if symbol in seen:
                    duplicates += 1
                    page_dups += 1
                    continue
                seen[symbol] = row
                new_items += 1

            logger.info(
                "Screener page | page=%s | start=%s | count=%s | items=%s | new=%s | dup=%s | total_unique=%s",
                pages - 1,
                offset,
                self._count,
                items,
                new_items,
                page_dups,
                len(seen),
            )

            if items < self._count or new_items == 0:
                break
            if total_expected is not None and offset + self._count >= total_expected:
                break
            offset += self._count

        elapsed = time.time() - start
        stats = ScreenerStats(
            total_items=total_items,
            unique_symbols=len(seen),
            duplicates=duplicates,
            pages=pages,
            total_expected=total_expected,
            elapsed_seconds=elapsed,
        )
        return list(seen.values()), stats.__dict__

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
        self, method: str, url: str, params: dict[str, Any], json_body: dict | None
    ) -> requests.Response | None:
        for attempt in range(1, self._max_attempts + 1):
            try:
                response = self._session.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    timeout=self._timeout,
                )
            except requests.RequestException as exc:
                logger.warning("Screener HTTP failed | attempt=%s | error=%s", attempt, exc)
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
        out = artifacts / f"screener_http_{status}_{ts}.txt"
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
        out = artifacts / f"screener_http_000_{ts}.txt"
        payload = {"url": url, "params": params, "error": error}
        out.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")

    def _save_json_artifact(self, body: str, url: str, params: dict[str, Any], error: str) -> None:
        artifacts = Path("artifacts")
        artifacts.mkdir(exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        out = artifacts / f"screener_json_{ts}.txt"
        payload = {"url": url, "params": params, "error": error, "body_snippet": body[:1000]}
        out.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")

    def _get_crumb(self) -> str | None:
        params = {"lang": "en-US", "region": self._region}
        response = self._request_with_retry("GET", CRUMB_URL, params, None)
        if response is None:
            return None
        if response.status_code != 200:
            self._save_http_artifact(response, CRUMB_URL, params)
            return None
        crumb = response.text.strip()
        return crumb or None


def _extract_items(payload: dict) -> list[dict]:
    result = payload.get("finance", {}).get("result")
    if not isinstance(result, list) or not result:
        raise RuntimeError("Screener payload missing finance.result list.")
    root = result[0] if isinstance(result[0], dict) else None
    if not isinstance(root, dict):
        raise RuntimeError("Screener payload root is not a dict.")
    items = root.get("records") or root.get("quotes")
    if isinstance(items, dict):
        items = list(items.values())
    if not isinstance(items, list):
        raise RuntimeError("Screener payload missing records/quotes list.")
    return items


def _extract_total(payload: dict) -> int | None:
    result = payload.get("finance", {}).get("result")
    if not isinstance(result, list) or not result:
        return None
    root = result[0] if isinstance(result[0], dict) else None
    if not isinstance(root, dict):
        return None
    total = root.get("total")
    try:
        return int(total)
    except (TypeError, ValueError):
        return None


def _normalize_item(item: dict) -> dict | None:
    if not isinstance(item, dict):
        return None
    symbol = item.get("ticker") or item.get("symbol")
    if not symbol:
        return None
    name = _first_non_empty(
        item.get("companyName"),
        item.get("shortName"),
        item.get("longName"),
        item.get("name"),
    )
    exchange = _first_non_empty(item.get("exchange"), item.get("fullExchangeName"))
    price_value = item.get("regularMarketPrice")
    if price_value is None:
        price_value = item.get("regularMarketPreviousClose")
        if price_value is not None:
            logger.info("Price fallback to regularMarketPreviousClose | symbol=%s", symbol)
    if price_value is None:
        price_value = item.get("price") or item.get("lastPrice")
    price = _normalize_value(price_value)
    currency = _first_non_empty(item.get("currency"), item.get("financialCurrency"))
    market_cap = _normalize_value(item.get("marketCap"))
    return {
        "symbol": str(symbol),
        "name": name,
        "exchange": exchange,
        "market_cap": market_cap,
        "price": price,
        "currency": currency,
    }


def _normalize_value(value: Any) -> Any:
    if isinstance(value, dict):
        if "raw" in value:
            return value.get("raw")
        if "fmt" in value:
            return value.get("fmt")
    return value


def _first_non_empty(*values: Any) -> str | None:
    for value in values:
        if value:
            return str(value)
    return None


def _split_url(url: str) -> tuple[str, dict[str, str]]:
    if "&amp;" in url:
        url = url.replace("&amp;", "&")
    parsed = urlsplit(url)
    params = {key: value[0] for key, value in parse_qs(parsed.query).items()}
    base_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    return base_url, params


def _normalize_region(region: str) -> str:
    if len(region) == 2:
        return region.upper()
    return REGION_MAP.get(region, region.upper())


def _filter_params(params: dict[str, str]) -> dict[str, str]:
    allowed = {"formatted", "lang", "region", "corsDomain"}
    filtered = {"formatted": "true", "lang": "en-US"}
    for key, value in params.items():
        if key in allowed:
            filtered[key] = value
    return filtered


def _default_criteria(region: str) -> dict:
    return {
        "offset": 0,
        "size": 25,
        "sortType": "DESC",
        "sortField": "intradaymarketcap",
        "quoteType": "EQUITY",
        "query": {
            "operator": "and",
            "operands": [{"operator": "eq", "operands": ["region", region.lower()]}],
        },
    }


def _prepare_criteria(criteria: dict | None, region: str) -> dict | None:
    if not isinstance(criteria, dict):
        return None
    cloned = json.loads(json.dumps(criteria))
    _ensure_region_filter(cloned, region.lower())
    return cloned


def _apply_paging(criteria: dict, start: int, count: int) -> dict:
    cloned = json.loads(json.dumps(criteria))
    cloned["offset"] = start
    cloned["size"] = count
    return cloned


def _ensure_region_filter(criteria: dict, region: str) -> None:
    query = criteria.get("query")
    if not isinstance(query, dict):
        return
    operands = query.get("operands")
    if not isinstance(operands, list):
        return
    for operand in operands:
        if not isinstance(operand, dict):
            continue
        if operand.get("operator") != "eq":
            continue
        values = operand.get("operands")
        if isinstance(values, list) and len(values) >= 2 and values[0] == "region":
            values[1] = region
            return
    operands.append({"operator": "eq", "operands": ["region", region]})
