"""Ingestion: load extracted report records into the DB, idempotently.

A report is identified by the SHA-256 of its file bytes, so re-running the
nightly job never double-counts a PDF. The *extraction* itself (reading the
PDF and producing the structured dict) is done by the model — me now for the
one-time backfill, headless Claude Code nightly thereafter — and handed to
`ingest_record()` as a plain dict.
"""
from __future__ import annotations
import datetime as dt
import hashlib
import json
from pathlib import Path

from db import connect

REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def already_ingested(content_hash: str) -> bool:
    conn = connect()
    row = conn.execute(
        "SELECT 1 FROM reports WHERE content_hash=?", (content_hash,)
    ).fetchone()
    conn.close()
    return row is not None


def new_pdfs() -> list[Path]:
    """PDFs in reports/ whose hash we haven't ingested yet."""
    out = []
    for p in sorted(REPORTS_DIR.glob("*.pdf")):
        if not already_ingested(file_hash(p)):
            out.append(p)
    return out


def file_text_hash(path: Path) -> str | None:
    """sha256 of the report's extracted text (first 6 pages). Two files with the
    same content but different bytes (a re-export/rename) share this hash."""
    try:
        from extract_text import extract_text
        return hashlib.sha256(
            extract_text(str(path), 6).encode("utf-8", "replace")).hexdigest()
    except Exception:  # noqa: BLE001 - dedup is best-effort
        return None


def text_hash_seen(thash: str | None) -> bool:
    if not thash:
        return False
    conn = connect()
    row = conn.execute(
        "SELECT 1 FROM reports WHERE text_hash=? LIMIT 1", (thash,)).fetchone()
    conn.close()
    return row is not None


def ingest_record(filename: str, rec: dict) -> int:
    """Insert one extracted report (+ its calls or market summary).

    `rec` shape:
      {
        "report_type": "analyst" | "market",
        "broker": str, "analyst": str, "report_date": "YYYY-MM-DD",
        "parse_status": "ok" | "needs_review", "parse_note": str|None,
        # analyst reports:
        "calls": [ {ticker, company_raw, sector, rating, rating_raw,
                    rating_action, cmp, target_price, prior_target,
                    horizon_months, thesis, drivers[], risks[], estimates{}} ],
        # market reports:
        "market": {theme, sectors[], summary, outlook, key_points[]}
      }
    Returns the report id. Skips (returns -1) if already ingested.
    """
    path = REPORTS_DIR / filename
    chash = file_hash(path)
    if already_ingested(chash):
        return -1

    # content-level dedup: catches a renamed / re-exported copy of a note we
    # already have (same extracted text, different file bytes).
    thash = file_text_hash(path)
    if text_hash_seen(thash):
        return -2

    conn = connect()
    cur = conn.execute(
        """INSERT INTO reports
           (filename, content_hash, text_hash, report_type, broker, analyst,
            report_date, parse_status, parse_note, ingested_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (filename, chash, thash, rec.get("report_type", "analyst"),
         rec.get("broker"), rec.get("analyst"), rec.get("report_date"),
         rec.get("parse_status", "ok"), rec.get("parse_note"),
         dt.datetime.now().isoformat(timespec="seconds")),
    )
    report_id = cur.lastrowid

    for c in rec.get("calls", []) or []:
        conn.execute(
            """INSERT INTO calls
               (report_id, ticker, company_raw, sector, rating, rating_raw,
                rating_action, cmp, target_price, prior_target, horizon_months,
                report_date, thesis, drivers_json, risks_json, estimates_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (report_id, c.get("ticker"), c.get("company_raw"), c.get("sector"),
             (c.get("rating") or "").upper(), c.get("rating_raw"),
             c.get("rating_action"), c.get("cmp"), c.get("target_price"),
             c.get("prior_target"), c.get("horizon_months", 12),
             rec.get("report_date"), c.get("thesis"),
             json.dumps(c.get("drivers") or []),
             json.dumps(c.get("risks") or []),
             json.dumps(c.get("estimates") or {})),
        )

    m = rec.get("market")
    if m:
        conn.execute(
            """INSERT INTO market_reports
               (report_id, theme, sectors_json, summary, outlook, key_points_json)
               VALUES (?,?,?,?,?,?)""",
            (report_id, m.get("theme"), json.dumps(m.get("sectors") or []),
             m.get("summary"), m.get("outlook"),
             json.dumps(m.get("key_points") or [])),
        )

    conn.commit()
    conn.close()
    return report_id


def ingest_dir(staging: Path) -> int:
    """Load every <name>.json in a staging dir. Each JSON must carry a
    top-level 'filename' pointing at the source PDF in reports/."""
    n = 0
    for jf in sorted(staging.glob("*.json")):
        rec = json.loads(jf.read_text(encoding="utf-8"))
        if ingest_record(rec["filename"], rec) != -1:
            n += 1
    return n
