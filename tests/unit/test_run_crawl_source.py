import logging
from pathlib import Path

from yahoo_crawler.config import Settings
from yahoo_crawler.infrastructure.yahoo.navigator import NavigationResult
from yahoo_crawler.service import run_crawl as run_crawl_module


class DummyDriver:
    current_url = "https://finance.yahoo.com/research-hub/screener/equity/?region=AR"

    def quit(self) -> None:
        return None


class DummyNavigator:
    def __init__(self, driver: DummyDriver) -> None:
        self._driver = driver

    def open(self, region: str) -> None:
        self._driver.current_url = (
            "https://finance.yahoo.com/research-hub/screener/equity/?region=AR"
        )

    def get_page_source(self) -> NavigationResult:
        return NavigationResult(page_source="<html></html>")

    def wait_for_screener_seed(self) -> bool:
        return False

    def get_screener_seed(self) -> tuple[str | None, str | None]:
        return None, None

    def get_user_agent(self) -> str:
        return "UA"

    def get_cookies(self) -> list[dict]:
        return []

    def get_runtime_state(self) -> dict | None:
        return None


class DummyScreener:
    def __init__(self, *args, **kwargs) -> None:
        return None

    def fetch_all(self) -> tuple[list[dict], dict]:
        rows = [
            {
                "symbol": "AAA",
                "name": "AAA Corp",
                "exchange": "NYQ",
                "market_cap": "",
                "price": 1,
                "currency": "",
            }
        ]
        stats = {
            "pages": 1,
            "total_items": 1,
            "unique_symbols": 1,
            "duplicates": 0,
            "total_expected": 1,
            "elapsed_seconds": 0.01,
        }
        return rows, stats


def test_run_crawl_uses_screener_source(monkeypatch, tmp_path, caplog) -> None:
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(run_crawl_module, "create_chrome_driver", lambda cfg: DummyDriver())
    monkeypatch.setattr(run_crawl_module, "YahooNavigator", DummyNavigator)
    monkeypatch.setattr(
        run_crawl_module,
        "extract_screener_seed",
        lambda html: (
            "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved?count=25&start=0&region=AR",
            {"offset": 0, "size": 25, "query": {"operator": "and", "operands": []}},
        ),
    )
    monkeypatch.setattr(run_crawl_module, "YahooScreenerClient", DummyScreener)
    stats = {
        "total_symbols": 1,
        "batches": 1,
        "enriched_currency": 0,
        "enriched_market_cap": 0,
        "failures": 0,
        "elapsed_seconds": 0.0,
    }
    monkeypatch.setattr(
        run_crawl_module.YahooQuoteClient,
        "enrich_rows",
        lambda self, rows: (rows, stats),
    )

    settings = Settings(
        region="Argentina",
        output=str(Path(tmp_path) / "out.csv"),
        headless=True,
        log_level="INFO",
        strict=True,
    )
    run_crawl_module.run_crawl(settings)
    assert "fonte=screener_api" in caplog.text
