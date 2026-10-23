"""Generate the electrical layer of Loaf_x004 — the BREAD power/bus backplane.

Loaf_x004 takes a 12 V barrel-jack input and distributes it to six 10-pin
slice-bus connectors. Every bus connector carries the same contract: 12 V, GND
and the five 5 V slice-bus signals. This module expresses that netlist in SKiDL;
KiCad is the oracle for whether it is correct (`just verify loaf`).

The slice-bus pinout, identical on every 10-pin connector (J2–J7):

    1  GND        6  E_STOP_5V
    2  +12V       7  INT_5V
    3  SCL_5V     8  SYNC_5V
    4  SDA_5V     9  +12V
    5  GND       10  GND

J1 is the barrel jack: pin 1 = +12V, pin 2 = GND.

All symbols here are stock KiCad (`Connector:*`); only the footprints reach into
KiCad-Master-Lib. Everything resolves through `libs.configure_skidl()`, never the
developer's global KiCad config.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from kidl_spike import libs
from kidl_spike.boards import loaf_layout

BUILD = Path("build/loaf")

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

# The six bus connectors, in board order: (reference, symbol, footprint). J2/J7
# use stock pin-header/socket footprints; J3–J6 use the BREAD custom bus
# footprint. All six are wired to the identical bus pinout above.
BUS_CONNECTORS = [
    ("J2", "Conn_01x10_Pin", "Connector_PinHeader_2.54mm:PinHeader_1x10_P2.54mm_Horizontal"),
    ("J3", "Conn_01x10_Pin", "KMLib_Connectors:BREAD_Slice_Bus_10Pin"),
    ("J4", "Conn_01x10_Pin", "KMLib_Connectors:BREAD_Slice_Bus_10Pin"),
    ("J5", "Conn_01x10_Pin", "KMLib_Connectors:BREAD_Slice_Bus_10Pin"),
    ("J6", "Conn_01x10_Pin", "KMLib_Connectors:BREAD_Slice_Bus_10Pin"),
    ("J7", "Conn_01x10_Socket", "Connector_PinSocket_2.54mm:PinSocket_1x10_P2.54mm_Horizontal"),
]

# The power input: a 12 V barrel jack. Pin 1 = +12V, pin 2 = GND (2-pin symbol).
BARREL_JACK = ("J1", "Barrel_Jack", "Connector_BarrelJack:BarrelJack_CUI_PJ-063AH_Horizontal")


@contextmanager
def _in_dir(path: Path) -> Iterator[None]:
    """Run inside *path*. SKiDL's schematic writer emits into the cwd."""
    prev = Path.cwd()
    path.mkdir(parents=True, exist_ok=True)
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(prev)


def circuit(workdir: Path | None = None) -> dict[str, Any]:
    """Build the Loaf circuit into SKiDL's default circuit; return its nets by name."""
    import skidl

    skidl.reset()  # start from an empty circuit, so repeated builds don't accumulate
    # Resolve libraries from the committed tables, never the global KiCad config.
    libs.configure_skidl(workdir=workdir)

    def part(lib: str, sym: str, ref: str, **kw: Any) -> Any:
        # A fixed tag keeps SKiDL's generated UUIDs stable from run to run.
        return skidl.Part(lib, sym, ref=ref, tag=ref, **kw)

    nets = {name: skidl.Net(name) for name in dict.fromkeys(BUS_PINOUT.values())}

    jack_ref, jack_sym, jack_fp = BARREL_JACK
    jack = part("Connector", jack_sym, jack_ref, footprint=jack_fp)
    nets["+12V"] += jack[1]
    nets["GND"] += jack[2]

    for ref, sym, fp in BUS_CONNECTORS:
        conn = part("Connector", sym, ref, footprint=fp)
        for pin, net_name in BUS_PINOUT.items():
            nets[net_name] += conn[pin]

    # Power enters through the jack, whose pins are passive, so nothing on the
    # board drives +12V or GND. PWR_FLAG tells ERC they are driven off-board.
    # The hand-drawn Loaf_x004 omits these and fails ERC with two
    # power_pin_not_driven errors.
    for i, name in enumerate(("+12V", "GND"), start=1):
        nets[name] += part("power", "PWR_FLAG", f"#FLG0{i}")[1]

    return nets


def build(outdir: Path = BUILD, source: str | None = None) -> Path:
    """Build the Loaf into *outdir*: netlist, schematic, board and project.

    *source* is printed on the board's silkscreen to trace it back to the
    generating commit; it defaults to the current checkout's.
    Returns the directory the KiCad files were written to.
    """
    import skidl

    # Absolute workdir so the materialised fp-lib-table survives the chdir below.
    nets = circuit(workdir=(outdir / "kicad-env").resolve())

    outdir.mkdir(parents=True, exist_ok=True)
    default_handler = skidl.empty_footprint_handler

    def footprint_handler(part: Any) -> None:
        # Power flags (#FLG) are virtual: no footprint, nothing on the PCB.
        if not part.ref.startswith("#"):
            default_handler(part)

    skidl.empty_footprint_handler = footprint_handler
    try:
        # do_backup would write a `<name>_sklib.py` part-library into the cwd; we
        # resolve parts from KiCad-Master-Lib every run, so we don't want it.
        skidl.generate_netlist(file_=str((outdir / "loaf.net").resolve()), do_backup=False)
    finally:
        skidl.empty_footprint_handler = default_handler
    with _in_dir(outdir):
        # Every net on this board fans out well past the routing threshold, so
        # the bus is expressed as labels (and GND/+12V as power symbols) rather
        # than drawn wires — the natural representation for a backplane, and the
        # physical layout is pkidl's job, not the schematic's. Placement and
        # routing are randomised; a fixed seed removes that source, but at the
        # pinned SKiDL placement still varies between processes (F-016). The
        # netlist is unaffected and is what the tests gate.
        skidl.generate_schematic(filepath=".", top_name="loaf", auto_stub=True, seed=0)

    pad_nets: dict[str, dict[str, str]] = {}
    fields: dict[str, dict[str, str]] = {}
    for name, net in nets.items():
        for p in net.pins:
            part = p.part
            if part.ref.startswith("#"):
                continue
            pad_nets.setdefault(part.ref, {})[str(p.num)] = name
            # KiCad reads a "~" datasheet as empty.
            datasheet = part.datasheet if part.datasheet not in (None, "~") else ""
            fields[part.ref] = {"Datasheet": datasheet, "Description": part.description or ""}
    loaf_layout.build_pcb(outdir, "loaf", pad_nets, fields, source or _source_id())
    return outdir


def _source_id() -> str:
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


def main() -> int:
    outdir = build()
    print(f"Generated Loaf into {outdir}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
