"""Generate Slice_HBTC: a new Slice made from existing blocks.

One LMD18200 H-bridge channel, Slice_DCMT's, and two MAX31855K thermocouple channels,
Slice_RLHT's, on one Arduino Nano. Its composition is ``hbtc.yaml``: no reference is
listed there, so every one is generated. The motor current returns on the bus ground
(GNDPWR), tied to the logic ground at NT1, as on DCMT.

There is no original to compare against: the parity tests check the board against its
own schematic, and ERC/DRC judge it like the others.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from kidl_spike.boards.blocks import build_circuit
from kidl_spike.boards.common import generate
from kidl_spike.boards.spec import load

BUILD = Path("build/hbtc")

SPEC = load("hbtc")
BRIDGES = SPEC.channels("bridge")
THERMOCOUPLES = SPEC.channels("thermocouple")


def circuit(workdir: Path | None = None) -> dict[str, Any]:
    """Build the HBTC circuit into SKiDL's default circuit; return its nets by name."""
    return build_circuit(SPEC.circuit, workdir)


def build(outdir: Path = BUILD, source: str | None = None) -> Path:
    """Build the HBTC into *outdir*: netlist, schematic, board and project.

    *source* is printed on the board's silkscreen; it defaults to the current checkout's.
    Returns the directory the KiCad files were written to.
    """
    from kidl_spike.boards import hbtc_layout

    # Absolute workdir so the materialised fp-lib-table survives the chdir below.
    nets = circuit(workdir=(outdir / "kicad-env").resolve())
    return generate(outdir, "hbtc", nets, hbtc_layout.build_pcb, source)


def main() -> int:
    outdir = build()
    print(f"Generated Slice_HBTC into {outdir}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
