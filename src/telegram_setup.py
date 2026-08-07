"""One-time Telegram login + list your groups so you can pick the reports group.

Prereqs:
  1. pip install telethon   (already in requirements.txt)
  2. Get api_id + api_hash at https://my.telegram.org -> API development tools
  3. Copy telegram_config.example.json -> telegram_config.json and fill them in.

Run:  python src/telegram_setup.py
The FIRST run asks for your phone number and the login code Telegram texts you;
after that the session is saved (data/.telegram_session) and it won't ask again.
"""
from __future__ import annotations
import json
from pathlib import Path

from telethon.sync import TelegramClient

ROOT = Path(__file__).resolve().parent.parent
CFG = ROOT / "telegram_config.json"
SESSION = ROOT / "data" / ".telegram_session"  # gitignored


def load_cfg() -> dict:
    if not CFG.exists():
        raise SystemExit(
            f"Missing {CFG.name}. Copy telegram_config.example.json to "
            f"telegram_config.json and fill in api_id / api_hash.")
    cfg = json.loads(CFG.read_text(encoding="utf-8"))
    if "REPLACE" in str(cfg.get("api_hash", "")) or "REPLACE" in str(cfg.get("api_id", "")):
        raise SystemExit("Fill real api_id / api_hash into telegram_config.json first.")
    return cfg


def main() -> None:
    cfg = load_cfg()
    SESSION.parent.mkdir(parents=True, exist_ok=True)
    with TelegramClient(str(SESSION), int(cfg["api_id"]), cfg["api_hash"]) as client:
        me = client.get_me()
        print(f"Logged in as {me.first_name} (@{me.username}).\n")
        print("Your groups / channels (find the reports one and note its id):\n")
        for d in client.iter_dialogs():
            if d.is_group or d.is_channel:
                kind = "GROUP  " if d.is_group else "CHANNEL"
                print(f"  id={d.id:>16}  {kind}  {d.name}")
        print("\nTell Claude the id (and name) of the reports group.")


if __name__ == "__main__":
    main()
