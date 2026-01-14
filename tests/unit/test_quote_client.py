from yahoo_crawler.infrastructure.yahoo.quote_client import YahooQuoteClient


def test_enrich_rows_merges_quote_fields(monkeypatch) -> None:
    client = YahooQuoteClient(region="Argentina", user_agent="UA", cookies=[])
    monkeypatch.setattr(client, "get_crumb", lambda: "crumb")
    monkeypatch.setattr(
        client,
        "fetch_quotes",
        lambda symbols, crumb: {"ABC": {"symbol": "ABC", "currency": "USD", "marketCap": 123}},
    )
    rows = [
        {"symbol": "ABC", "name": "ABC Co", "currency": "", "market_cap": ""},
        {"symbol": "MISSING", "name": "Missing"},
    ]
    enriched, stats = client.enrich_rows(rows)
    assert enriched[0]["currency"] == "USD"
    assert enriched[0]["market_cap"] == "123"
    assert stats["enriched_currency"] == 1
    assert stats["enriched_market_cap"] == 1
