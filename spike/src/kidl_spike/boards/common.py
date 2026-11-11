"""What every BREAD board generator shares: the slice-bus contract and build plumbing."""

from __future__ import annotations

import builtins
import importlib
import os
import subprocess
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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


C1206 = "Capacitor_SMD:C_1206_3216Metric"


def buck_5v(part: Callable[..., Any], net: Callable[[str], Any], value: str) -> None:
    """The Slices' 12 V -> 5 V buck (U1, C1-C4, L1), with the thermal pad HS1 on GND.

    *part* and *net* are the board's constructors (``part(lib, sym, ref, **kw)``,
    ``net(name)``); *value* is U1's value field.
    """
    buck = part("KMLib_IC_Power", "AP63205WU-7_Buck_Regulator", "U1", value=value,
                footprint="KMLib_IC_SMD:SOIC_05WU-7_DIO")  # fmt: skip
    c_in = part("Device", "C_Small", "C1", value="22uF", footprint=C1206)
    c_bst = part("Device", "C_Small", "C2", value="100nF", footprint=C1206)
    c_out = [part("Device", "C_Small", ref, value="22uF", footprint=C1206) for ref in ("C3", "C4")]
    ind = part("Device", "L_Small", "L1", value="4.7uH", footprint="Inductor_SMD:L_1210_3225Metric")
    pad = part("Mechanical", "Heatsink_Pad", "HS1", footprint="KMLib_Mounting:Thermal_Pad")
    net("+12V").connect(buck[2], buck[3], c_in[2])
    net("GND").connect(buck[4], c_in[1], *(c[1] for c in c_out), pad[1])
    net("BUCK_SW").connect(buck[5], c_bst[1], ind[1])
    net("BUCK_BST").connect(buck[6], c_bst[2])
    net("+5V").connect(buck[1], ind[2], *(c[2] for c in c_out))


def status_led(part: Callable[..., Any], net: Callable[[str], Any]) -> None:
    """The Slices' WS2812 status LED D1, on +5V and GND, driven by the LED net."""
    led = part("KMLib_IC_Digital", "WS2812B_5050_RGB_LED", "D1", value="WS2812B_5050",
               footprint="KMLib_IC_SMD:WS2812-5050-4PIN")  # fmt: skip
    net("+5V").connect(led[1])
    net("GND").connect(led[3])
    net("LED").connect(led[4])
    led[2] += default_circuit().NC


def default_circuit() -> Any:
    """SKiDL's default circuit. SKiDL keeps it, and its no-connect net, in builtins."""
    import skidl  # noqa: F401  (creates the default circuit)

    return getattr(builtins, "default_circuit")  # noqa: B009


def generate(
    outdir: Path,
    name: str,
    nets: dict[str, Any],
    build_pcb: Callable[
        [Path, str, dict[str, dict[str, str]], dict[str, dict[str, str]], str], Any
    ],
    source: str | None = None,
) -> Path:
    """Write a hierarchical board's netlist and schematic from SKiDL's default circuit,
    then hand its pad nets and symbol fields to *build_pcb* for the board.

    *nets* maps every named net of the circuit to its SKiDL net; *source* is
    printed on the silkscreen and defaults to the current checkout's commit.
    """
    import skidl

    outdir.mkdir(parents=True, exist_ok=True)
    default_handler = skidl.empty_footprint_handler

    def footprint_handler(part: Any) -> None:
        # Power flags (#FLG) are virtual: no footprint, nothing on the PCB.
        if not part.ref.startswith("#"):
            default_handler(part)

    skidl.empty_footprint_handler = footprint_handler
    try:
        # do_backup would write a `<name>_sklib.py` part-library into the cwd.
        skidl.generate_netlist(file_=str((outdir / f"{name}.net").resolve()), do_backup=False)
    finally:
        skidl.empty_footprint_handler = default_handler
    # Every net is drawn as labels, so KiCad reads every net by the name given
    # here and the board's pads match it. SKiDL's two-pin snap would join some
    # pins directly and drop their labels, and KiCad would rename those nets
    # Net-(...) (F-020), so it is switched off for this call.
    # The package re-exports a function of the same name; take the module.
    gen_schematic = importlib.import_module("skidl.tools.kicad10.gen_schematic")

    for net in nets.values():
        net.stub = True
    snap = getattr(gen_schematic, "_snap_two_pin_parts")  # noqa: B009
    setattr(gen_schematic, "_snap_two_pin_parts", lambda node: None)  # noqa: B010
    try:
        with in_dir(outdir):
            # Placement is still not byte-stable between processes (F-016); the
            # netlist is, and is what the tests gate.
            skidl.generate_schematic(filepath=".", top_name=name, auto_stub=True, seed=0)
    finally:
        setattr(gen_schematic, "_snap_two_pin_parts", snap)  # noqa: B010

    pad_nets: dict[str, dict[str, str]] = {}
    for net_name, net in nets.items():
        for p in net.pins:
            if not p.part.ref.startswith("#"):
                pad_nets.setdefault(p.part.ref, {})[str(p.num)] = net_name
    # KiCad gives each no-connect pin a net of its own, named after the pin.
    for p in default_circuit().NC.pins:
        pin_name = str(p.name).replace("/", "{slash}")
        pad_nets.setdefault(p.part.ref, {})[str(p.num)] = (
            f"unconnected-({p.part.ref}-{pin_name}-Pad{p.num})"
        )
    fields: dict[str, dict[str, str]] = {}
    for part in default_circuit().parts:
        if part.ref.startswith("#"):
            continue
        # KiCad reads a "~" datasheet as empty.
        datasheet = part.datasheet if part.datasheet not in (None, "~") else ""
        fields[part.ref] = {"Datasheet": datasheet, "Description": part.description or ""}
    build_pcb(outdir, name, pad_nets, fields, source or source_id())
    return outdir
