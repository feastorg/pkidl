"""The corpus: public boards pkidl must be able to express, and their scorecard.

usage:
  python scripts/corpus.py extract     write each board's circuit.json and mechanical.json
                                       from its reference, and corpus/manifest.json
  python scripts/corpus.py score DIR   score the boards whose filled copies (and DRC
                                       reports) are in DIR; see the justfile's corpus recipe

Each board lives in corpus/<tier>/<board_id>/ with reference.kicad_pcb (the original,
upgraded to KiCad 10: compared against, never copied from) and its LICENSE.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from collections import Counter
from pathlib import Path

from pkidl.importer import circuit, mechanical
from pkidl.measure import regions
from pkidl.sexpr import Node, find, find_all, parse

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "corpus"
FREEROUTING = "842ad83"  # freerouting/freerouting commit the PCBench boards come from
# What each board directory holds and the manifest hashes (board.py is hashed once written).
FILES = ("LICENSE", "circuit.json", "mechanical.json", "reference.kicad_pcb")

# board_id -> (tier, licence, source repository). Licences read from each source repo.
BOARDS = {
    "esp12-breakout_ESP12Breakout": ("t0", "Apache-2.0", "https://github.com/itmarshall/esp12-breakout"),
    "qrp_swr_meter_swr_meter_rev_a": ("t0", "MIT", "https://github.com/4x1md/qrp_swr_meter"),
    "nextbusclock_NextBusClockV1": ("t0", "MIT", "https://github.com/chrisgillis/nextbusclock"),
    "DualLM317BenchSupply_DualLM317BenchSupply": ("t1", "MIT", "https://github.com/pepaslabs/DualLM317BenchSupply"),
    "free-of-charge_BMS": ("t1", "MIT", "https://github.com/hosier/free-of-charge"),
    "OpenMPPT_OpenMPPT": ("t1", "MIT", "https://github.com/Ralim/OpenMPPT"),
    "UProgrammer-Hardware_Programmer": ("t2", "MIT", "https://github.com/MackPI/UProgrammer-Hardware"),
    "bldc-gimbal-1d_gimbal-board": ("t2", "MIT", "https://github.com/swedishhat/bldc-gimbal-1d"),
    "fan_controller_fan_controller": ("t2", "MIT", "https://github.com/slightlynybbled/fan_controller"),
    "usb2serial-CH340G_USB2TTL-CH340G": ("t3", "MIT", "https://github.com/smslit/usb2serial-CH340G"),
    "pcb-usb-ft245r-parallel-adapter_pcb-usb-ft245r-parallel-adapter": ("t3", "MIT", "https://github.com/yeokm1/pcb-usb-ft245r-parallel-adapter"),
    "NRC2016_usb_sio": ("t3", "MIT", "https://github.com/alangarf/NRC2016"),
    "icehat_icehat": ("t4", "MIT", "https://github.com/emeb/icehat"),
    "rxadc_14_rxadc_14": ("t4", "MIT", "https://github.com/emeb/rxadc_14"),
    "a123-battery-integration_BCM": ("t4", "MIT", "https://github.com/MITEVT/a123-battery-integration"),
}  # fmt: skip


def board_dir(board_id: str) -> Path:
    return CORPUS / BOARDS[board_id][0] / board_id


def _dump(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")


def extract() -> None:
    manifest = {"source": f"PCBench via freerouting/freerouting@{FREEROUTING}",
                "boards": {}}  # fmt: skip
    for board_id, (tier, licence, source) in BOARDS.items():
        d = board_dir(board_id)
        board = parse((d / "reference.kicad_pcb").read_text())
        _dump(d / "circuit.json", circuit(board))
        _dump(d / "mechanical.json", mechanical(board))
        files = [d / n for n in FILES]
        manifest["boards"][board_id] = {
            "tier": tier, "licence": licence, "source": source,
            "pcbench": f"scripts/benchmark/fixtures/PCBench/{board_id}/raw.kicad_pcb",
            "sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
        }  # fmt: skip
        c = json.loads((d / "circuit.json").read_text())
        print(f"{tier} {board_id}: {len(c['parts'])} parts, {len(c['nets'])} nets")
    _dump(CORPUS / "manifest.json", manifest)


# DRC findings about the reference's footprint libraries, which are not available here:
# they say nothing about the layout.
NOT_LAYOUT = {"lib_footprint_issues", "lib_footprint_mismatch"}


def measures(board: Node) -> dict:
    """What the scorecard counts on a filled board, the same way for any board."""
    track = 0.0
    for s in find_all(board, "segment"):
        a, e = find(s, "start"), find(s, "end")
        assert a is not None and e is not None
        track += math.dist((float(a[1]), float(a[2])), (float(e[1]), float(e[2])))
    pours = regions(board)
    return {
        "vias": len(find_all(board, "via")),
        "track_mm": round(track, 1),
        "poured_nets": len(pours),
        "split_pours": sorted(n for n, r in pours.items() if r.count > 1),
    }


def drc_counts(report: dict) -> dict:
    found = [v for v in report["violations"] if v["type"] not in NOT_LAYOUT]
    errors = [v["type"] for v in found if v["severity"] == "error"]
    return {
        "errors": len(errors),
        "warnings": sum(v["severity"] == "warning" for v in found),
        "unconnected": len(report.get("unconnected_items", [])),
        "error_types": dict(Counter(errors).most_common()),
    }


def score(build: Path) -> None:
    """One row per board from ``build/<board_id>/``: ``reference.kicad_pcb`` refilled by
    KiCad and ``drc.json``, its report. Boards not run show as such."""
    rows = {}
    for board_id, (tier, _, _) in BOARDS.items():
        d = build / board_id
        if not (d / "drc.json").is_file():
            rows[board_id] = {"tier": tier, "run": False}
            continue
        c = json.loads((board_dir(board_id) / "circuit.json").read_text())
        board_py = board_dir(board_id) / "board.py"
        rows[board_id] = {
            "tier": tier, "run": True,
            "parts": len(c["parts"]), "nets": len(c["nets"]),
            "reference": {**measures(parse((d / "reference.kicad_pcb").read_text())),
                          **drc_counts(json.loads((d / "drc.json").read_text())),
                          "refilled": not (d / "not-refilled").is_file()},
            "board_py_lines": (len(board_py.read_text().splitlines())
                               if board_py.is_file() else None),
        }  # fmt: skip
    _dump(build / "scorecard.json", rows)
    print(
        f"{'tier':4} {'board':44} {'parts':>5} {'nets':>4} {'err':>4} {'warn':>4} "
        f"{'uncon':>5} {'vias':>5} {'track mm':>9} {'split pours':>11} {'board.py':>8}"
    )
    for board_id, r in rows.items():
        if not r["run"]:
            print(f"{r['tier']:4} {board_id[:44]:44} not run")
            continue
        m = r["reference"]
        lines = r["board_py_lines"] if r["board_py_lines"] is not None else "-"
        print(f"{r['tier']:4} {board_id[:44]:44} {r['parts']:5} {r['nets']:4} {m['errors']:4} "
              f"{m['warnings']:4} {m['unconnected']:5} {m['vias']:5} {m['track_mm']:9} "
              f"{len(m['split_pours']):11} {lines:>8}"
              f"{'' if m['refilled'] else '  * not refilled'}")  # fmt: skip
    print(f"\nReference boards only so far: the bar a board file has to reach. "
          f"* KiCad's refill ran past 600 s; checked on the pours as saved. "
          f"Full rows in {build / 'scorecard.json'}.")  # fmt: skip


def main(argv: list[str]) -> int:
    if argv[1:2] == ["extract"]:
        extract()
        return 0
    if argv[1:2] == ["score"] and len(argv) == 3:
        score(Path(argv[2]))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
