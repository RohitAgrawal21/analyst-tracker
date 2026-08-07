"""Local, zero-token PDF text extraction (PyMuPDF).

Images/graphs are never touched — we only pull the text layer, which is all the
7 fields + thesis live in. The extracted text is what the model reads; the PDF
bytes never go to any model.
"""
from __future__ import annotations
import sys
from pathlib import Path

import pymupdf  # PyMuPDF


def extract_text(path: str | Path, max_pages: int | None = None) -> str:
    doc = pymupdf.open(path)
    n = doc.page_count if max_pages is None else min(max_pages, doc.page_count)
    parts = []
    for i in range(n):
        parts.append(doc[i].get_text("text"))
    doc.close()
    return "\n".join(parts)


if __name__ == "__main__":
    # extract_text.py <pdf> [max_pages]  -> prints text to stdout
    p = sys.argv[1]
    mp = int(sys.argv[2]) if len(sys.argv) > 2 else None
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(extract_text(p, mp))
