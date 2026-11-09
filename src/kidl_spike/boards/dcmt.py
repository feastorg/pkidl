"""Generate Slice_DCMT — the BREAD dual DC motor controller.

An Arduino Nano on the slice bus drives two LMD18200 H-bridges. Each bridge's
supply (VS) is chosen by a slide switch: the bus's 12 V, or an external supply
on its own terminal (VDC). Two 4-way terminals take quadrature encoders. A buck
converter makes 5 V from the bus's 12 V; a WS2812 shows status.

Two grounds: GNDPWR carries the bridges' current and is the bus ground; GND is
the logic ground. A net tie (NT1) joins them at one point.

The bridge circuit is one parametric subcircuit, instantiated twice — the
hierarchy the hand-drawn board expresses as one sheet used twice. Every net is
named, so the board's pad nets and KiCad's reading of the schematic agree by
construction.

Reference designators follow the original (feastorg/Slice_DCMT@b32e3b2), so the
generated circuit compares against KiCad's export of it part for part
(`tests/test_dcmt.py`). Deliberate differences from the original:

- M1/M2, the off-board motors, are left out. The original marks them
  on_board/in_bom no; SKiDL cannot (it writes every symbol on_board yes).
- NT1, the net tie, is in the BOM: the original excludes it, SKiDL writes every
  symbol in_bom yes, and parity needs the footprint to agree.
- The mounting holes H1-H4 are board-only footprints, placed by the layout, not
  schematic symbols: a pinless part crashes SKiDL's schematic placer (F-019).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from kidl_spike.boards.blocks import Channel, SliceCircuit, build_circuit
from kidl_spike.boards.common import generate

BUILD = Path("build/dcmt")

# Per channel: reference designators, and the Nano pins that drive and read the
# bridge.
BRIDGES = [
    {"ch": "CH1", "U": "U2", "CBULK": "C5", "CVS": "C7", "CSNS": "C6", "CB1": "C8", "CB2": "C9",
     "R": "R1", "S": "S1", "JVDC": "J4", "JOUT": "J5",
     "pins": {"DIR": 14, "BRAKE": 15, "PWM": 13, "CSENS": 26, "THRM": 16}},
    {"ch": "CH2", "U": "U3", "CBULK": "C10", "CVS": "C12", "CSNS": "C11", "CB1": "C13",
     "CB2": "C14", "R": "R2", "S": "S2", "JVDC": "J6", "JOUT": "J7",
     "pins": {"DIR": 10, "BRAKE": 11, "PWM": 9, "CSENS": 25, "THRM": 12}},
]  # fmt: skip

# Encoder terminals: A, B, +5V, GND, with the Nano pins for A and B.
ENCODERS = [("J2", "ENC1", 20, 19), ("J3", "ENC2", 22, 21)]

# Nano pins on the bus and shared nets: pin number -> net name.
NANO_PINS = {
    4: "GND", 29: "GND", 27: "+5V",
    24: "SCL_5V", 23: "SDA_5V", 5: "E_STOP_5V", 6: "INT_5V", 7: "SYNC_5V", 8: "LED",
}  # fmt: skip
NANO_UNUSED = [1, 2, 3, 17, 18, 28, 30]


def spec() -> SliceCircuit:
    """The DCMT's composition: the net tie, two encoders, then two H-bridges."""
    return SliceCircuit(
        nano_pins=NANO_PINS,
        nano_unused=NANO_UNUSED,
        buck_value="AP63205",
        channels=[
            Channel("encoder", {"J": j, "ch": ch, "a": a, "b": b}) for j, ch, a, b in ENCODERS
        ]
        + [Channel("bridge", b) for b in BRIDGES],  # fmt: skip
        ground="GNDPWR",
        net_tie=True,
        # ERC treats the two sides of the net tie as separate nets, so GND needs one.
        pwr_flags=("+12V", "GNDPWR", "GND"),
    )


def circuit(workdir: Path | None = None) -> dict[str, Any]:
    """Build the DCMT circuit into SKiDL's default circuit; return its nets by name."""
    return build_circuit(spec(), workdir)


def build(outdir: Path = BUILD, source: str | None = None) -> Path:
    """Build the DCMT into *outdir*: netlist, schematic, board and project.

    *source* is printed on the board's silkscreen to trace it back to the
    generating commit; it defaults to the current checkout's.
    Returns the directory the KiCad files were written to.
    """
    from kidl_spike.boards import dcmt_layout

    # Absolute workdir so the materialised fp-lib-table survives the chdir below.
    nets = circuit(workdir=(outdir / "kicad-env").resolve())
    return generate(outdir, "dcmt", nets, dcmt_layout.build_pcb, source)


def main() -> int:
    outdir = build()
    print(f"Generated Slice_DCMT into {outdir}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
