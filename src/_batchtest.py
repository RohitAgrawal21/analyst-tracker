import glob
import json
import shutil
import subprocess
import time

import extract_model as em
from extract_text import extract_text

CLAUDE = shutil.which("claude")
ps = glob.glob("../reports/*.pdf")[:5]
parts = [f"===== REPORT {i} =====\n{extract_text(p,3)[:9000]}" for i, p in enumerate(ps, 1)]
combined = "\n\n".join(parts)

t = time.time()
p = subprocess.run(
    [CLAUDE, "-p", em.PROMPT_BATCH, "--model", "claude-haiku-4-5",
     "--allowed-tools", "", "--output-format", "json"],
    input=combined, capture_output=True, text=True, encoding="utf-8",
    errors="replace", timeout=500)
j = json.loads(p.stdout)
u = j.get("usage", {})
cost = j.get("total_cost_usd", 0)
print(f"batch of {len(ps)} in {time.time()-t:.0f}s | cost ${cost:.4f} "
      f"-> ${cost/len(ps):.4f}/report | turns={j.get('num_turns')}")
recs = em._parse_json_array(j.get("result", ""))
print(f"parsed {len(recs)} records:")
for r in recs:
    c = (r.get("calls") or [{}])
    print("  ", r.get("broker"), "|", (c[0] if c else {}).get("ticker"),
          (c[0] if c else {}).get("rating"), (c[0] if c else {}).get("target_price"))
