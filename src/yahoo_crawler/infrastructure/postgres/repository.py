from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from importlib.resources import files
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg import Cursor


@dataclass(frozen=True, slots=True)
class LoadResult:
    run_id: UUID
    records_received: int
    records_loaded: int
    observed_at: datetime


class PostgresEquityRepository:
    """Loads the curated crawler output into an idempotent daily warehouse."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def load_snapshot(
        self,
        rows: list[dict[str, Any]],
        *,
        region: str,
        source: str,
        observed_at: datetime | None = None,
    ) -> LoadResult:
        snapshot_at = observed_at or datetime.now(timezone.utc)
        if snapshot_at.tzinfo is None or snapshot_at.utcoffset() is None:
            raise ValueError("observed_at must include timezone information")

        run_id = uuid4()
        normalized_rows = [_normalize_row(row) for row in rows if row.get("symbol")]

        with psycopg.connect(self._database_url) as connection:
            with connection.cursor() as cursor:
                _apply_migrations(cursor)
                cursor.execute(
                    """
                    INSERT INTO pipeline_runs (
                        run_id, region, source, observed_at,
                        records_received, records_loaded
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        run_id,
                        region,
                        source,
                        snapshot_at,
                        len(rows),
                        len(normalized_rows),
                    ),
                )

                cursor.executemany(
                    """
                    INSERT INTO equity_assets (
                        region, symbol, name, exchange, currency,
                        first_seen_at, last_seen_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (region, symbol) DO UPDATE SET
                        name = EXCLUDED.name,
                        exchange = EXCLUDED.exchange,
                        currency = EXCLUDED.currency,
                        last_seen_at = EXCLUDED.last_seen_at
                    """,
                    [
                        (
                            region,
                            row["symbol"],
                            row["name"],
                            row["exchange"],
                            row["currency"],
                            snapshot_at,
                            snapshot_at,
                        )
                        for row in normalized_rows
                    ],
                )

                cursor.executemany(
                    """
                    INSERT INTO equity_daily_prices (
                        region, symbol, price_date, observed_at,
                        price, market_cap, run_id
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (region, symbol, price_date) DO UPDATE SET
                        observed_at = EXCLUDED.observed_at,
                        price = EXCLUDED.price,
                        market_cap = EXCLUDED.market_cap,
                        run_id = EXCLUDED.run_id
                    """,
                    [
                        (
                            region,
                            row["symbol"],
                            snapshot_at.date(),
                            snapshot_at,
                            row["price"],
                            row["market_cap"],
                            run_id,
                        )
                        for row in normalized_rows
                    ],
                )

        return LoadResult(
            run_id=run_id,
            records_received=len(rows),
            records_loaded=len(normalized_rows),
            observed_at=snapshot_at,
        )


def _apply_migrations(cursor: Cursor[Any]) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    migration = files("yahoo_crawler.infrastructure.postgres.migrations").joinpath(
        "001_initial.sql"
    )
    cursor.execute("SELECT 1 FROM schema_migrations WHERE version = 1")
    if cursor.fetchone() is not None:
        return
    cursor.execute(migration.read_text(encoding="utf-8"))
    cursor.execute("INSERT INTO schema_migrations (version) VALUES (1)")


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": str(row["symbol"]).strip().upper(),
        "name": _optional_text(row.get("name")),
        "exchange": _optional_text(row.get("exchange")),
        "currency": _optional_text(row.get("currency")),
        "price": _optional_decimal(row.get("price"), field="price", row=row),
        "market_cap": _optional_decimal(
            row.get("market_cap"), field="market_cap", row=row
        ),
    }


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_decimal(value: Any, *, field: str, row: dict[str, Any]) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        symbol = row.get("symbol", "<unknown>")
        raise ValueError(f"Invalid {field} for symbol {symbol}: {value!r}") from exc

