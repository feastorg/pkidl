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

from kidl_spike import libs
from kidl_spike.boards.common import (
    BUS_PINOUT,
    buck_5v,
    default_circuit,
    generate,
    status_led,
)

BUILD = Path("build/rlht")


R1206 = "Resistor_SMD:R_1206_3216Metric_Pad1.30x1.75mm_HandSolder"
C1206_HS = "Capacitor_SMD:C_1206_3216Metric_Pad1.33x1.80mm_HandSolder"

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


def circuit(workdir: Path | None = None) -> dict[str, Any]:
    """Build the RLHT circuit into SKiDL's default circuit; return its nets by name."""
    import skidl

    skidl.reset()  # start from an empty circuit, so repeated builds don't accumulate
    # Resolve libraries from the committed tables, never the global KiCad config.
    libs.configure_skidl(workdir=workdir)

    nets: dict[str, Any] = {}

    def net(name: str) -> Any:
        if name not in nets:
            nets[name] = skidl.Net(name)
        return nets[name]

    def part(lib: str, sym: str, ref: str, **kw: Any) -> Any:
        # A fixed tag keeps SKiDL's generated UUIDs stable from run to run.
        return skidl.Part(lib, sym, ref=ref, tag=ref, **kw)

    @skidl.subcircuit
    def relay(r: dict, v12: Any, gnd: Any, ctrl: Any, com: Any, no: Any, nc: Any) -> None:
        """Opto-driven SPDT relay: ctrl lights the opto, which sinks the coil."""
        coil, led = net(f"{r['ch']}_COIL"), net(f"{r['ch']}_LED")
        d = part("Device", "D", r["D"], footprint="Diode_THT:D_DO-35_SOD27_P7.62mm_Horizontal")
        k = part("Relay", "G5Q-1", r["K"], footprint="Relay_THT:Relay_SPDT_Omron-G5Q-1")
        res = part("Device", "R", r["R"], value="180", footprint=R1206)
        u = part("Isolator", "TCMT1100", r["U"], footprint="Package_SO:SOP-4_4.4x2.6mm_P1.27mm")
        v12 += d[1], k[5]
        coil += d[2], k[1], u[4]
        com += k[2]
        no += k[3]
        nc += k[4]
        ctrl += res[1]
        led += res[2], u[1]
        gnd += u[2], u[3]

    @skidl.subcircuit
    def max31855k(
        t: dict, v5: Any, gnd: Any, ss: Any, clk: Any, data: Any, tp: Any, tn: Any
    ) -> None:
        """Thermocouple front end: ferrite-filtered inputs, pulled-up CS and SCK."""
        in_p, in_n = net(f"{t['ch']}_IN+"), net(f"{t['ch']}_IN-")
        u = part("Sensor_Temperature", "MAX31855KASA", t["U"],
                 footprint="Package_SO:SOIC-8_3.9x4.9mm_P1.27mm")  # fmt: skip
        c = part("Device", "C", t["C"], value="10n", footprint=C1206_HS)
        fb_p = part("Device", "FerriteBead_Small", t["FBP"], value="Ferrite_Bead_Small",
                    footprint=R1206)  # fmt: skip
        fb_n = part("Device", "FerriteBead_Small", t["FBN"], value="Ferrite_Bead_Small",
                    footprint=R1206)  # fmt: skip
        r_clk = part("Device", "R", t["RCLK"], value="10k", footprint=R1206)
        r_ss = part("Device", "R", t["RSS"], value="10k", footprint=R1206)
        v5 += r_clk[1], r_ss[2], u[4]
        gnd += u[1]
        ss += r_ss[1], u[6]
        clk += r_clk[2], u[5]
        data += u[7]
        in_p += c[1], fb_p[1], u[3]
        in_n += c[2], fb_n[1], u[2]
        tp += fb_p[2]
        tn += fb_n[2]
        u[8] += default_circuit().NC

    # The slice bus.
    bus = part(
        "Connector",
        "Conn_01x10_Socket",
        "J1",
        value="Conn_01x10_Female",
        footprint="Connector_PinSocket_2.54mm:PinSocket_1x10_P2.54mm_Horizontal",
    )
    for pin, name in BUS_PINOUT.items():
        net(name).connect(bus[pin])

    nano = part("MCU_Module", "Arduino_Nano_v3.x", "A1", footprint="Module:Arduino_Nano")
    for pin, name in NANO_PINS.items():
        net(name).connect(nano[pin])
    for pin in NANO_UNUSED:
        nano[pin] += default_circuit().NC

    # 12 V -> 5 V buck and the status LED, as on every Nano Slice.
    buck_5v(part, net, value="AP63205WU-7")
    status_led(part, net)

    for r in RELAYS:
        ch = r["ch"]
        ctrl, com = net(f"{ch}_CTRL"), net(f"{ch}_COM")
        nano[r["ctrl"]] += ctrl
        relay(r, net("+12V"), net("GND"), ctrl, com, net(f"{ch}_NO"), net(f"{ch}_NC"))
        # Line in on terminal 1, through the fuse to the relay's common. Terminals
        # 2 and 4 are the E-stop return; the off-board switch bridges 1 and 2.
        fuse = part("Device", "Fuse", r["F"], footprint=(
            "Fuse:Fuseholder_Clip-5x20mm_Bel_FC-203-22_Lateral_P17.80x5.00mm_D1.17mm_Horizontal"
        ))  # fmt: skip
        term = part("Connector", "Screw_Terminal_01x06", r["J"], footprint=(
            "TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-6-5.08_1x06_P5.08mm_Horizontal"
        ))  # fmt: skip
        com += fuse[1]
        net(f"{ch}_LINE").connect(fuse[2], term[1])
        net(f"{ch}_ESTOP").connect(term[2], term[4])
        net("GND").connect(term[3])
        net(f"{ch}_NO").connect(term[5])
        net(f"{ch}_NC").connect(term[6])

    for t in THERMOCOUPLES:
        ch = t["ch"]
        ss = net(f"{ch}_SS")
        nano[t["ss"]] += ss
        tp, tn = net(f"{ch}+"), net(f"{ch}-")
        max31855k(t, net("+5V"), net("GND"), ss, net("TC_CLK"), net("TC_DATA"), tp, tn)
        term = part("Connector", "Screw_Terminal_01x02", t["J"], footprint=(
            "TerminalBlock_Phoenix:TerminalBlock_Phoenix_MPT-0,5-2-2.54_1x02_P2.54mm_Horizontal"
        ))  # fmt: skip
        tn += term[1]
        tp += term[2]

    # Power enters over the bus, whose pins are passive, so nothing on the board
    # drives +12V or GND. PWR_FLAG tells ERC they are driven off-board.
    for i, name in enumerate(("+12V", "GND"), start=1):
        nets[name] += part("power", "PWR_FLAG", f"#FLG0{i}")[1]

    return nets


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
