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

from kidl_spike import libs
from kidl_spike.boards.common import (
    BUS_PINOUT,
    buck_5v,
    default_circuit,
    generate,
    status_led,
)

BUILD = Path("build/dcmt")

R1206 = "Resistor_SMD:R_1206_3216Metric_Pad1.30x1.75mm_HandSolder"
C1206_HS = "Capacitor_SMD:C_1206_3216Metric_Pad1.33x1.80mm_HandSolder"
C0603_HS = "Capacitor_SMD:C_0603_1608Metric_Pad1.08x0.95mm_HandSolder"
TERMINAL_2 = "TerminalBlock_4Ucon:TerminalBlock_4Ucon_1x02_P3.50mm_Horizontal"
TERMINAL_4 = "TerminalBlock_TE-Connectivity:TerminalBlock_TE_282834-4_1x04_P2.54mm_Horizontal"

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

# The bus ground is the power ground on this board.
BUS_NETS = {pin: ("GNDPWR" if name == "GND" else name) for pin, name in BUS_PINOUT.items()}

# Nano pins on the bus and shared nets: pin number -> net name.
NANO_PINS = {
    4: "GND", 29: "GND", 27: "+5V",
    24: "SCL_5V", 23: "SDA_5V", 5: "E_STOP_5V", 6: "INT_5V", 7: "SYNC_5V", 8: "LED",
}  # fmt: skip
NANO_UNUSED = [1, 2, 3, 17, 18, 28, 30]


def circuit(workdir: Path | None = None) -> dict[str, Any]:
    """Build the DCMT circuit into SKiDL's default circuit; return its nets by name."""
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
    def bridge(b: dict, v12: Any, gndpwr: Any, ctl: dict[str, Any]) -> None:
        """LMD18200 H-bridge: switched supply, bootstrap caps, current sense, terminals."""
        ch = b["ch"]
        vs, vdc = net(f"{ch}_VS"), net(f"{ch}_VDC")
        out1, out2 = net(f"{ch}_OUT1"), net(f"{ch}_OUT2")
        boot1, boot2 = net(f"{ch}_BOOT1"), net(f"{ch}_BOOT2")
        u = part("Driver_Motor", "LMD18200", b["U"], value="LMD18200T_NOPB", footprint=(
            "KMLib_IC_THT:TO-220-11_P3.4x5.08mm_StaggerOdd_Lead8.45mm_TabDown"
        ))  # fmt: skip
        c_bulk = part("Device", "C_Polarized", b["CBULK"], value="220uF_T",
                      footprint="Capacitor_THT:CP_Radial_D10.0mm_P5.00mm")  # fmt: skip
        c_vs = part("Device", "C", b["CVS"], value="1u", footprint=C1206_HS)
        c_sns = part("Device", "C", b["CSNS"], value="1u", footprint=C1206_HS)
        c_b1 = part("Device", "C", b["CB1"], value="10n", footprint=C0603_HS)
        c_b2 = part("Device", "C", b["CB2"], value="10n", footprint=C0603_HS)
        r_sns = part("Device", "R", b["R"], value="4.42k", footprint=R1206)
        sw = part("KMLib_Switches", "1101M2S3CQE2", b["S"],
                  footprint="KMLib_Switches:SW_Slide-CK-1101M2S3CQE2")  # fmt: skip
        j_vdc = part("Connector", "Screw_Terminal_01x02", b["JVDC"], footprint=TERMINAL_2)
        j_out = part("Connector", "Screw_Terminal_01x02", b["JOUT"], footprint=TERMINAL_2)
        # VS comes from the bus (switch pin 1) or the external terminal (pin 3).
        v12 += sw[1]
        vs += sw[2], u[6], c_bulk[1], c_vs[1]
        vdc += sw[3], j_vdc[2]
        gndpwr += u[7], c_bulk[2], c_vs[2], c_sns[2], r_sns[2], j_vdc[1]
        out1 += u[2], c_b1[1], j_out[1]
        out2 += u[10], c_b2[2], j_out[2]
        boot1 += u[1], c_b1[2]
        boot2 += u[11], c_b2[1]
        ctl["DIR"] += u[3]
        ctl["BRAKE"] += u[4]
        ctl["PWM"] += u[5]
        ctl["CSENS"] += u[8], r_sns[1], c_sns[1]
        ctl["THRM"] += u[9]
        # VS reaches the bridge through the passive switch, from the bus or the
        # external terminal; ERC cannot see that it is driven.
        vs += part("power", "PWR_FLAG", f"#FLG1{ch[-1]}")[1]

    # The slice bus.
    bus = part(
        "Connector",
        "Conn_01x10_Socket",
        "J1",
        footprint="Connector_PinSocket_2.54mm:PinSocket_1x10_P2.54mm_Horizontal",
    )
    for pin, name in BUS_NETS.items():
        net(name).connect(bus[pin])

    nano = part("MCU_Module", "Arduino_Nano_v3.x", "A1", footprint="Module:Arduino_Nano")
    for pin, name in NANO_PINS.items():
        net(name).connect(nano[pin])
    for pin in NANO_UNUSED:
        nano[pin] += default_circuit().NC

    # 12 V -> 5 V buck and the status LED, as on every Nano Slice.
    buck_5v(part, net, value="AP63205")
    status_led(part, net)

    # Logic ground meets power ground at one point.
    tie = part("Device", "NetTie_2", "NT1", footprint="NetTie:NetTie-2_SMD_Pad2.0mm")
    net("GND").connect(tie[1])
    net("GNDPWR").connect(tie[2])

    for ref, ch, pin_a, pin_b in ENCODERS:
        term = part("Connector", "Screw_Terminal_01x04", ref, footprint=TERMINAL_4)
        net(f"{ch}_A").connect(nano[pin_a], term[1])
        net(f"{ch}_B").connect(nano[pin_b], term[2])
        net("+5V").connect(term[3])
        net("GND").connect(term[4])

    for b in BRIDGES:
        ctl = {sig: net(f"{b['ch']}_{sig}") for sig in b["pins"]}
        for sig, pin in b["pins"].items():
            nano[pin] += ctl[sig]
        bridge(b, net("+12V"), net("GNDPWR"), ctl)

    # Power enters over the bus, whose pins are passive, so nothing on the board
    # drives +12V or GNDPWR. PWR_FLAG tells ERC they are driven off-board. ERC
    # also treats the two sides of the net tie as separate nets, so GND needs one.
    for i, name in enumerate(("+12V", "GNDPWR", "GND"), start=1):
        nets[name] += part("power", "PWR_FLAG", f"#FLG0{i}")[1]

    return nets


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
