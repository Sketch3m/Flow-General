"""Run the constrained loop on the five drawn papers; log every round."""
import sys
from pathlib import Path

import cells
import delta

MODE = sys.argv[1] if len(sys.argv) > 1 else "draft"
ROUNDS = int(sys.argv[2]) if len(sys.argv) > 2 else 3
SEED = "None of these systems convinces me that a new claim is true; I want to see what each one treats as evidence."

cs = [cells.Cell(id="h1", text=SEED, role="seed")]
for i, p in enumerate(sorted(Path("papers").glob("*.md")), 1):
    cs.append(cells.Cell(id=f"p{i}", text=p.read_text(encoding="utf-8"), origin="paper", role="paper"))
cells.assign(cs)
# provenance: every number this run prints is parented to this context
delta.record_context(f"run_loop mode={MODE} rounds={ROUNDS}")
print(f"mode={MODE} rounds={ROUNDS} start_words={len(cells.sheet_text(cs).split())}")
for r in range(1, ROUNDS + 1):
    res = cells.step(cs, mode=MODE, use_needle=True, use_qwen=True)
    print(f"--- round {r}")
    for line in res.get("log", []):
        print("  " + line)
    if "stopped" in res:
        print("  stopped:", res["stopped"])
        break
    cs.append(res["cell"])
    print("  wrote:", res["cell"].text)
    print("  crossed:", res["cell"].meta.get("crossed"))
