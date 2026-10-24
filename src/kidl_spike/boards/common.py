"""What every BREAD board generator shares: the slice-bus contract and build plumbing."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from pkidl.sexpr import find, find_all, parse

# Slice-bus pinout: connector pin number -> net name. Taken from the hand-drawn
# Loaf_x004; this is the contract every slice plugs into.
BUS_PINOUT = {
    1: "GND",
    2: "+12V",
    3: "SCL_5V",
    4: "SDA_5V",
    5: "GND",
    6: "E_STOP_5V",
    7: "INT_5V",
    8: "SYNC_5V",
    9: "+12V",
    10: "GND",
}


@dataclass(frozen=True)
class SliceFormat:
    """A Slice board format: the mechanical contract a Slice case is built to.

    In the board frame a designer reads in KiCad: the bus edge on the left, y down.
    Values from the fleet's format table (bread-mechanical
    slice-case/design/synth/formats.yaml, the stand-in for bread-infra's).
    """

    width: float  # along the bus edge's normal
    height: float  # along the bus edge
    corner_r: float
    bus_inset: float  # bus pin-row centre, in from the bus edge
    bus_from_bottom: float  # bus pin-row centre, up from the bottom edge
    hole_inset: float  # each hole, in from both edges at its corner
    hole_d: float

    def outline(self, x0: float, y0: float) -> tuple[float, float, float, float]:
        return (x0, y0, x0 + self.width, y0 + self.height)

    def holes(self, x0: float, y0: float) -> list[tuple[float, float]]:
        """Centres: top-left, bottom-left, top-right, bottom-right."""
        i = self.hole_inset
        return [
            (x0 + i, y0 + i),
            (x0 + i, y0 + self.height - i),
            (x0 + self.width - i, y0 + i),
            (x0 + self.width - i, y0 + self.height - i),
        ]

    def bus_pin1(
        self, x0: float, y0: float, pins: int = 10, pitch: float = 2.54
    ) -> tuple[float, float]:
        """Pin 1 of a vertical bus connector whose pins run down the bus edge."""
        centre = y0 + self.height - self.bus_from_bottom
        return (x0 + self.bus_inset, round(centre - (pins - 1) * pitch / 2, 6))


SLICE_S = SliceFormat(width=70.0, height=100.0, corner_r=5.0, bus_inset=3.6,
                      bus_from_bottom=50.0, hole_inset=5.0, hole_d=5.0)  # fmt: skip


@dataclass(frozen=True)
class SymbolLink:
    """What links a board footprint to its schematic symbol, as KiCad stores it."""

    path: str  # "/<sheet uuid>.../<symbol uuid>", the root sheet left out
    sheetname: str  # "/" for the root sheet, "/<name>/" below it
    sheetfile: str
    fields: dict[str, str]


def symbols(schematic: Path) -> dict[str, SymbolLink]:
    """Reference -> link, for every placed symbol in a generated schematic and its sheets."""
    root = parse(schematic.read_text())
    sheets = {schematic.name: "/"}
    for s in find_all(root, "sheet"):
        props = {p[1]: p[2] for p in find_all(s, "property")}
        sheets[props["Sheetfile"]] = f"/{props['Sheetname']}/"
    out = {}
    for file, sheetname in sheets.items():
        for sym in find_all(parse((schematic.parent / file).read_text()), "symbol"):
            if find(sym, "lib_id") is None:
                continue
            props = {p[1]: p[2] for p in find_all(sym, "property")}
            ref = props.get("Reference", "")
            uid = find(sym, "uuid")
            if ref.startswith("#") or uid is None:
                continue  # power symbols and flags have no footprint
            instances = find(sym, "instances")
            project = find(instances, "project") if instances is not None else None
            inst = find(project, "path") if project is not None else None
            sheet_path = str(inst[1]).split("/")[2:] if inst is not None else []
            out[ref] = SymbolLink(
                "/" + "/".join([*sheet_path, str(uid[1])]), sheetname, file, props
            )
    return out


@contextmanager
def in_dir(path: Path) -> Iterator[None]:
    """Run inside *path*. SKiDL's schematic writer emits into the cwd."""
    prev = Path.cwd()
    path.mkdir(parents=True, exist_ok=True)
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(prev)


def source_id() -> str:
    """Short commit of the generating checkout, marked if the tree is dirty."""
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()  # fmt: skip
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return f"{sha}-dirty" if dirty else sha
