# Analyst Rating & Tracker

Scores equity analysts on how their recommendations and target prices actually
performed, and flags who to trust less. Built to run itself.

## How it works

1. **You** drop broker PDFs into `reports/` throughout the day.
2. **Nightly**, a local Task Scheduler job runs `src/run_nightly.py`, which:
   - finds new PDFs (by content hash, so nothing is parsed twice),
   - extracts 7 fields locally with zero LLM tokens (broker, analyst, date,
     company, rating, CMP, target price),
   - fetches only the missing price days from yfinance,
   - re-scores every open call and freezes closed ones,
   - rebuilds the static site and `git push`es it to GitHub Pages.
3. **Anyone** with the GitHub Pages link sees the ratings. The PDFs stay on your
   machine (`reports/` is gitignored) — only the computed numbers are published.

## Running it

```bash
# one-time: create the venv + deps
python -m venv .venv && ./.venv/Scripts/python.exe -m pip install -r requirements.txt

# the nightly job (Task Scheduler runs this):
python src/run_nightly.py            # extract new PDFs, scrape prices, score, rebuild, publish
python src/run_nightly.py --no-wait --no-publish   # skip usage-limit sleeps + git push (testing)
```

Individual stages: `python src/backfill_samples.py` (one-time seed load),
`python src/score.py` (re-score), `python src/build_site.py` (rebuild only).

On a usage limit during extraction, the runner waits `BACKOFF_HOURS` (default 3)
and retries up to `MAX_LIMIT_RETRIES` (default 3); anything still unread is parked
in `staging/pending/` so nothing is lost.

## Scoring

Per call: target-hit, direction, **alpha vs Nifty** (skill, not a rising
market), capture ratio, optimism bias, drawdown. Rolled up into 0-100 / A-F
ratings per analyst, broker, and stock, weighted by sample size. Plus a
pre-emptive tracker: fade flags, track-record drift, chronic optimism, and an
open-call watchlist.

## Layout

| Path | What |
|---|---|
| `reports/` | Your PDFs (local only, gitignored) |
| `data/tracker.db` | SQLite: reports, calls, prices, evaluations |
| `src/db.py` | Schema + connection |
| `src/extract.py` | Local field extraction (regex/heuristics) |
| `src/prices.py` | yfinance fetch + cache |
| `src/score.py` | Scoring engine |
| `src/build_site.py` | Renders the static site |
| `src/run_nightly.py` | The cron entrypoint that chains it all |
| `site/` | Generated static site for GitHub Pages |

Zero admin installs, zero server, near-zero tokens.
