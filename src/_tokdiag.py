import json
import shutil
import subprocess

from extract_text import extract_text

CLAUDE = shutil.which("claude")
text = extract_text("../reports/HCL-Technologies-Q1FY27.pdf", 4)[:16000]
prompt = "Extract broker, analyst, rating, target price as JSON. Report text is on stdin."

for model in ("claude-haiku-4-5", None):
    args = [CLAUDE, "-p", prompt, "--output-format", "json"]
    if model:
        args += ["--model", model]
    try:
        p = subprocess.run(args, input=text, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=220)
        j = json.loads(p.stdout)
        u = j.get("usage", {})
        it = u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
        print(f"model={model or 'DEFAULT'}: total_in={it} out={u.get('output_tokens')} "
              f"cost_usd={j.get('total_cost_usd')} turns={j.get('num_turns')} model_used={j.get('model','?')}")
        print("   raw usage:", u)
    except Exception as e:
        print(f"model={model}: FAILED {type(e).__name__}: {str(e)[:200]} | out={p.stdout[:200] if 'p' in dir() else ''}")
