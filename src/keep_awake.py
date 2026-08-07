"""Keep the machine awake for a fixed window so the scheduled backfill runs even
under corporate sleep settings.

Uses SetThreadExecutionState (ES_SYSTEM_REQUIRED) — the same signal media players
use. No admin rights, no power-plan changes, so group policy can't override it.

Limitation: it prevents *idle* sleep only. It does NOT stop lid-close sleep, so
keep the lid open (and plugged in) overnight.

    python src/keep_awake.py [hours]     # default 6
"""
from __future__ import annotations
import ctypes
import sys
import time

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


def main(hours: float = 6.0) -> None:
    end = time.time() + hours * 3600
    k = ctypes.windll.kernel32
    try:
        while time.time() < end:
            # re-assert every minute; ES_CONTINUOUS keeps it until reset
            k.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
            time.sleep(60)
    finally:
        k.SetThreadExecutionState(ES_CONTINUOUS)  # clear the request


if __name__ == "__main__":
    main(float(sys.argv[1]) if len(sys.argv) > 1 else 6.0)
