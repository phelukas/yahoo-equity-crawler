CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id UUID PRIMARY KEY,
    region TEXT NOT NULL,
    source TEXT NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    records_received INTEGER NOT NULL,
    records_loaded INTEGER NOT NULL,
    completed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS equity_assets (
    region TEXT NOT NULL,
    symbol TEXT NOT NULL,
    name TEXT,
    exchange TEXT,
    currency TEXT,
    first_seen_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (region, symbol)
);

CREATE TABLE IF NOT EXISTS equity_daily_prices (
    region TEXT NOT NULL,
    symbol TEXT NOT NULL,
    price_date DATE NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    price NUMERIC(24, 6),
    market_cap NUMERIC(30, 2),
    run_id UUID NOT NULL REFERENCES pipeline_runs(run_id),
    PRIMARY KEY (region, symbol, price_date),
    FOREIGN KEY (region, symbol) REFERENCES equity_assets(region, symbol)
);

CREATE INDEX IF NOT EXISTS equity_daily_prices_symbol_date_idx
    ON equity_daily_prices (symbol, price_date DESC);
