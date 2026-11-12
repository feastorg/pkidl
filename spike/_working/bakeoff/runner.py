"""Bake-off runner: every router on every board, twice, N at a time, each capped.

usage: python runner.py [--jobs N] [--only ROUTER,...] [--boards GLOB]
Writes results/<router>/<board>/run<k>/{out.ses,log.txt,result.json}.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
CAP = 600  # seconds per run

ROUTERS = {
    "freerouting": lambda d, s, o: ["freerouting", "-de", d, "-do", s, "--router.autorouter.max_passes=100",
                                     "-mt", "1", "--router.optimizer.max_threads=1"],
    "freerouting-obstacle": lambda d, s, o: ["freerouting", "-de", d, "-do", s,
                                              "--router.autorouter.max_passes=100", "-mt", "1",
                                              "--router.optimizer.max_threads=1",
                                              "--router.plane_as_obstacle=true"],
    "fastroute": lambda d, s, o: [str(HERE / "fastroute/target/release/fastroute"), "-de", d, "-do", s,
                                  "-mp", "100", "--multi-start=1", f"--max-time={CAP - 30}",
                                  "--router.optimizer.max_threads=1", f"--report={o}/report.json"],
    "fastroute-default": lambda d, s, o: [str(HERE / "fastroute/target/release/fastroute"), "-de", d, "-do", s,
                                          f"--max-time={CAP - 30}", f"--report={o}/report.json"],
    "copperline": lambda d, s, o: [str(HERE / "copperline/build/router"), "route", d, "--output", s,
                                   "--threads", "1", "--seed", "1", "--timeout", str(CAP - 30),
                                   "--no-board-echo", "--report", f"{o}/report.json"],
    "rpmroute": lambda d, s, o: [str(HERE / "rpmroute/.venv/bin/rpmroute"), "-de", d, "-do", s, "--jobs", "1"],
    "openroute": lambda d, s, o: ["node", str(HERE / "openpcb/packages/router/dist/cli.js"), d, "-ses", s,
                                  "-quit", "-nog"],
}  # fmt: skip


def run(router: str, board: Path, k: int) -> dict:
    out = HERE / "results" / router / board.stem / f"run{k}"
    out.mkdir(parents=True, exist_ok=True)
    ses = out / "out.ses"
    ses.unlink(missing_ok=True)
    src = board
    if router == "copperline":
        # copperline's DSN subset reads neither KiCad's nor pkidl's DSN; it gets the same board as .kicad_pcb.
        src, ses = board.with_suffix(".kicad_pcb"), out / "out.kicad_pcb"
        ses.unlink(missing_ok=True)
    cmd = ROUTERS[router](str(src), str(ses), str(out))
    env = {**os.environ, "FREEROUTING__USER_DATA_PATH": str(out / "fr")}
    t0 = time.monotonic()
    with (out / "log.txt").open("w") as f:
        try:
            rc = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, env=env, timeout=CAP,
                                cwd=out, check=False).returncode  # fmt: skip
        except subprocess.TimeoutExpired:
            rc = "timeout"
    secs = round(time.monotonic() - t0, 1)
    sha = hashlib.sha256(ses.read_bytes()).hexdigest()[:16] if ses.exists() else None
    r = {"router": router, "board": board.stem, "run": k, "rc": rc, "seconds": secs, "ses_sha": sha, "cmd": cmd}
    (out / "result.json").write_text(json.dumps(r, indent=1))
    print(json.dumps({k2: r[k2] for k2 in ("router", "board", "run", "rc", "seconds", "ses_sha")}), flush=True)
    return r


ap = argparse.ArgumentParser()
ap.add_argument("--jobs", type=int, default=6)
ap.add_argument("--only", default="")
ap.add_argument("--boards", default="*.dsn")
a = ap.parse_args()
routers = a.only.split(",") if a.only else list(ROUTERS)
boards = sorted((HERE / "boards").glob(a.boards))
jobs = [(r, b, k) for k in (1, 2) for b in boards for r in routers]
print(f"{len(jobs)} runs: {len(routers)} routers x {len(boards)} boards x 2", flush=True)
with ThreadPoolExecutor(a.jobs) as ex:
    list(ex.map(lambda j: run(*j), jobs))
print("done", flush=True)
