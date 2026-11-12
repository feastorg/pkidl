"""Put a router's SES onto its board for KiCad: tracks and vias added as text.

usage: uv run --project <kidl-spike> python assemble.py ROUTER BOARD_STEM OUT_STEM
Board: boards/<stem>.kicad_pcb (KiCad 10 format). Project and rules: build/<stem>/ for
our boards. Writes drc/<OUT_STEM>.kicad_pcb (+ .kicad_pro/.kicad_dru when there are any).
"""

import shutil
import sys
import uuid
from pathlib import Path

from pkidl.dsn import read_ses, via_size

HERE = Path(__file__).resolve().parent
router, stem, out = sys.argv[1:4]
src = HERE / "boards" / f"{('ext-' + stem[5:]) if stem.startswith('extp-') else stem}.kicad_pcb"
b = src.read_text()
wires, vias = read_ses(HERE / "results" / router / stem / "run1" / "out.ses")
# Drop board vias no track of their net reaches: with the pours stripped they float, and
# KiCad's ratsnest would report gaps against them instead of between the pads.
import math
import re as _re


def _touched(net, x, y, r):
    for w in wires:
        if w.net != net:
            continue
        for a, c in zip(w.points, w.points[1:], strict=False):
            dx, dy = c[0] - a[0], c[1] - a[1]
            L = dx * dx + dy * dy
            s = 0.0 if L == 0 else max(0.0, min(1.0, ((x - a[0]) * dx + (y - a[1]) * dy) / L))
            if math.hypot(x - a[0] - s * dx, y - a[1] - s * dy) <= w.width / 2 + r:
                return True
    return False


add = []
for w in wires:
    for a, c in zip(w.points, w.points[1:], strict=False):
        add.append(f'\n\t(segment (start {a[0]:.6f} {a[1]:.6f}) (end {c[0]:.6f} {c[1]:.6f}) (width {w.width}) '
                   f'(layer "{w.layer}") (net "{w.net}") (uuid "{uuid.uuid4()}"))')  # fmt: skip
for v in vias:
    d, h = via_size(v.padstack)
    if "keepvias" not in sys.argv and not _touched(v.net, v.at[0], v.at[1], d / 2):
        continue  # floats without the pours: see below
    add.append(f'\n\t(via (at {v.at[0]:.6f} {v.at[1]:.6f}) (size {d}) (drill {h}) (layers "F.Cu" "B.Cu") '
               f'(net "{v.net}") (uuid "{uuid.uuid4()}"))')  # fmt: skip
dropped = 0
for blk in _re.findall(r"\n\t\(via\n.*?\n\t\)", b, _re.S):
    at = _re.search(r"\(at ([-\d.]+) ([-\d.]+)\)", blk)
    size = _re.search(r"\(size ([\d.]+)\)", blk)
    net = _re.search(r'\(net "([^"]*)"\)', blk)
    if "keepvias" not in sys.argv and net and not _touched(net[1], float(at[1]), float(at[2]), float(size[1]) / 2):
        b = b.replace(blk, "", 1)
        dropped += 1
print("floating board vias dropped:", dropped)
i = b.rindex("\n)")
(HERE / "drc").mkdir(exist_ok=True)
(HERE / "drc" / f"{out}.kicad_pcb").write_text(b[:i] + "".join(add) + b[i:])
proj = HERE.parent / stem
for ext in ("kicad_pro", "kicad_dru"):
    if (proj / f"{stem}.{ext}").exists():
        shutil.copy(proj / f"{stem}.{ext}", HERE / "drc" / f"{out}.{ext}")
print(out, "segments", sum(len(w.points) - 1 for w in wires), "vias", len(vias))
