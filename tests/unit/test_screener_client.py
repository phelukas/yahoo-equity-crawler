import json
from pathlib import Path

from yahoo_crawler.infrastructure.yahoo.screener_client import YahooScreenerClient


class DummyResponse:
    def __init__(self, payload: dict) -> None:
        self.status_code = 200
        self._payload = payload
        self.headers: dict = {}
        self.url = "http://test"
        self.text = json.dumps(payload)

    def json(self) -> dict:
        return self._payload


def test_fetch_all_dedup_and_stop(monkeypatch) -> None:
    page_0 = json.loads(Path("tests/fixtures/screener_page_0.json").read_text(encoding="utf-8"))
    page_25 = json.loads(Path("tests/fixtures/screener_page_25.json").read_text(encoding="utf-8"))

    def fake_request(method: str, url: str, params: dict, json_body: dict | None) -> DummyResponse:
        if json_body:
            start = int(json_body.get("offset", 0))
        else:
            start = int(params.get("start", 0))
        if start == 0:
            return DummyResponse(page_0)
        if start == 2:
            return DummyResponse(page_25)
        empty = {"finance": {"result": [{"start": start, "count": 25, "total": 3, "records": []}]}}
        return DummyResponse(empty)

    client = YahooScreenerClient(
        region="Argentina",
        user_agent="UA",
        cookies=[],
        base_url="https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved?count=2&start=0&region=AR",
    )
    monkeypatch.setattr(client, "_request_with_retry", fake_request)

    rows, stats = client.fetch_all()
    symbols = {row["symbol"] for row in rows}
    assert symbols == {"AAA", "BBB", "CCC"}
    assert stats["duplicates"] == 1
    assert stats["pages"] == 2

    row_map = {row["symbol"]: row for row in rows}
    assert row_map["AAA"]["price"] == 10
    assert row_map["BBB"]["price"] == "20.50"
    assert row_map["BBB"]["currency"] == "EUR"
    assert row_map["BBB"]["market_cap"] == 200
