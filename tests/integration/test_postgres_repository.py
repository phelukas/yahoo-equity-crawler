import os
from datetime import datetime, timezone
from decimal import Decimal

import psycopg
import pytest

from yahoo_crawler.infrastructure.postgres.repository import PostgresEquityRepository


@pytest.mark.integration
def test_daily_load_is_idempotent() -> None:
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is required for PostgreSQL integration tests")

    repository = PostgresEquityRepository(database_url)
    observed_at = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
    initial_rows = [
        {
            "symbol": "PETR4.SA",
            "name": "Petrobras",
            "exchange": "SAO",
            "currency": "BRL",
            "price": "37.42",
            "market_cap": "487000000000",
        }
    ]
    repository.load_snapshot(
        initial_rows, region="Brazil", source="fixture", observed_at=observed_at
    )
    repository.load_snapshot(
        [{**initial_rows[0], "price": "38.10"}],
        region="Brazil",
        source="fixture",
        observed_at=observed_at,
    )

    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*), MAX(price)
                FROM equity_daily_prices
                WHERE region = 'Brazil'
                  AND symbol = 'PETR4.SA'
                  AND price_date = %s
                """,
                (observed_at.date(),),
            )
            count, price = cursor.fetchone()

    assert count == 1
    assert price == Decimal("38.100000")
