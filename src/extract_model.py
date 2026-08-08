"""Model extraction via headless Claude Code (uses your existing plan, no key).

The nightly job calls `claude -p` with each new report's text and the target
JSON schema. If the subscription's usage limit is hit, we raise UsageLimitError
so the runner can back off a few hours and retry (per Rohit's instruction).

Images/graphs are never sent — only the local text layer, trimmed to the first
few pages where the rating/target/thesis live, to keep it lean.
"""
from __future__ import annotations
import json
import re
import shutil
import subprocess

from extract_text import extract_text

CLAUDE_BIN = shutil.which("claude")

# phrases the Claude Code CLI prints when the subscription limit is reached
_LIMIT_MARKERS = ("usage limit", "rate limit", "limit reached", "limit will reset",
                  "out of usage", "resets at", "upgrade to", "session limit",
                  "hit your", "you've hit", "resets ", "· resets")

# phrases meaning the headless CLI login has expired (needs interactive re-auth)
_AUTH_MARKERS = ("oauth session expired", "failed to authenticate", "not logged in",
                 "please run /login", "authentication_error", "invalid api key")

PROMPT = """You are extracting structured data from one equity research PDF's text.

Return ONLY a single JSON object (no prose, no markdown fences) with this shape:
{
  "report_type": "analyst" | "market",
  "broker": "<research house>",
  "analyst": "<lead analyst name, or the desk name>",
  "report_date": "YYYY-MM-DD",
  "parse_status": "ok" | "needs_review",
  "parse_note": "<why, if needs_review, else omit>",
  "calls": [ {
      "ticker": "<NSE symbol>.NS (or .BO for BSE-only)",
      "company_raw": "<company name as printed>",
      "sector": "<sector>",
      "rating": "BUY|ADD|ACCUMULATE|HOLD|NEUTRAL|REDUCE|SELL",
      "rating_raw": "<as printed>",
      "rating_action": "initiate|reiterate|upgrade|downgrade",
      "cmp": <number or null>, "target_price": <number or null>,
      "prior_target": <number or null>,
      "horizon_months": <int, default 12>,
      "thesis": "<2-4 sentence rationale>",
      "drivers": ["..."], "risks": ["..."],
      "estimates": {"<label>": "<value>"}
  } ],
  "market": {            // include ONLY for report_type=market
      "theme": "...", "sectors": ["..."], "summary": "...",
      "outlook": "...", "key_points": ["..."]
  }
}

Rules:
- report_type is "analyst" if it carries a stock rating + target price; "market"
  for industry/macro/strategy notes. A sector report that also initiates stock
  coverage is "market" WITH a populated calls[] for those stocks.
- Resolve the NSE ticker from the company name / codes shown (e.g. BSE code,
  Bloomberg code). Append .NS.
- If a field isn't stated, use null; never invent numbers.
- report_date must be the note's publication date.

The report's extracted text is provided on standard input. Return only the JSON."""

EXTRACT_TIMEOUT = 210  # seconds; a hung claude -p must never block the run
# Extraction is simple field-pulling — force the cheapest model. Measured ~4x
# less usage than the default model (which also ran 3 agentic turns per report).
EXTRACT_MODEL = "claude-haiku-4-5"


class ExtractionError(RuntimeError):
    pass


class UsageLimitError(ExtractionError):
    """Raised when the Claude subscription usage limit blocks extraction."""


class AuthError(ExtractionError):
    """Raised when the headless `claude` CLI login has expired / is missing.

    Fix: run `claude` interactively once and log in (or `claude /login`), which
    refreshes the token that `claude -p` reuses.
    """


def extract_report(pdf_path: str, max_pages: int = 6) -> dict:
    """Extract one report's structured record via headless Claude Code."""
    if not CLAUDE_BIN:
        raise ExtractionError("`claude` CLI not found on PATH")

    # Report text goes via STDIN (not argv) — a 20k-char command-line argument
    # wedges claude on Windows. The schema/instruction is the -p prompt.
    text = extract_text(pdf_path, max_pages)[:16000]

    try:
        proc = subprocess.run(
            [CLAUDE_BIN, "-p", PROMPT, "--model", EXTRACT_MODEL,
             "--allowed-tools", ""],  # extraction needs no tools -> less overhead
            input=text, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=EXTRACT_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        raise ExtractionError(f"claude -p timed out after {EXTRACT_TIMEOUT}s")
    out = (proc.stdout or "") + "\n" + (proc.stderr or "")

    low = out.lower()
    if any(m in low for m in _AUTH_MARKERS):
        raise AuthError(out.strip()[:400])
    if any(m in low for m in _LIMIT_MARKERS):
        raise UsageLimitError(out.strip()[:400])
    if proc.returncode != 0:
        raise ExtractionError(f"claude exited {proc.returncode}: {out.strip()[:400]}")

    try:
        return _parse_json(proc.stdout)
    except Exception as e:  # wrap any JSON failure as ExtractionError (fail-safe)
        raise ExtractionError(f"could not parse model output: {e}") from e


def _parse_json(s: str) -> dict:
    """Pull the first {...} JSON object out of the model's stdout."""
    s = s.strip()
    # strip accidental ```json fences
    s = re.sub(r"^```(?:json)?|```$", "", s, flags=re.M).strip()
    start = s.find("{")
    if start == -1:
        raise ExtractionError(f"no JSON in model output: {s[:200]}")
    depth, end = 0, None
    for i in range(start, len(s)):
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end is None:
        raise ExtractionError("unterminated JSON in model output")
    return json.loads(s[start:end])
