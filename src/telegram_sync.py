"""Pull PDFs from the Telegram reports group, triage them locally (zero tokens),
and drop the keepers into reports/ for the pipeline.

Uses the saved session (login done once via telegram_setup.py), so it runs
unattended. Newest-first, resumable via a persisted set of processed message
ids. Downloading + triage cost no Claude usage — only the later extraction does.
"""
from __future__ import annotations
import datetime as dt
import json
import re
from pathlib import Path

from telethon.sync import TelegramClient

from relevance import classify_pdf
from ingest import REPORTS_DIR, file_text_hash, text_hash_seen

ROOT = Path(__file__).resolve().parent.parent
CFG = ROOT / "telegram_config.json"
SESSION = ROOT / "data" / ".telegram_session"
STATE = ROOT / "data" / "telegram_state.json"
REVIEW_DIR = ROOT / "telegram_review"
TMP_DIR = ROOT / "data" / "_tg_tmp"
FILTERED_LOG = ROOT / "data" / "filtered.log"


def _cfg() -> dict:
    return json.loads(CFG.read_text(encoding="utf-8"))


def _load_state() -> dict:
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}


def _save_state(s: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(s), encoding="utf-8")


def _safe_name(name: str | None, mid: int) -> str:
    name = (name or f"tg_{mid}.pdf").strip()
    name = re.sub(r"[^\w\-.() ]", "_", name)
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    return name[:180]


def _is_pdf(msg) -> bool:
    f = getattr(msg, "file", None)
    if not f:
        return False
    if (f.mime_type or "") == "application/pdf":
        return True
    return (f.name or "").lower().endswith(".pdf")


def _log(name: str, label: str, reason: str) -> None:
    FILTERED_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(FILTERED_LOG, "a", encoding="utf-8") as fh:
        fh.write(f"{dt.datetime.now():%Y-%m-%d %H:%M}\t{label}\t{reason}\t{name}\n")


def sync(limit: int | None = None, log=print) -> int:
    """Download new PDFs from the configured group, triage, route. Returns the
    number kept (moved into reports/). `limit` caps downloads per call (for
    testing); None = all new messages."""
    cfg = _cfg()
    chat = cfg.get("chat_id")
    if chat is None:
        log("telegram: no chat_id in config, skipping.")
        return 0
    if not SESSION.with_suffix(".session").exists() and not SESSION.exists():
        log("telegram: no saved session (run telegram_setup.py first), skipping.")
        return 0

    state = _load_state()
    key = str(chat)
    processed = set(state.get(key, {}).get("processed", []))
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    TMP_DIR.mkdir(parents=True, exist_ok=True)

    kept = reviewed = skipped = dups = 0
    seen_hashes: set[str] = set()

    def _persist():
        state[key] = {"processed": sorted(processed),
                      "synced_at": dt.datetime.now().isoformat(timespec="seconds")}
        _save_state(state)

    seen = 0
    with TelegramClient(str(SESSION), int(cfg["api_id"]), cfg["api_hash"]) as client:
        entity = client.get_entity(chat)
        for msg in client.iter_messages(entity):  # newest first
            seen += 1
            if seen % 25 == 0:  # checkpoint so a kill mid-run is resumable
                _persist()
            if msg.id in processed:
                continue
            if not _is_pdf(msg):
                processed.add(msg.id)
                continue

            fname = _safe_name(msg.file.name if msg.file else None, msg.id)
            tmp = TMP_DIR / f"{msg.id}_{fname}"
            try:
                client.download_media(msg, file=str(tmp))
            except Exception as e:  # noqa: BLE001
                log(f"  telegram download failed (msg {msg.id}): {e}")
                continue

            processed.add(msg.id)
            th = file_text_hash(tmp)
            if th and (th in seen_hashes or text_hash_seen(th)):
                tmp.unlink(missing_ok=True)
                dups += 1
            else:
                if th:
                    seen_hashes.add(th)
                label, reason = classify_pdf(tmp)
                if label in ("keep_analyst", "keep_market"):
                    dest = _unique(REPORTS_DIR / fname)
                    tmp.replace(dest)
                    kept += 1
                elif label == "review":
                    tmp.replace(_unique(REVIEW_DIR / fname))
                    reviewed += 1
                    _log(fname, label, reason)
                else:  # skip noise, keep only a log line
                    tmp.unlink(missing_ok=True)
                    skipped += 1
                    _log(fname, label, reason)

            if limit and (kept + reviewed + skipped + dups) >= limit:
                break

        _persist()

    log(f"  telegram sync: kept={kept} review={reviewed} skipped={skipped} dup={dups}")
    return kept


def _unique(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suf = path.stem, path.suffix
    i = 2
    while (path.parent / f"{stem} ({i}){suf}").exists():
        i += 1
    return path.parent / f"{stem} ({i}){suf}"


if __name__ == "__main__":
    import sys
    lim = int(sys.argv[1]) if len(sys.argv) > 1 else None
    sync(limit=lim)
