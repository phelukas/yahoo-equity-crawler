from decimal import Decimal

import pytest

from yahoo_crawler.infrastructure.postgres.repository import _normalize_row


def test_normalize_row_prepares_database_types() -> None:
    row = _normalize_row(
        {
            "symbol": " petr4.sa ",
            "name": "Petrobras",
            "exchange": "SAO",
            "currency": "BRL",
            "price": "37.42",
            "market_cap": 487_000_000_000,
        }
    )

    assert row["symbol"] == "PETR4.SA"
    assert row["price"] == Decimal("37.42")
    assert row["market_cap"] == Decimal("487000000000")


def test_normalize_row_rejects_invalid_numeric_data() -> None:
    with pytest.raises(ValueError, match="Invalid price for symbol INVALID"):
        _normalize_row({"symbol": "INVALID", "price": "not-a-number"})
