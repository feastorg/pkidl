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

from kidl_spike.boards.blocks import Channel, SliceCircuit, build_circuit
from kidl_spike.boards.common import generate

BUILD = Path("build/rlht")


# Per channel: reference designators, and the Nano pin that drives the relay or
# selects the thermocouple converter.
RELAYS = [
    {"ch": "CH1", "ctrl": 9, "D": "D2", "K": "K1", "R": "R5", "U": "U4", "F": "F1", "J": "J4"},
    {"ch": "CH2", "ctrl": 10, "D": "D3", "K": "K2", "R": "R6", "U": "U5", "F": "F2", "J": "J5"},
]
THERMOCOUPLES = [
    {"ch": "TC1", "ss": 16, "U": "U2", "C": "C5", "FBP": "FB1", "FBN": "FB2", "RCLK": "R1",
     "RSS": "R2", "J": "J2"},
    {"ch": "TC2", "ss": 14, "U": "U3", "C": "C6", "FBP": "FB3", "FBN": "FB4", "RCLK": "R3",
     "RSS": "R4", "J": "J3"},
]  # fmt: skip

# Nano pins on the bus and shared nets: pin number -> net name.
NANO_PINS = {
    4: "GND", 29: "GND", 27: "+5V",
    24: "SCL_5V", 23: "SDA_5V", 5: "E_STOP_5V", 6: "INT_5V", 7: "SYNC_5V",
    13: "TC_CLK", 15: "TC_DATA", 8: "LED",
}  # fmt: skip
NANO_UNUSED = [1, 2, 3, 11, 12, 17, 18, 19, 20, 21, 22, 25, 26, 28, 30]


def spec() -> SliceCircuit:
    """The RLHT's composition: two relay channels, then two thermocouple channels."""
    return SliceCircuit(
        nano_pins=NANO_PINS,
        nano_unused=NANO_UNUSED,
        buck_value="AP63205WU-7",
        channels=[Channel("relay", r) for r in RELAYS]
        + [Channel("thermocouple", t) for t in THERMOCOUPLES],
        bus_value="Conn_01x10_Female",
    )


def circuit(workdir: Path | None = None) -> dict[str, Any]:
    """Build the RLHT circuit into SKiDL's default circuit; return its nets by name."""
    return build_circuit(spec(), workdir)


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
