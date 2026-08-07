"""Scoring engine: turn scraped price history into per-call verdicts and
analyst / broker / stock ratings.

A "call" is scored against what the market actually did:
  - tp_hit        did price touch the target within the horizon?
  - direction_ok  did it move the way the rating implied?
  - alpha         return vs Nifty over the same window (skill, not market)
  - capture_ratio realized return / promised upside
  - max_drawdown  worst dip you'd have stomached before the target

Open calls (horizon not yet elapsed) are re-scored every night and flagged
provisional; closed calls freeze.
"""
from __future__ import annotations
import datetime as dt
import statistics
from typing import Optional

from db import connect
from prices import get_series, price_on, NIFTY

BULLISH = {"BUY", "ADD", "ACCUMULATE", "OUTPERFORM", "OVERWEIGHT"}
BEARISH = {"REDUCE", "SELL", "UNDERPERFORM", "UNDERWEIGHT"}
# everything else (HOLD, NEUTRAL) is treated as neutral


def _add_months(iso: str, months: int) -> str:
    d = dt.date.fromisoformat(iso)
    m = d.month - 1 + months
    y = d.year + m // 12
    return dt.date(y, m % 12 + 1, min(d.day, 28)).isoformat()


def score_call(call: dict) -> Optional[dict]:
    """Compute the evaluation dict for one call, or None if unscoreable."""
    ticker = call["ticker"]
    rdate = call["report_date"]
    if not ticker or not rdate:
        return None

    entry = call["cmp"] or price_on(ticker, rdate)
    if not entry:
        return None

    horizon = call["horizon_months"] or 12
    horizon_end = _add_months(rdate, horizon)
    today = dt.date.today().isoformat()
    closed = today >= horizon_end
    eval_end = horizon_end if closed else today

    series = get_series(ticker, rdate, eval_end).dropna(subset=["close"])
    if series.empty:
        return None

    # yfinance often returns the latest trading day with a NaN close (not yet
    # finalised) — use the last *valid* close, not blindly iloc[-1].
    end_close = float(series["close"].iloc[-1])
    stock_return = end_close / entry - 1

    bench = get_series(NIFTY, rdate, eval_end).dropna(subset=["close"])
    benchmark_return = None
    if not bench.empty:
        b0, b1 = float(bench["close"].iloc[0]), float(bench["close"].iloc[-1])
        benchmark_return = b1 / b0 - 1
    alpha = stock_return - benchmark_return if benchmark_return is not None else None

    rating = (call["rating"] or "").upper()
    target = call["target_price"]

    tp_hit, tp_hit_date, direction_ok, implied_upside, max_drawdown = (
        None, None, None, None, None)

    if rating in BULLISH:
        if target:
            hit = series[series["high"] >= target]
            tp_hit = 1 if not hit.empty else 0
            tp_hit_date = hit.index[0].strftime("%Y-%m-%d") if not hit.empty else None
            implied_upside = target / entry - 1
        direction_ok = 1 if stock_return > 0 else 0
        max_drawdown = float(series["low"].min()) / entry - 1  # most negative dip
    elif rating in BEARISH:
        if target:
            hit = series[series["low"] <= target]
            tp_hit = 1 if not hit.empty else 0
            tp_hit_date = hit.index[0].strftime("%Y-%m-%d") if not hit.empty else None
            implied_upside = target / entry - 1  # negative for a sell
        direction_ok = 1 if stock_return < 0 else 0
        max_drawdown = float(series["high"].max()) / entry - 1  # worst upside move
    else:  # neutral
        direction_ok = 1 if abs(stock_return) <= 0.10 else 0

    capture_ratio = None
    if implied_upside and abs(implied_upside) > 1e-6:
        capture_ratio = stock_return / implied_upside

    return {
        "call_id": call["id"],
        "status": "closed" if closed else "open",
        "tp_hit": tp_hit,
        "tp_hit_date": tp_hit_date,
        "direction_ok": direction_ok,
        "stock_return": stock_return,
        "benchmark_return": benchmark_return,
        "alpha": alpha,
        "implied_upside": implied_upside,
        "capture_ratio": capture_ratio,
        "max_drawdown": max_drawdown,
        "updated_at": dt.datetime.now().isoformat(timespec="seconds"),
    }


def score_all() -> int:
    """(Re)score every open call and any never-scored call. Returns count.

    Three phases so no two write-connections ever overlap (SQLite on a synced
    drive locks easily): read calls -> compute evals (price scraper manages its
    own short-lived connections) -> write all evals at once.
    """
    # Phase 1: read (connection closed before any price fetch writes)
    conn = connect()
    calls = [dict(r) for r in conn.execute("SELECT * FROM calls")]
    done_closed = {
        r["call_id"] for r in conn.execute(
            "SELECT call_id FROM evaluations WHERE status='closed'")
    }
    conn.close()

    # Phase 2: compute (score_call fetches/caches prices via its own connections)
    evals = []
    for call in calls:
        if call["id"] in done_closed:
            continue
        ev = score_call(call)
        if ev:
            evals.append(ev)

    # Phase 3: write all evaluations in one transaction
    conn = connect()
    conn.executemany(
        """INSERT OR REPLACE INTO evaluations
           (call_id,status,tp_hit,tp_hit_date,direction_ok,stock_return,
            benchmark_return,alpha,implied_upside,capture_ratio,
            max_drawdown,updated_at)
           VALUES (:call_id,:status,:tp_hit,:tp_hit_date,:direction_ok,
            :stock_return,:benchmark_return,:alpha,:implied_upside,
            :capture_ratio,:max_drawdown,:updated_at)""",
        evals,
    )
    conn.commit()
    conn.close()
    return len(evals)


# ---- Aggregate ratings -------------------------------------------------------

def analyst_score(rows: list[dict]) -> dict:
    """Composite 0-100 rating for a set of an analyst's evaluated calls.

    Weighted blend of hit rate, direction accuracy, and market-beating alpha,
    scaled down when the sample is thin (few calls => low confidence).
    """
    closed = [r for r in rows if r.get("alpha") is not None]
    n = len(closed)
    if n == 0:
        return {"score": None, "grade": "NR", "n": 0, "confidence": "none"}

    hit = [r["tp_hit"] for r in closed if r["tp_hit"] is not None]
    hit_rate = (sum(hit) / len(hit)) if hit else None
    dir_rate = statistics.mean(
        [r["direction_ok"] for r in closed if r["direction_ok"] is not None] or [0])
    beat = statistics.mean([1 if r["alpha"] > 0 else 0 for r in closed])
    avg_alpha = statistics.mean([r["alpha"] for r in closed])

    # blend (0-1): direction 30%, beat-market 30%, hit-rate 25%, alpha shape 15%
    parts = [(dir_rate, 0.30), (beat, 0.30)]
    if hit_rate is not None:
        parts.append((hit_rate, 0.25))
    alpha_shape = max(0.0, min(1.0, 0.5 + avg_alpha))  # +50% alpha -> 1.0
    parts.append((alpha_shape, 0.15))
    wsum = sum(w for _, w in parts)
    raw = sum(v * w for v, w in parts) / wsum

    # confidence haircut for small samples
    conf = min(1.0, n / 10)
    score = round(100 * (0.5 + (raw - 0.5) * conf))
    conf_label = "high" if n >= 10 else "medium" if n >= 4 else "low"
    return {
        "score": score,
        "grade": _grade(score),
        "n": n,
        "hit_rate": hit_rate,
        "direction_rate": dir_rate,
        "beat_market": beat,
        "avg_alpha": avg_alpha,
        "confidence": conf_label,
    }


def _grade(score: int) -> str:
    return ("A" if score >= 80 else "B" if score >= 65 else
            "C" if score >= 50 else "D" if score >= 35 else "F")


if __name__ == "__main__":
    print(f"Scored {score_all()} calls")
