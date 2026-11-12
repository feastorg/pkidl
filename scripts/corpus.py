"""The corpus: public boards pkidl must be able to express, and their scorecard.

usage:
  python scripts/corpus.py extract     write each board's circuit.json, mechanical.json and
                                       footprints/ from its reference, and corpus/manifest.json
  python scripts/corpus.py build DIR   build each board that has a board.py into
                                       DIR/<board_id>/ as built.kicad_pcb
  python scripts/corpus.py score DIR   score the boards whose filled copies (and DRC
                                       reports) are in DIR; see the justfile's corpus recipe

Each board lives in corpus/<tier>/<board_id>/ with reference.kicad_pcb (the original,
upgraded to KiCad 10: compared against, never copied from) and its LICENSE. One that
pkidl builds has a board.py there too: it makes a ``board`` from the inputs beside it.
"""

from __future__ import annotations

import hashlib
import json
import math
import runpy
import sys
from collections import Counter
from pathlib import Path

from pkidl.build import BuildError
from pkidl.footprint import footprint_path
from pkidl.importer import circuit, footprints, mechanical
from pkidl.measure import regions
from pkidl.sexpr import Node, dumps, find, find_all, parse

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "corpus"
FREEROUTING = "842ad83"  # freerouting/freerouting commit the PCBench boards come from
# What each board directory holds and the manifest hashes, beside the files under
# footprints/ and, where the board is built, its board.py.
FILES = ("LICENSE", "circuit.json", "mechanical.json", "reference.kicad_pcb")
BUILT = "built"  # the name a board file's board is built under

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


def _write_footprints(d: Path, board: Node) -> tuple[list[Path], dict[str, list[str]]]:
    """Rewrite ``d/footprints`` from *board*: the files written, and the parts carrying a
    version of their footprint other than the one written."""
    libs, differ = footprints(board)
    root = d / "footprints"
    written = []
    for name, lib in libs.items():
        path = root / footprint_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dumps(lib) + "\n")
        written.append(path)
    for stale in set(root.rglob("*.kicad_mod")) - set(written):
        stale.unlink()
    return sorted(written), differ


def extract() -> None:
    manifest = {"source": f"PCBench via freerouting/freerouting@{FREEROUTING}",
                "boards": {}}  # fmt: skip
    for board_id, (tier, licence, source) in BOARDS.items():
        d = board_dir(board_id)
        board = parse((d / "reference.kicad_pcb").read_text())
        _dump(d / "circuit.json", circuit(board))
        _dump(d / "mechanical.json", mechanical(board))
        written, differ = _write_footprints(d, board)
        files = [d / n for n in FILES] + written + [p for p in [d / "board.py"] if p.is_file()]
        manifest["boards"][board_id] = {
            "tier": tier, "licence": licence, "source": source,
            "pcbench": f"scripts/benchmark/fixtures/PCBench/{board_id}/raw.kicad_pcb",
            "sha256": {p.relative_to(d).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in files},
            # Parts whose footprint on the reference is not the version footprints/ holds.
            "other_footprint_versions": differ,
        }  # fmt: skip
        c = json.loads((d / "circuit.json").read_text())
        print(f"{tier} {board_id}: {len(c['parts'])} parts, {len(c['nets'])} nets, "
              f"{len(written)} footprints")  # fmt: skip
        for name, refs in differ.items():
            print(f"     {name}: {', '.join(refs)} carry another version of it")
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


def build(out: Path) -> int:
    """Build each board that has a ``board.py`` into ``out/<board_id>/``: the KiCad
    files as ``built.kicad_pcb`` and ``built.kicad_pro``, what the router read and
    wrote, and ``built.json``, what the build says of itself. A board file that does
    not build is said, and the rest are still built."""
    failed = 0
    for board_id in BOARDS:
        board_py = board_dir(board_id) / "board.py"
        if not board_py.is_file():
            continue
        d = out / board_id
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{BUILT}.json").unlink(missing_ok=True)  # an earlier build's is not this one's
        try:
            built = runpy.run_path(str(board_py))["board"].build(d, BUILT)
        except BuildError as e:
            failed += 1
            _dump(d / f"{BUILT}.json", {"built": False, "problems": list(e.problems)})
            print(e, file=sys.stderr)
            continue
        runs = built.routed.runs if built.routed is not None else ()
        _dump(d / f"{BUILT}.json", {
            "built": True,
            "placed": list(built.solution.poses),
            "chosen": list(built.solution.chosen),
            "routed": [{"stage": stage, "unrouted": run.unrouted} for stage, run in runs],
        })  # fmt: skip
        print(f"{BOARDS[board_id][0]} {board_id}: built, {len(built.solution.poses)} parts placed"
              + "".join(f", {run.unrouted} unrouted" for _, run in runs))  # fmt: skip
    return 1 if failed else 0


def _built(d: Path, c: dict) -> dict | None:
    """What a board file's board scores, from ``d``: None where there is none."""
    if not (d / f"{BUILT}.json").is_file():
        return None
    said = json.loads((d / f"{BUILT}.json").read_text())
    if not said["built"] or not (d / f"{BUILT}-drc.json").is_file():
        return {"built": said["built"], "run": False, "problems": said.get("problems", [])}
    board = parse((d / f"{BUILT}.kicad_pcb").read_text())
    return {
        "built": True, "run": True,
        **measures(board),
        **drc_counts(json.loads((d / f"{BUILT}-drc.json").read_text())),
        "netlist_matches": circuit(board) == c,
        "placed": len(said["placed"]),
        "unrouted": [r["unrouted"] for r in said["routed"]],
    }  # fmt: skip


def score(build: Path) -> None:
    """One row per board from ``build/<board_id>/``: ``reference.kicad_pcb`` refilled by
    KiCad and ``drc.json``, its report. Boards not run show as such. A board with a
    board file has a second row, for the board built from it (``built.kicad_pcb``,
    refilled, and ``built-drc.json``)."""
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
            "built": _built(d, c),
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
        b = r["built"]
        if b is not None and not b["run"]:
            print(f"     {'  its board.py: ' + ('not checked' if b['built'] else 'not built'):44}")
        elif b is not None:
            print(f"     {'  built from its board.py':44} {b['placed']:5} "
                  f"{'same' if b['netlist_matches'] else 'DIFF':>4} {b['errors']:4} "
                  f"{b['warnings']:4} {b['unconnected']:5} {b['vias']:5} {b['track_mm']:9} "
                  f"{len(b['split_pours']):11}")  # fmt: skip
    print(f"\nA reference is the bar its board file has to reach; under a built board, "
          f"parts is the parts placed and nets whether its netlist is the circuit's. "
          f"* KiCad's refill ran past 600 s; checked on the pours as saved. "
          f"Full rows in {build / 'scorecard.json'}.")  # fmt: skip


def main(argv: list[str]) -> int:
    if argv[1:2] == ["extract"]:
        extract()
        return 0
    if argv[1:2] == ["build"] and len(argv) == 3:
        return build(Path(argv[2]))
    if argv[1:2] == ["score"] and len(argv) == 3:
        score(Path(argv[2]))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
