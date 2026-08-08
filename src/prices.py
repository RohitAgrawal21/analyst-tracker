"""Share-price scraping + caching (the 'judge' behind every rating).

For every analyst call we need the stock's REAL price history from the report
date forward, plus the Nifty benchmark over the same window, to decide whether
the target was hit and whether the call actually beat the market.

Prices come from yfinance (NSE via .NS, BSE via .BO), cached in SQLite so we
only ever fetch dates we don't already have.
"""
from __future__ import annotations
import datetime as dt
from typing import Optional

import pandas as pd
import yfinance as yf

from db import connect

NIFTY = "^NSEI"  # Nifty 50 benchmark for alpha


def _yf_download(ticker: str, start: str, end: str) -> pd.DataFrame:
    """Raw daily OHLC from yfinance. Empty frame on failure (never raises)."""
    try:
        df = yf.download(
            ticker, start=start, end=end, progress=False, auto_adjust=True,
            timeout=20, threads=False,  # never let a slow fetch hang the run
        )
        if df is None or df.empty:
            return pd.DataFrame()
        # yfinance sometimes returns a MultiIndex on columns for single tickers
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df
    except Exception:
        return pd.DataFrame()


def cache_prices(ticker: str, start: str, end: str) -> None:
    """Fetch [start, end] for ticker and upsert only the missing days."""
    conn = connect()
    # Only treat a day as "have" if its close is populated, so an unfinalised
    # bar (NaN close) gets re-fetched and filled on a later run.
    have = {
        r["date"]
        for r in conn.execute(
            "SELECT date FROM prices WHERE ticker=? AND date BETWEEN ? AND ? "
            "AND close IS NOT NULL",
            (ticker, start, end),
        )
    }
    df = _yf_download(ticker, start, end)
    rows = []
    for idx, row in df.iterrows():
        d = idx.strftime("%Y-%m-%d")
        if d in have:
            continue
        rows.append(
            (ticker, d, _f(row.get("Open")), _f(row.get("High")),
             _f(row.get("Low")), _f(row.get("Close")))
        )
    if rows:
        conn.executemany(
            "INSERT OR REPLACE INTO prices(ticker,date,open,high,low,close) "
            "VALUES (?,?,?,?,?,?)",
            rows,
        )
        conn.commit()
    conn.close()


def get_series(ticker: str, start: str, end: str) -> pd.DataFrame:
    """Return cached daily OHLC for ticker as a DataFrame indexed by date.

    Fetches from yfinance first if the cache doesn't span the window.
    """
    cache_prices(ticker, start, end)
    conn = connect()
    df = pd.read_sql_query(
        "SELECT date, open, high, low, close FROM prices "
        "WHERE ticker=? AND date BETWEEN ? AND ? ORDER BY date",
        conn, params=(ticker, start, end),
    )
    conn.close()
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date")
    return df


def price_on(ticker: str, date: str) -> Optional[float]:
    """Closing price on `date`, or the nearest prior trading day within a week."""
    start = (dt.date.fromisoformat(date) - dt.timedelta(days=7)).isoformat()
    df = get_series(ticker, start, date)
    if df.empty:
        return None
    return float(df["close"].iloc[-1])


def _f(v) -> Optional[float]:
    try:
        if v is None or pd.isna(v):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None
