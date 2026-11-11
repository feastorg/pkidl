"""Generate Slice_RLHT — the BREAD dual relay heater controller with thermocouple feedback.

An Arduino Nano on the slice bus drives two opto-isolated relays, each switching
a fused heater line, and reads two K-type thermocouples through MAX31855K
front ends. A buck converter makes 5 V from the bus's 12 V; a WS2812 shows status.

The relay and thermocouple circuits are each one parametric subcircuit,
instantiated twice — the hierarchy the hand-drawn board expresses as two sheets
of two instances each. Every net is named, so the board's pad nets and KiCad's
reading of the schematic agree by construction.

Reference designators follow the original (feastorg/Slice_RLHT@a7308f3), so the
generated circuit compares against KiCad's export of it part for part
(`tests/test_rlht.py`). Deliberate differences from the original:

- SW1/SW2, the off-board E-stop switches, are left out. The original marks them
  on_board/in_bom no; SKiDL cannot (it writes every symbol on_board yes).
  Each one bridges its channel's LINE and ESTOP terminal nets off the board.
- D1's symbol is KMLib_IC_Digital:WS2812B_5050_RGB_LED, the first-party copy of
  the vendored SparkFun-LED:WS2812B_5050 (same pins, same footprint).
- U1's value is its part number; the original leaves it empty ("~").
- The mounting holes H1–H4 are board-only footprints, placed by the layout, not
  schematic symbols: a pinless part crashes SKiDL's schematic placer (F-019).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from kidl_spike.boards.blocks import build_circuit
from kidl_spike.boards.common import generate
from kidl_spike.boards.spec import load

BUILD = Path("build/rlht")


# The composition, from rlht.yaml: per channel, reference designators, the Nano pin that
# drives the relay or selects the converter, and where the block goes.
SPEC = load("rlht")
RELAYS = SPEC.channels("relay")
THERMOCOUPLES = SPEC.channels("thermocouple")


def circuit(workdir: Path | None = None) -> dict[str, Any]:
    """Build the RLHT circuit into SKiDL's default circuit; return its nets by name."""
    return build_circuit(SPEC.circuit, workdir)


def build(outdir: Path = BUILD, source: str | None = None) -> Path:
    """Build the RLHT into *outdir*: netlist, schematic, board and project.

    *source* is printed on the board's silkscreen to trace it back to the
    generating commit; it defaults to the current checkout's.
    Returns the directory the KiCad files were written to.
    """
    from kidl_spike.boards import rlht_layout

    # Absolute workdir so the materialised fp-lib-table survives the chdir below.
    nets = circuit(workdir=(outdir / "kicad-env").resolve())

    return generate(outdir, "rlht", nets, rlht_layout.build_pcb, source)


def main() -> int:
    outdir = build()
    print(f"Generated Slice_RLHT into {outdir}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
