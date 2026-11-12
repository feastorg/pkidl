"""Evaluate every bake-off result: connections left open (connectivity.py), run time, determinism.

usage: uv run --project <kidl-spike> python evaluate.py > results.tsv
"""

import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent


def board_pcb(stem: str) -> Path:
    if stem.startswith("extp-"):
        stem = "ext-" + stem[5:]
    return HERE / "boards" / f"{stem}.kicad_pcb"


def missing(dsn: Path, ses: Path, pcb: Path) -> str:
    if not ses.exists() or ses.stat().st_size == 0:
        return "no-output"
    p = subprocess.run([sys.executable, str(HERE / "connectivity.py"), str(dsn), str(ses), str(pcb)],
                       capture_output=True, text=True, check=False)  # fmt: skip
    last = (p.stdout.strip().splitlines() or [""])[-1]
    return last.split()[1] if last.startswith("MISSING") else "error: " + (p.stderr.strip().splitlines() or ["?"])[-1][:80]


rows = defaultdict(dict)
for res in sorted(HERE.glob("results/*/*/run[12]/result.json")):
    r = json.loads(res.read_text())
    dsn = HERE / "boards" / f"{r['board']}.dsn"
    base = missing(dsn, Path("/dev/null"), board_pcb(r["board"])) if False else None
    m = missing(dsn, res.parent / "out.ses", board_pcb(r["board"]))
    rows[(r["router"], r["board"])][r["run"]] = (m, r["seconds"], r["rc"], r["ses_sha"])
print("router\tboard\tmissing_run1\tmissing_run2\tseconds_run1\trc_run1\tidentical")
for (router, board), runs in sorted(rows.items(), key=lambda kv: (kv[0][1], kv[0][0])):
    r1, r2 = runs.get(1), runs.get(2)
    same = "yes" if r1 and r2 and r1[3] and r1[3] == r2[3] else ("no" if r1 and r2 else "-")
    print(f"{router}\t{board}\t{r1[0] if r1 else '-'}\t{r2[0] if r2 else '-'}\t{r1[1] if r1 else '-'}\t{r1[2] if r1 else '-'}\t{same}")
