"""SQLite schema + connection for the Analyst Rating & Tracker.

One local DB (data/tracker.db). No server. The nightly job reads/writes here,
then build_site.py renders it to a static site for GitHub Pages.
"""
from __future__ import annotations
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "tracker.db"

SCHEMA = """
-- One row per source PDF we've seen. content_hash makes extraction idempotent:
-- a file is never re-parsed once its hash is known.
-- report_type splits the two document kinds:
--   'analyst' -> has scored calls (rating + target price)
--   'market'  -> industry/macro note, no calls; summarized as context
CREATE TABLE IF NOT EXISTS reports (
    id              INTEGER PRIMARY KEY,
    filename        TEXT NOT NULL,
    content_hash    TEXT NOT NULL UNIQUE,   -- sha256 of file bytes
    text_hash       TEXT,                   -- sha256 of extracted text (catches
                                            -- renamed/re-exported copies)
    report_type     TEXT NOT NULL DEFAULT 'analyst',
    broker          TEXT,
    analyst         TEXT,
    report_date     TEXT,              -- ISO YYYY-MM-DD
    parse_status    TEXT NOT NULL,     -- 'ok' | 'needs_review' | 'error'
    parse_note      TEXT,              -- why it needs review, if so
    ingested_at     TEXT NOT NULL
);

-- One row per recommendation (a "call"). A report usually has exactly one,
-- but multi-stock notes (e.g. a morning note) can have several.
-- The *_json columns hold the intelligence layer: pulled once at extraction,
-- reused forever by the site so answering "why?" costs no further tokens.
CREATE TABLE IF NOT EXISTS calls (
    id              INTEGER PRIMARY KEY,
    report_id       INTEGER NOT NULL REFERENCES reports(id),
    ticker          TEXT,              -- resolved NSE ticker e.g. RELIANCE.NS
    company_raw     TEXT,              -- name as printed in the report
    sector          TEXT,
    rating          TEXT,              -- normalized: BUY/ADD/HOLD/REDUCE/SELL
    rating_raw      TEXT,              -- as printed (e.g. "Accumulate")
    rating_action   TEXT,              -- upgrade | downgrade | reiterate | initiate
    cmp             REAL,              -- price at report time, as printed
    target_price    REAL,
    prior_target    REAL,              -- previous TP if the note revised one
    horizon_months  INTEGER DEFAULT 12,
    report_date     TEXT,              -- denormalized for fast scoring
    thesis          TEXT,              -- 2-4 sentence rationale (the "why")
    drivers_json    TEXT,              -- JSON list of key drivers
    risks_json      TEXT,              -- JSON list of risks
    estimates_json  TEXT               -- JSON of key estimates (rev/EPS/margin/PE)
);

-- Industry / macro reports: no calls, stored as browsable + queryable context.
CREATE TABLE IF NOT EXISTS market_reports (
    id              INTEGER PRIMARY KEY,
    report_id       INTEGER NOT NULL REFERENCES reports(id),
    theme           TEXT,              -- e.g. "Indian Textiles", "Aug-26 Quant"
    sectors_json    TEXT,              -- JSON list of sectors/tickers touched
    summary         TEXT,              -- what it says
    outlook         TEXT,              -- where things are heading
    key_points_json TEXT               -- JSON list of notable data points
);

-- Daily OHLC cache so we only ever fetch missing dates from yfinance.
CREATE TABLE IF NOT EXISTS prices (
    ticker          TEXT NOT NULL,
    date            TEXT NOT NULL,
    open            REAL, high REAL, low REAL, close REAL,
    PRIMARY KEY (ticker, date)
);

-- Recomputed every night for open calls; frozen once a call closes.
CREATE TABLE IF NOT EXISTS evaluations (
    call_id         INTEGER PRIMARY KEY REFERENCES calls(id),
    status          TEXT,              -- 'open' | 'closed'
    tp_hit          INTEGER,           -- 1/0: did price touch target in horizon
    tp_hit_date     TEXT,
    direction_ok    INTEGER,           -- 1/0: moved the way the rating implied
    stock_return    REAL,              -- realized, report_date -> eval point
    benchmark_return REAL,             -- Nifty over same window
    alpha           REAL,              -- stock_return - benchmark_return
    implied_upside  REAL,              -- target/cmp - 1
    capture_ratio   REAL,              -- stock_return / implied_upside
    max_drawdown    REAL,              -- worst dip before target/horizon
    updated_at      TEXT
);

CREATE INDEX IF NOT EXISTS idx_calls_ticker ON calls(ticker);
CREATE INDEX IF NOT EXISTS idx_calls_report ON calls(report_id);
CREATE INDEX IF NOT EXISTS idx_mkt_report ON market_reports(report_id);
"""


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    # timeout + busy_timeout: the DB lives on a synced Google Drive folder, so
    # brief file locks from the sync client are expected — wait them out.
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def init() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


if __name__ == "__main__":
    init()
    print(f"Initialized DB at {DB_PATH}")
