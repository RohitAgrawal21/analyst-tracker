"""Zero-token relevance triage: decide, from local text only, whether a PDF is
worth sending to the LLM extractor.

Rohit's focus: company analyst coverage (primary) + industry/sector coverage
(secondary). Skip the noise the Telegram group is full of: daily trend/technical/
F&O notes and bulky macro / strategy / quant "opinion" reports.

No model call here — just PyMuPDF text + rules, so filtering costs ~nothing.
Labels: 'keep_analyst' | 'keep_market' | 'skip' | 'review'.
"""
from __future__ import annotations
import re
from pathlib import Path

import pymupdf

# company-report fingerprints
_TARGET = re.compile(r"\btarget\s*price\b|\btarget\b|\bTP\b|\bfair\s*value\b", re.I)
_CMP = re.compile(r"\bCMP\b|current\s*price|current\s*mkt|current\s*market\s*price", re.I)
_RATING = re.compile(
    r"\b(BUY|SELL|HOLD|ACCUMULATE|ADD|REDUCE|NEUTRAL|OUTPERFORM|UNDERPERFORM|"
    r"OVER\s?WEIGHT|UNDER\s?WEIGHT|MARKET\s?PERFORM)\b")

# STRICT industry-report markers (an explicit sector/thematic study, not just
# any doc that says "industry" somewhere).
_SECTOR_STRICT = ("sector report", "thematic report", "thematic study")
_SECTOR_SOFT = ("sector", "industry", "thematic", "initiating coverage")

# noise to skip: macro / strategy / quant / daily / technical / derivatives.
# Kept as specific phrases so we don't false-match e.g. "Technical Textiles".
_MACRO = ("quant", "asset allocation", "model portfolio", "strategy report",
          "portfolio strategy", "outlook & strategy", "outlook and strategy",
          "macro outlook", "fixed income", "global equity", "global market",
          "factor investing", "currency outlook", "commodity outlook")
_DAILY = ("technical analysis", "technical view", "technical outlook",
          "technical pick", "daily report", "daily note", "daily wrap",
          "daily market", "daily strateg", "morning note", "morning report",
          "morning brief", "f&o", "futures & options", "option strateg",
          "derivatives strateg", "nifty outlook", "bank nifty", "market wrap",
          "trade of the day", "top picks of the day", "bulk deal", "block deal",
          "pre-market", "opening bell", "closing bell", "market recap",
          "weekly wrap", "muhurat")


def classify_pdf(path: str | Path) -> tuple[str, str]:
    """Return (label, reason). Reads only the first 3 pages of text."""
    try:
        doc = pymupdf.open(path)
        pages = doc.page_count
        text = "\n".join(doc[i].get_text("text") for i in range(min(3, pages)))
        doc.close()
    except Exception as e:  # noqa: BLE001
        return "review", f"could not read pdf: {e}"

    low = text.lower()
    has_target = bool(_TARGET.search(text))
    has_cmp = bool(_CMP.search(text))
    has_rating = bool(_RATING.search(text))
    is_daily = any(k in low for k in _DAILY)
    is_macro = any(k in low for k in _MACRO)

    # 1) Company coverage — the strong signal: a rated stock with a target/CMP.
    #    Checked FIRST, so a company note that merely mentions macro/technical
    #    words is still kept.
    if has_target and has_cmp:
        return "keep_analyst", "target + CMP present"
    if has_rating and has_target:
        return "keep_analyst", "rating + target present"

    # 2) Industry coverage — deliberately STRICT (Rohit: keep this minimal, when
    #    unsure send to review, not keep). Must be an explicit sector/thematic
    #    study, carrying stock target prices, long, and free of macro/daily tone.
    strict_sector = any(k in low for k in _SECTOR_STRICT)
    if strict_sector and has_target and pages >= 10 and not is_macro and not is_daily:
        return "keep_market", "explicit sector report with stock targets"

    # 3) Clear noise.
    if is_daily:
        return "skip", "daily / technical / derivatives note"
    if is_macro:
        return "skip", "macro / strategy / quant note"

    # 4) Everything else (incl. merely sector-ish docs) is uncertain -> review,
    #    logged for rescue, but no tokens spent.
    if any(k in low for k in _SECTOR_SOFT):
        return "review", "sector-ish but does not meet strict industry bar"
    return "review", "no rating/target signal found"


if __name__ == "__main__":
    import sys
    d = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent.parent / "reports"
    for p in sorted(d.glob("*.pdf")):
        label, reason = classify_pdf(p)
        print(f"  {label:12} {reason:34} {p.name}")
