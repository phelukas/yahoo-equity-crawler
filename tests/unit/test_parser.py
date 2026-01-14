import json
from pathlib import Path

from yahoo_crawler.infrastructure.yahoo.parser import (
    extract_quotes,
    extract_screener_seed,
    normalize_equities,
)


def test_extract_quotes_from_fixture() -> None:
    state = json.loads(Path("tests/fixtures/quotes_state.json").read_text(encoding="utf-8"))
    quotes = extract_quotes(state)
    symbols = {quote["symbol"] for quote in quotes}
    assert symbols == {"ABC", "XYZ"}


def test_price_prefers_regular_market_price() -> None:
    state = json.loads(Path("tests/fixtures/quotes_state.json").read_text(encoding="utf-8"))
    quotes = extract_quotes(state)
    rows = normalize_equities(quotes)
    price_map = {row.symbol: row.price for row in rows}
    assert price_map["ABC"] == 10
    assert price_map["XYZ"] == 5


def test_extract_screener_seed_from_sveltekit_script() -> None:
    raw_criteria = {
        "offset": 0,
        "size": 25,
        "query": {"operator": "and", "operands": [{"operator": "eq", "operands": ["region", "us"]}]},
    }
    payload = {"finance": {"result": [{"rawCriteria": json.dumps(raw_criteria)}]}}
    body = json.dumps({"status": 200, "body": json.dumps(payload)})
    html = (
        '<script type="application/json" data-sveltekit-fetched '
        'data-url="https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved?count=25&amp;start=0&amp;region=AR">'
        f"{body}</script>"
    )
    url, criteria = extract_screener_seed(html)
    assert url is not None
    assert "predefined/saved" in url
    assert criteria is not None
    assert criteria.get("size") == 25
