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

from kidl_spike.boards.blocks import build_circuit
from kidl_spike.boards.common import generate
from kidl_spike.boards.spec import load

BUILD = Path("build/dcmt")

# The composition, from dcmt.yaml: per channel, reference designators, the Nano pins
# that drive and read it, and where the block goes.
SPEC = load("dcmt")
BRIDGES = SPEC.channels("bridge")
# Encoder terminals: (terminal, channel, Nano pin for A, for B).
ENCODERS = [(e["J"], e["ch"], e["a"], e["b"]) for e in SPEC.channels("encoder")]


def circuit(workdir: Path | None = None) -> dict[str, Any]:
    """Build the DCMT circuit into SKiDL's default circuit; return its nets by name."""
    return build_circuit(SPEC.circuit, workdir)


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
