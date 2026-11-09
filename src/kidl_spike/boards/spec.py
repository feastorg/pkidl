"""Load a Slice's composition from ``boards/<name>.yaml``.

The YAML says what the board is made of: the Nano's pin map, the buck, the bus, and its
channels in order. Each channel names its block ``kind``, its channel name ``ch``, its
Nano pins, where the block goes (``anchor``, board mm; absent for parts the layout fixes)
and, optionally, its reference designators by role. A role left out gets the next free
designator for its prefix, after every reference the board already uses, in channel
order: so a new board needs no numbering, and an existing one can keep its original's.

Errors name the file and the key, e.g. ``rlht.yaml: channels[2].anchor: expected
[x, y]``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from kidl_spike.boards.blocks import Channel, SliceCircuit

HERE = Path(__file__).parent

# Each block's roles and the designator prefix of the part filling it, in the order the
# block creates them.
BLOCK_ROLES: dict[str, dict[str, str]] = {
    "relay": {"D": "D", "K": "K", "R": "R", "U": "U", "F": "F", "J": "J"},
    "thermocouple": {"U": "U", "C": "C", "FBP": "FB", "FBN": "FB", "RCLK": "R", "RSS": "R",
                     "J": "J"},
    "bridge": {"U": "U", "CBULK": "C", "CVS": "C", "CSNS": "C", "CB1": "C", "CB2": "C",
               "R": "R", "S": "S", "JVDC": "J", "JOUT": "J"},
    "encoder": {"J": "J"},
}  # fmt: skip
# Each block's Nano pin keys: one pin each, or ("pins", names) for a map of named pins.
BLOCK_PINS: dict[str, tuple[str, ...]] = {
    "relay": ("ctrl",),
    "thermocouple": ("ss",),
    "bridge": ("pins",),
    "encoder": ("a", "b"),
}
BRIDGE_PINS = ("DIR", "BRAKE", "PWM", "CSENS", "THRM")
# Every Nano Slice's root parts: the bus, the Nano, the buck and its heatsink pad, the
# status LED, the net tie, and the mounting holes.
ROOT_REFS = frozenset({"J1", "A1", "U1", "C1", "C2", "C3", "C4", "L1", "HS1", "D1", "NT1",
                       "H1", "H2", "H3", "H4"})  # fmt: skip


class SpecError(ValueError):
    pass


@dataclass(frozen=True)
class BoardSpec:
    name: str
    circuit: SliceCircuit
    anchors: dict[str, tuple[float, float]]  # channel name -> block anchor

    def channels(self, kind: str) -> list[dict[str, Any]]:
        """The parameters of every channel of *kind*, in board order."""
        return [c.params for c in self.circuit.channels if c.kind == kind]


def load(name: str, directory: Path = HERE) -> BoardSpec:
    path = directory / f"{name}.yaml"
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as e:
        raise SpecError(f"{path.name}: {e}") from e
    return parse(data, path.name)


def parse(data: Any, where: str) -> BoardSpec:
    def fail(key: str, msg: str) -> SpecError:
        return SpecError(f"{where}: {key}: {msg}")

    def need(obj: Any, key: str, kind: type | tuple[type, ...], at: str) -> Any:
        if not isinstance(obj, dict) or key not in obj:
            raise fail(f"{at}{key}", "missing")
        if not isinstance(obj[key], kind):
            raise fail(f"{at}{key}", f"expected {getattr(kind, '__name__', kind)}")
        return obj[key]

    nano = need(data, "nano", dict, "")
    pins = need(nano, "pins", dict, "nano.")
    if not all(isinstance(k, int) and isinstance(v, str) for k, v in pins.items()):
        raise fail("nano.pins", "expected {pin number: net name}")
    unused = need(nano, "unused", list, "nano.")
    raw = need(data, "channels", list, "")

    used = set(ROOT_REFS)
    for c in raw:
        refs = c.get("refs", {}) if isinstance(c, dict) else {}
        used |= set(refs.values()) if isinstance(refs, dict) else set()
    counters: dict[str, int] = {}

    def next_ref(prefix: str) -> str:
        n = counters.get(prefix, 0)
        while True:
            n += 1
            if f"{prefix}{n}" not in used:
                counters[prefix] = n
                used.add(f"{prefix}{n}")
                return f"{prefix}{n}"

    channels: list[Channel] = []
    anchors: dict[str, tuple[float, float]] = {}
    names: set[str] = set()
    for i, c in enumerate(raw):
        at = f"channels[{i}]."
        kind = need(c, "kind", str, at)
        if kind not in BLOCK_ROLES:
            raise fail(f"{at}kind", f"unknown block {kind!r}; one of {sorted(BLOCK_ROLES)}")
        ch = need(c, "ch", str, at)
        if ch in names:
            raise fail(f"{at}ch", f"{ch!r} repeats")
        names.add(ch)
        params: dict[str, Any] = {"ch": ch}
        for key in BLOCK_PINS[kind]:
            if key == "pins":
                pinmap = need(c, "pins", dict, at)
                if set(pinmap) != set(BRIDGE_PINS) or not all(
                    isinstance(v, int) for v in pinmap.values()
                ):
                    raise fail(
                        f"{at}pins", f"expected a pin number for each of {list(BRIDGE_PINS)}"
                    )
                params["pins"] = {k: pinmap[k] for k in BRIDGE_PINS}
            else:
                params[key] = need(c, key, int, at)
        given = c.get("refs", {})
        if not isinstance(given, dict) or set(given) - set(BLOCK_ROLES[kind]):
            raise fail(f"{at}refs", f"expected roles from {list(BLOCK_ROLES[kind])}")
        for role, prefix in BLOCK_ROLES[kind].items():
            ref = given.get(role) or next_ref(prefix)
            if not re.fullmatch(rf"{prefix}\d+", ref):
                raise fail(f"{at}refs.{role}", f"{ref!r} is not a {prefix} designator")
            params[role] = ref
        if "anchor" in c:
            anchor = c["anchor"]
            if not (isinstance(anchor, list) and len(anchor) == 2
                    and all(isinstance(v, (int, float)) for v in anchor)):  # fmt: skip
                raise fail(f"{at}anchor", "expected [x, y]")
            anchors[ch] = (float(anchor[0]), float(anchor[1]))
        channels.append(Channel(kind, params))

    circuit = SliceCircuit(
        nano_pins=pins,
        nano_unused=unused,
        buck_value=need(data, "buck", str, ""),
        channels=channels,
        ground=data.get("ground", "GND"),
        bus_value=data.get("bus_value"),
        net_tie=bool(data.get("net_tie", False)),
        pwr_flags=tuple(data.get("pwr_flags", ("+12V", "GND"))),
    )
    return BoardSpec(name=need(data, "name", str, ""), circuit=circuit, anchors=anchors)
