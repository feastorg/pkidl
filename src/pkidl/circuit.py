"""The circuit a board is laid out for: its parts, their pins and its nets, as objects.

The circuit is input, as ``circuit.json`` holds it, and layout never edits it. A board
file refers to it through handles, each identified by what the netlist calls it: a part
by its reference, a pin by its part and number, a net by its name. Two handles for the
same thing are equal, whichever board they came from.

What a board file declares about the circuit is kept beside it: which nets are rails,
and which of those are grounds,
names for nets the schematic left anonymous, the named areas of a footprint that its
annotation marks out, and names for a part's pins.

Anything plural is a method that selects, and gives everything when asked for nothing
(``board.parts()``, ``part.pins()``, ``net.pins()``); anything singular is an attribute.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

Selector = Callable[["Part"], bool]
Box = tuple[int, int, int, int]  # x0, y0, x1, y1, in nanometres


def natural(ref: str) -> tuple:
    """A key that sorts references as people read them: R2 before R10."""
    return tuple(int(t) if t.isdigit() else t for t in re.split(r"(\d+)", ref))


@dataclass(frozen=True)
class Net:
    """A net, by the name the circuit gives it. ``str(net)`` is the name the board file
    gave it with ``name_nets``, where it gave one."""

    name: str
    circuit: Circuit = field(repr=False, compare=False)

    def __str__(self) -> str:
        return self.circuit._given.get(self.name, self.name)

    @property
    def is_rail(self) -> bool:
        self.circuit._rails_read = self.circuit._rails_read or f"{self}.is_rail"
        return self.name in self.circuit._rails

    @property
    def is_ground(self) -> bool:
        """Whether the board file said this net is a ground, with ``ground``."""
        return self.name in self.circuit._grounds

    def pins(self) -> tuple[Pin, ...]:
        """The pins on this net: part by part, each part's in its footprint's order."""
        return tuple(pin for part in self.circuit.parts() for pin in part.pins()
                     if pin.net == self)  # fmt: skip

    def parts(self) -> tuple[Part, ...]:
        """The parts with a pin on this net."""
        return tuple(dict.fromkeys(pin.part for pin in self.pins()))


@dataclass(frozen=True)
class Pin:
    """A pin of a part, by its number: the footprint's pad number, or the pads that
    share it."""

    part: Part
    number: str

    def __str__(self) -> str:
        return f"{self.part.ref}.{self.number}"

    @property
    def net(self) -> Net | None:
        """The net it is on, or None for a pin that is on none."""
        name = self.part.circuit._parts[self.part.ref]["pads"].get(self.number)
        return None if name is None else Net(name, self.part.circuit)


@dataclass(frozen=True)
class Area:
    """A named area of a part's footprint, such as a module's antenna."""

    part: Part
    name: str

    def __str__(self) -> str:
        return f'{self.part.ref}.area("{self.name}")'

    @property
    def box(self) -> Box:
        """Its corners in the footprint's own coordinates."""
        return self.part.circuit._areas[self.part.footprint][self.name]


@dataclass(frozen=True)
class Part:
    """A part, by its reference."""

    ref: str
    circuit: Circuit = field(repr=False, compare=False)

    def __str__(self) -> str:
        return self.ref

    @property
    def value(self) -> str:
        return self.circuit._parts[self.ref]["value"]

    @property
    def footprint(self) -> str:
        """Its footprint's name, as a footprint library has it: ``library:footprint``."""
        return self.circuit._parts[self.ref]["footprint"]

    def pin(self, number: int | str) -> Pin:
        """Its pin with this number, or with this name where the board file named its
        pins: ``driver.pin("B")``."""
        numbers, names = self.circuit._pins[self.ref], self.circuit._names.get(self.ref, {})
        found = str(number) if str(number) in numbers else names.get(str(number))
        if found is None:
            if str(number).isdigit():
                why = ""  # a number the part has not got: its names are no answer
            elif names:
                why = f": its pins are named {', '.join(names)}"
            else:
                why = ": name its pins with annotate(pins=)"
            raise LookupError(f"{self.ref} has no pin {number}{why}")
        return Pin(self, found)

    def pins(self, *numbers: int | str) -> tuple[Pin, ...]:
        """The pins numbered or named, in the order given; with none, all of them, in
        the footprint's order."""
        return tuple(self.pin(n) for n in numbers or self.circuit._pins[self.ref])

    def side(self, name: str) -> str:
        """The side of its footprint that goes by *name*, as the footprint is drawn:
        ``left``, ``right``, ``top`` or ``bottom``."""
        sides = self.circuit._sides.get(self.footprint, {})
        if name not in sides:
            why = (f"its footprint {self.footprint!r} has {', '.join(sides)}" if sides else
                   f"name it with annotate(sides={{{name!r}: Edge.LEFT}}), by the side of its "
                   f"footprint {self.footprint!r} it is as the footprint is drawn")  # fmt: skip
            raise LookupError(f"{self.ref} has no side {name!r}: {why}")
        return sides[name]

    @property
    def way_up_matters(self) -> bool:
        """Whether which way round it is is the board file's to say and never chosen: a
        part annotated ``oriented=True``, or with a side named for it."""
        return self.ref in self.circuit._oriented

    def area(self, name: str) -> Area:
        """A named area of its footprint, as the footprint's annotation marks it out:
        ``u1.area("antenna")``."""
        areas = self.circuit._areas.get(self.footprint, {})
        if name not in areas:
            if areas:
                why = f"its footprint {self.footprint!r} has {', '.join(areas)}"
            elif self.footprint in self.circuit.unfitted:
                why = (f"the annotation that ships for {self.footprint.rpartition(':')[2]} "
                       f"is not of its footprint {self.footprint!r}: "
                       f"{self.circuit.unfitted[self.footprint]}")  # fmt: skip
            else:
                why = (f"its footprint {self.footprint!r} has no annotation: say where the "
                       "area is with annotate()")  # fmt: skip
            raise LookupError(f"{self.ref} has no area {name!r}: {why}")
        return Area(self, name)

    def nets(self) -> tuple[Net, ...]:
        """The nets its pins are on, each once, in pin order."""
        return tuple(dict.fromkeys(pin.net for pin in self.pins() if pin.net is not None))

    def pin_on(self, net: Net | str) -> Pin:
        """The pin of this part that is on *net*. A part with several is asked by number."""
        net = self.circuit.net(net)
        on = [pin for pin in self.pins() if pin.net == net]
        if not on:
            raise LookupError(f"{self.ref} has no pin on {net}")
        if len(on) > 1:
            numbers = ", ".join(p.number for p in on)
            raise ValueError(f"{self.ref} has {len(on)} pins on {net} ({numbers}): "
                             "say which with pin()")  # fmt: skip
        return on[0]

    @property
    def signal_net(self) -> Net:
        """The one net of this part that is not a rail: what a pull-up, a series resistor
        or a decoupling capacitor is there for. Rails are what ``rails`` declared."""
        signals = [net for net in self.nets() if net.name not in self.circuit._rails]
        if len(signals) == 1:
            self.circuit._rails_read = self.circuit._rails_read or f"{self.ref}.signal_net"
            return signals[0]
        found = ", ".join(map(str, signals)) or "none"
        hint = "" if self.circuit._rails else "; no rails are declared: say which with rails()"
        raise ValueError(f"{self.ref} has no one signal net: of its nets, those that are "
                         f"not rails are {found}{hint}")  # fmt: skip


def on_net(net: Net | str) -> Selector:
    """Selects the parts with a pin on *net*."""
    return lambda part: part.circuit.net(net) in part.nets()


def where(*, value: str | None = None, footprint: str | None = None) -> Selector:
    """Selects the parts with this value, this footprint name, or both."""
    return lambda part: (
        (value is None or part.value == value)
        and (footprint is None or part.footprint == footprint)
    )


class Circuit:
    """Parts and nets as ``circuit.json`` holds them (*data*), which stays as it was, and
    what the board file declares about them.

    *pads* gives each footprint name's pad numbers, so that a pin on no net is still a
    pin; without it a part's pins are the ones on a net.
    """

    def __init__(
        self,
        data: Mapping[str, Any] | None = None,
        pads: Mapping[str, Sequence[str]] | None = None,
    ) -> None:
        self.data: Mapping[str, Any] = data or {"parts": [], "nets": []}
        self._parts: dict[str, Mapping[str, Any]] = {}
        self._pins: dict[str, tuple[str, ...]] = {}
        nets = set(self.data["nets"])
        for part in sorted(self.data["parts"], key=lambda p: natural(p["ref"])):
            ref = part["ref"]
            if ref in self._parts:
                raise ValueError(f"{ref} is in the circuit twice")
            if unknown := sorted(set(part["pads"].values()) - nets):
                raise ValueError(f"{ref} is on {', '.join(unknown)}, not a net of the circuit")
            self._parts[ref] = part
            numbers = part["pads"] if pads is None else pads[part["footprint"]]
            self._pins[ref] = tuple(dict.fromkeys(n for n in numbers if n))
        self._rails: set[str] = set()
        self._grounds: set[str] = set()
        self._rails_read: str | None = None  # the first thing that asked what a rail is
        self._given: dict[str, str] = {}  # the circuit's name for a net -> the board file's
        self._areas: dict[str, dict[str, Box]] = {}  # footprint name -> area name -> box
        self._names: dict[str, dict[str, str]] = {}  # reference -> pin name -> number
        # footprint name -> the name of a side of it -> which side, as it is drawn
        self._sides: dict[str, dict[str, str]] = {}
        self._oriented: set[str] = set()  # the parts whose way round is not to be chosen
        # A footprint whose shipped annotation is of some other footprint, and why.
        self.unfitted: dict[str, str] = {}

    def part(self, ref: str) -> Part:
        if ref not in self._parts:
            raise LookupError(f"no part {ref!r}")
        return Part(ref, self)

    def parts(self, *which: str | Part | Selector) -> tuple[Part, ...]:
        """The parts selected, each once, in the order asked for: a reference (``"U1"``),
        a run of them (``"R1..R5"``, every one of which must exist), a part, or a
        selector such as ``on_net("GND")`` or ``where(value="100nF")``, which gives its
        parts in reference order. With nothing asked for, every part."""
        if not which:
            return tuple(Part(ref, self) for ref in self._parts)
        found: list[Part] = []
        for w in which:
            if isinstance(w, Part):
                found.append(self.part(w.ref))
            elif not isinstance(w, str):
                found += [p for p in self.parts() if w(p)]
            elif ".." in w:
                found += [self._in_run(w, ref) for ref in _run(w)]
            else:
                found.append(self.part(w))
        return tuple(dict.fromkeys(found))

    def _in_run(self, run: str, ref: str) -> Part:
        if ref not in self._parts:
            raise LookupError(f"{run!r}: no part {ref!r}")
        return Part(ref, self)

    def net(self, net: Net | str) -> Net:
        """A net by the circuit's name for it, or by the name ``name_nets`` gave it."""
        name = net.name if isinstance(net, Net) else net
        name = next((n for n, given in self._given.items() if given == name), name)
        if name not in self.data["nets"]:
            raise LookupError(f"no net {name!r}")
        return Net(name, self)

    def nets(self) -> tuple[Net, ...]:
        return tuple(Net(name, self) for name in self.data["nets"])

    def rails(self, *nets: Net | str) -> tuple[Net, ...]:
        """Declare *nets* as rails: supplies and grounds, the nets a part is on without
        being about them. Gives them back, in the order named. Declared before anything
        asks what a rail is (``signal_net``, ``is_rail``), so that the answer is one."""
        found = tuple(self.net(n) for n in nets)
        if self._rails_read and {n.name for n in found} - self._rails:
            raise ValueError(f"rails declared after {self._rails_read} was read: "
                             "declare the rails first")  # fmt: skip
        self._rails |= {n.name for n in found}
        return found

    def ground(self, *nets: Net | str) -> tuple[Net, ...]:
        """Declare *nets* as grounds: what a decoupling capacitor's other pin is on. A
        ground is a rail too. Gives them back, in the order named."""
        found = self.rails(*nets)
        self._grounds |= {n.name for n in found}
        return found

    def annotate(
        self,
        footprint: str,
        areas: Mapping[str, Box],
        pins: Mapping[str, Mapping[str, str]] | None = None,
        sides: Mapping[str, str] | None = None,
        oriented: Iterable[str] = (),
    ) -> None:
        """Give the footprint named *footprint* its named *areas*, each a box in the
        footprint's own coordinates, and each part in *pins*, by its reference, names
        for its pins, each with the pin's number. A name is a word: not all digits, which
        would be taken for a pin's number, and not the number of one of the part's pins.
        An area or a name is said once: one already there stays, and a different box or
        pin for it is refused, with nothing of what was said kept.

        *sides* names sides of the footprint as it is drawn, each ``left``, ``right``,
        ``top`` or ``bottom``, and every part with the footprint has them. *oriented*
        is the parts, by reference, whose way round is not to be chosen for them."""
        marked = [self.part(ref).ref for ref in oriented]
        sided = self._sides.get(footprint, {})
        for name, side in (sides or {}).items():
            if not isinstance(name, str) or not name:
                raise TypeError(f"{footprint}: a side's name is a word, such as socket, "
                                f"not {name!r}")  # fmt: skip
            if side not in ("left", "right", "top", "bottom"):
                raise ValueError(f"{footprint}: side {name} is left, right, top or bottom of "
                                 f"the footprint, not {side!r}")  # fmt: skip
            if sided.get(name, side) != side:
                raise ValueError(f"{footprint} has a side {name} already, the {sided[name]}")
        have = self._areas.get(footprint, {})
        for name, box in areas.items():
            if have.get(name, box) != box:
                raise ValueError(f"{footprint} has an area {name} already, somewhere else")
        named = {}
        for ref, names in (pins or {}).items():
            named[ref] = dict(self._names.get(self.part(ref).ref, {}))
            for name, number in names.items():
                if not isinstance(name, str):
                    raise TypeError(f"{ref}: a pin's name is a word, such as B, not {name!r}")
                if name in self._pins[ref]:
                    raise ValueError(f"{ref} has a pin numbered {name}: a name is not a number")
                if not name or name.isdigit():
                    raise ValueError(f"{ref}: a pin's name is a word, such as B, not {name!r}")
                if number not in self._pins[ref]:
                    raise LookupError(f"{ref} has no pin {number}")
                if named[ref].setdefault(name, number) != number:
                    raise ValueError(f"{ref}: pin {name} is {named[ref][name]}, and cannot "
                                     f"also be {number}")  # fmt: skip
        self._areas[footprint] = {**have, **areas}
        self._names.update(named)
        if sides:
            self._sides[footprint] = {**sided, **sides}
        self._oriented.update(marked)

    def name_nets(self, names: Mapping[str, str]) -> tuple[Net, ...]:
        """Give nets the schematic left anonymous a name to write and read:
        ``{"Net-(C106-Pad1)": "VIN"}``. Gives the nets back, in the order named. The
        circuit keeps its own names, and so do the KiCad files."""
        found = []
        for name, given in names.items():
            net = self.net(name)
            if given in self.data["nets"] and given != net.name:
                raise ValueError(f"{net.name} cannot be named {given}: the circuit has a "
                                 "net of that name")  # fmt: skip
            if (other := self._given.get(net.name, given)) != given:
                raise ValueError(f"{net.name} is named {other}, and cannot also be {given}")
            if any(g == given and n != net.name for n, g in self._given.items()):
                raise ValueError(f"{net.name} cannot be named {given}: {self.net(given).name} is")
            self._given[net.name] = given
            found.append(net)
        return tuple(found)


def _run(run: str) -> list[str]:
    """The references ``"R1..R5"`` stands for."""
    m = re.fullmatch(r"(.*?)(\d+)\.\.(.*?)(\d+)", run)
    if m is None or m[1] != m[3] or int(m[2]) > int(m[4]):
        raise ValueError(f"{run!r} is not a run of references: write the first and the last, "
                         'as in "R1..R5"')  # fmt: skip
    width = len(m[2]) if m[2].startswith("0") else 0  # C01..C12 keeps its zeros
    return [f"{m[1]}{n:0{width}d}" for n in range(int(m[2]), int(m[4]) + 1)]
