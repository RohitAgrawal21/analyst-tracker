"""Nightly orchestrator — the single entrypoint Task Scheduler runs.

    python src/run_nightly.py

Steps:
  1. Extract every NEW pdf in reports/ (headless Claude Code) and ingest it.
     If the subscription usage limit is hit, back off a few hours and retry
     (per Rohit's instruction). PDFs that still can't be read are parked in
     staging/pending/ so nothing is lost.
  2. Refresh prices, re-score every open call (this always runs, so the site
     stays current even on nights with no new reports).
  3. Rebuild the static site.
  4. If reports/ sits in a git repo, commit + push the refreshed site.

Flags:
  --no-wait     don't sleep on a usage limit (park pending and move on)
  --no-publish  skip the git commit/push step
Env:
  BACKOFF_HOURS (default 3)   MAX_LIMIT_RETRIES (default 3)
"""
from __future__ import annotations
import datetime as dt
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import ingest
from ingest import REPORTS_DIR, ingest_record, file_hash
import score as scoring
import build_site

ROOT = Path(__file__).resolve().parent.parent
PENDING = ROOT / "staging" / "pending"
BACKOFF_HOURS = float(os.environ.get("BACKOFF_HOURS", "3"))
MAX_LIMIT_RETRIES = int(os.environ.get("MAX_LIMIT_RETRIES", "3"))


try:  # keep logs clean on the Windows cp1252 console
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass


LOGFILE = ROOT / "data" / "nightly.log"
CHECKPOINT_EVERY = 25  # publish progress after this many new extractions


def log(msg: str) -> None:
    line = f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    try:  # also persist so scheduled runs aren't a black box
        LOGFILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOGFILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:  # noqa: BLE001
        pass


def sync_telegram() -> None:
    """Pull new PDFs from the Telegram group into reports/ (usage-free).

    Capped per run so the download phase can never starve extraction (that bug
    wedged the first overnight run for hours)."""
    try:
        import telegram_sync
    except Exception as e:  # noqa: BLE001 - telethon not installed etc.
        log(f"Telegram sync unavailable ({e}); skipping.")
        return
    try:
        telegram_sync.sync(limit=120, log=log)
    except Exception as e:  # noqa: BLE001 - never let sync kill the run
        log(f"Telegram sync error ({type(e).__name__}: {e}); continuing.")


def extract_new(no_wait: bool, no_publish: bool) -> int:
    """Extract + ingest every new PDF, with usage-limit backoff. Returns count.
    Publishes progress every CHECKPOINT_EVERY extractions so a big backfill shows
    up on the site as it goes, not only at the very end."""
    from extract_model import (extract_report, UsageLimitError, AuthError,
                               ExtractionError)

    pending = ingest.new_pdfs()
    if not pending:
        log("No new reports.")
        return 0
    log(f"{len(pending)} new report(s) to extract.")

    from ingest import file_text_hash, text_hash_seen
    from relevance import classify_pdf

    ingested = 0
    retries = 0
    i = 0
    while i < len(pending):
        pdf = pending[i]
        # cheap content-dedup before spending an LLM call on a re-download
        if text_hash_seen(file_text_hash(pdf)):
            log(f"  duplicate of an existing note, skipping (no extraction): {pdf.name}")
            i += 1
            continue
        # zero-token relevance triage: only company / strict-industry coverage
        # reaches the LLM; everything else is logged, not extracted.
        label, reason = classify_pdf(pdf)
        if label not in ("keep_analyst", "keep_market"):
            log(f"  filtered [{label}: {reason}] -> {pdf.name}")
            _log_filtered(pdf.name, label, reason)
            i += 1
            continue
        try:
            rec = extract_report(str(pdf))
            rid = ingest_record(pdf.name, rec)
            if rid == -2:
                log(f"  skipped duplicate (same broker/ticker/date/target): {pdf.name}")
            else:
                log(f"  ingested: {pdf.name}")
                ingested += 1
                if ingested % CHECKPOINT_EVERY == 0:
                    log(f"  checkpoint at {ingested} extractions -> publishing progress")
                    refresh()
                    publish(no_publish)
            i += 1
        except AuthError as e:
            # every remaining PDF will fail the same way — park them all and stop.
            log(f"  claude login expired -> parking {len(pending) - i} report(s). "
                f"Fix: run `claude` and log in, then re-run. Detail: {e}")
            _park(pending[i:])
            break
        except UsageLimitError as e:
            if no_wait or retries >= MAX_LIMIT_RETRIES:
                log(f"  usage limit -> parking remaining {len(pending) - i} report(s).")
                _park(pending[i:])
                break
            retries += 1
            log(f"  usage limit hit (retry {retries}/{MAX_LIMIT_RETRIES}); "
                f"backing off {BACKOFF_HOURS}h. Detail: {e}")
            time.sleep(BACKOFF_HOURS * 3600)
            # loop again on the same pdf after the wait
        except Exception as e:  # noqa: BLE001 - never let one bad PDF kill the run
            log(f"  extraction failed for {pdf.name}: {type(e).__name__}: {e} -> parking.")
            _park([pdf])
            i += 1
    return ingested


FILTERED_LOG = ROOT / "data" / "filtered.log"


def _log_filtered(name: str, label: str, reason: str) -> None:
    """Record a filtered-out file so Rohit can rescue false negatives."""
    FILTERED_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(FILTERED_LOG, "a", encoding="utf-8") as f:
        f.write(f"{dt.datetime.now():%Y-%m-%d %H:%M}\t{label}\t{reason}\t{name}\n")


def _park(pdfs: list[Path]) -> None:
    """Save extracted text of un-ingested PDFs so they can be done later."""
    from extract_text import extract_text
    PENDING.mkdir(parents=True, exist_ok=True)
    for p in pdfs:
        try:
            (PENDING / (p.stem + ".txt")).write_text(
                extract_text(str(p), 6), encoding="utf-8")
        except Exception as e:  # noqa: BLE001 - best-effort parking
            log(f"  could not park {p.name}: {e}")


def refresh() -> None:
    log("Scraping prices + scoring open calls...")
    n = scoring.score_all()
    log(f"  scored {n} call(s).")
    out = build_site.render()
    log(f"  built site: {out}")


def publish(no_publish: bool) -> None:
    if no_publish:
        return
    if not (ROOT / ".git").exists():
        log("Not a git repo — skipping publish. (Run `git init` + add a remote to enable.)")
        return
    try:
        subprocess.run(["git", "-C", str(ROOT), "add", "docs"], check=False)
        msg = f"nightly refresh {dt.datetime.now():%Y-%m-%d %H:%M}"
        r = subprocess.run(["git", "-C", str(ROOT), "commit", "-m", msg],
                           capture_output=True, text=True)
        if r.returncode != 0 and "nothing to commit" in (r.stdout + r.stderr).lower():
            log("  no changes to publish.")
            return
        subprocess.run(["git", "-C", str(ROOT), "push"], check=False)
        log("  pushed to GitHub Pages.")
    except Exception as e:  # noqa: BLE001
        log(f"  publish failed: {e}")


LOCK = ROOT / "data" / ".nightly.lock"


def _acquire_lock() -> bool:
    """Prevent two runs (e.g. the backfill task + the daily task) overlapping."""
    if LOCK.exists() and (time.time() - LOCK.stat().st_mtime) < 13 * 3600:
        return False
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    LOCK.write_text(str(os.getpid()))
    return True


def main(argv: list[str]) -> None:
    no_wait = "--no-wait" in argv
    no_publish = "--no-publish" in argv
    if not _acquire_lock():
        log("another run is active (lock held); exiting.")
        return
    try:  # keep the machine awake for the duration of this run
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)
    except Exception:  # noqa: BLE001 - non-Windows / no ctypes
        pass
    log("=== nightly run start ===")
    try:
        # Extract the already-downloaded backlog FIRST (visible progress); pull
        # new PDFs from Telegram afterwards so downloads never starve extraction.
        try:
            extract_new(no_wait, no_publish)
        except Exception as e:  # noqa: BLE001 - sync/publish must still run
            log(f"Extraction phase error ({type(e).__name__}: {e}); continuing.")
        sync_telegram()
        refresh()
        publish(no_publish)
    finally:
        LOCK.unlink(missing_ok=True)
    log("=== nightly run done ===")


if __name__ == "__main__":
    main(sys.argv[1:])
