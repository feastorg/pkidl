"""The Slices' circuit blocks, and one Slice circuit built from a list of them.

A Slice is the bus connector J1, an Arduino Nano (A1), the 12 V -> 5 V buck, the
status LED, optionally a net tie between logic and power ground, then its channels in
order, then PWR_FLAGs for the nets driven off the board. A channel is a block kind and
its parameters (reference designators, Nano pins).

Each block's circuit is a SKiDL subcircuit, defined once per build under the name the
schematic hierarchy shows (``relay``, ``max31855k``, ``bridge``). Parts are created in
a fixed order, so the same channels give the same netlist byte for byte.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kidl_spike import libs
from kidl_spike.boards.common import BUS_PINOUT, buck_5v, default_circuit, status_led

R1206 = "Resistor_SMD:R_1206_3216Metric_Pad1.30x1.75mm_HandSolder"
C1206_HS = "Capacitor_SMD:C_1206_3216Metric_Pad1.33x1.80mm_HandSolder"
C0603_HS = "Capacitor_SMD:C_0603_1608Metric_Pad1.08x0.95mm_HandSolder"
TERMINAL_2 = "TerminalBlock_4Ucon:TerminalBlock_4Ucon_1x02_P3.50mm_Horizontal"
TERMINAL_4 = "TerminalBlock_TE-Connectivity:TerminalBlock_TE_282834-4_1x04_P2.54mm_Horizontal"
RELAY_TERMINAL = (
    "TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-6-5.08_1x06_P5.08mm_Horizontal"
)
FUSE_CLIPS = "Fuse:Fuseholder_Clip-5x20mm_Bel_FC-203-22_Lateral_P17.80x5.00mm_D1.17mm_Horizontal"
TC_TERMINAL = "TerminalBlock_Phoenix:TerminalBlock_Phoenix_MPT-0,5-2-2.54_1x02_P2.54mm_Horizontal"


@dataclass(frozen=True)
class Channel:
    """One block instance: its kind (``relay``, ``thermocouple``, ``bridge``,
    ``encoder``) and parameters (reference designators by role, ``ch``, Nano pins)."""

    kind: str
    params: dict[str, Any]


@dataclass(frozen=True)
class SliceCircuit:
    """What a Nano Slice is made of, in the order its parts are created."""

    nano_pins: dict[int, str]  # Nano pin -> net, for the bus and shared nets
    nano_unused: list[int]
    buck_value: str
    channels: list[Channel]
    ground: str = "GND"  # the net the bus's GND pins carry
    bus_value: str | None = None
    net_tie: bool = False  # NT1 between GND and the bus ground
    pwr_flags: tuple[str, ...] = ("+12V", "GND")


def build_circuit(spec: SliceCircuit, workdir: Path | None = None) -> dict[str, Any]:
    """Build *spec* into SKiDL's default circuit; return its nets by name."""
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

    subcircuits = _subcircuits(skidl, net, part)

    # The slice bus.
    bus_kw: dict[str, str] = {"value": spec.bus_value} if spec.bus_value else {}
    bus_kw["footprint"] = "Connector_PinSocket_2.54mm:PinSocket_1x10_P2.54mm_Horizontal"
    bus = part("Connector", "Conn_01x10_Socket", "J1", **bus_kw)
    for pin, name in BUS_PINOUT.items():
        net(spec.ground if name == "GND" else name).connect(bus[pin])

    nano = part("MCU_Module", "Arduino_Nano_v3.x", "A1", footprint="Module:Arduino_Nano")
    for pin, name in spec.nano_pins.items():
        net(name).connect(nano[pin])
    for pin in spec.nano_unused:
        nano[pin] += default_circuit().NC

    # 12 V -> 5 V buck and the status LED, as on every Nano Slice.
    buck_5v(part, net, value=spec.buck_value)
    status_led(part, net)

    if spec.net_tie:
        # Logic ground meets power ground at one point.
        tie = part("Device", "NetTie_2", "NT1", footprint="NetTie:NetTie-2_SMD_Pad2.0mm")
        net("GND").connect(tie[1])
        net(spec.ground).connect(tie[2])

    for channel in spec.channels:
        BLOCKS[channel.kind](channel.params, net, part, nano, subcircuits, spec.ground)

    # Power enters over the bus, whose pins are passive, so nothing on the board drives
    # it. PWR_FLAG tells ERC those nets are driven off-board.
    for i, name in enumerate(spec.pwr_flags, start=1):
        nets[name] += part("power", "PWR_FLAG", f"#FLG0{i}")[1]
    return nets


def _subcircuits(skidl: Any, net: Callable[[str], Any], part: Callable[..., Any]) -> dict[str, Any]:
    """The block subcircuits, defined once per build."""

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

    return {"relay": relay, "max31855k": max31855k, "bridge": bridge}


def _relay(r: dict, net: Any, part: Any, nano: Any, sub: dict, ground: str) -> None:
    ch = r["ch"]
    ctrl, com = net(f"{ch}_CTRL"), net(f"{ch}_COM")
    nano[r["ctrl"]] += ctrl
    sub["relay"](r, net("+12V"), net("GND"), ctrl, com, net(f"{ch}_NO"), net(f"{ch}_NC"))
    # Line in on terminal 1, through the fuse to the relay's common. Terminals 2 and 4
    # are the E-stop return; the off-board switch bridges 1 and 2.
    fuse = part("Device", "Fuse", r["F"], footprint=FUSE_CLIPS)
    term = part("Connector", "Screw_Terminal_01x06", r["J"], footprint=RELAY_TERMINAL)
    com += fuse[1]
    net(f"{ch}_LINE").connect(fuse[2], term[1])
    net(f"{ch}_ESTOP").connect(term[2], term[4])
    net("GND").connect(term[3])
    net(f"{ch}_NO").connect(term[5])
    net(f"{ch}_NC").connect(term[6])


def _thermocouple(t: dict, net: Any, part: Any, nano: Any, sub: dict, ground: str) -> None:
    ch = t["ch"]
    ss = net(f"{ch}_SS")
    nano[t["ss"]] += ss
    tp, tn = net(f"{ch}+"), net(f"{ch}-")
    sub["max31855k"](t, net("+5V"), net("GND"), ss, net("TC_CLK"), net("TC_DATA"), tp, tn)
    term = part("Connector", "Screw_Terminal_01x02", t["J"], footprint=TC_TERMINAL)
    tn += term[1]
    tp += term[2]


def _encoder(e: dict, net: Any, part: Any, nano: Any, sub: dict, ground: str) -> None:
    term = part("Connector", "Screw_Terminal_01x04", e["J"], footprint=TERMINAL_4)
    net(f"{e['ch']}_A").connect(nano[e["a"]], term[1])
    net(f"{e['ch']}_B").connect(nano[e["b"]], term[2])
    net("+5V").connect(term[3])
    net("GND").connect(term[4])


def _bridge(b: dict, net: Any, part: Any, nano: Any, sub: dict, ground: str) -> None:
    ctl = {sig: net(f"{b['ch']}_{sig}") for sig in b["pins"]}
    for sig, pin in b["pins"].items():
        nano[pin] += ctl[sig]
    sub["bridge"](b, net("+12V"), net(ground), ctl)


BLOCKS: dict[str, Callable[..., None]] = {
    "relay": _relay,
    "thermocouple": _thermocouple,
    "encoder": _encoder,
    "bridge": _bridge,
}
