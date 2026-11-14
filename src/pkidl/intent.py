"""Intent: what a board file says about where things go, as statements.

A statement is an immutable value. ``place(p1, against=Edge.LEFT, inset=1.27 * mm)`` makes
one and moves nothing; a board collects them (``board.place``, ``board.add``) and solves
them together when it is built, so the order they were written in never matters. A block
is a function that returns statements, to add to any board that has those parts.

Each aspect of a part is said once. Two statements that give it differently are a
conflict, reported with the line each was written on; neither wins.

``row(fans, along=Edge.BOTTOM)`` is about several parts at once: where they go along an
edge, in the order they are named.

``decouple(u1, caps, within=2 * mm)`` puts capacitors by a part's supply pins, one to
a pin.

``keepout(u1.area("antenna"), copper=True)`` is a statement too, about an area of a
part. It says nothing of where the part goes, so keepouts add up and never conflict.

``rules(track=0.25 * mm, clearance=0.2 * mm)`` and ``route()`` are about the board, not
a part: the widths its copper is held to, and that it is routed when it is built.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from pkidl.circuit import Area, Circuit, Part, Pin, natural
from pkidl.units import Length, length, mm

_HERE = str(Path(__file__).parent) + os.sep


class Edge(Enum):
    """A side of the board, as it is seen from the front."""

    LEFT = "left"
    RIGHT = "right"
    TOP = "top"
    BOTTOM = "bottom"

    def __str__(self) -> str:
        return f"Edge.{self.name}"


class Side(Enum):
    """A face of the board."""

    FRONT = "front"
    BACK = "back"

    def __str__(self) -> str:
        return f"Side.{self.name}"


@dataclass(frozen=True)
class Source:
    """The line of a board file that made a statement."""

    file: str
    line: int

    def __str__(self) -> str:
        return f"{Path(self.file).name}:{self.line}"


def _written_at() -> Source | None:
    """The line that made the statement being made: the nearest caller outside pkidl."""
    frame = sys._getframe(1)
    while frame is not None and frame.f_code.co_filename.startswith(_HERE):
        frame = frame.f_back
    return None if frame is None else Source(frame.f_code.co_filename, frame.f_lineno)


@dataclass(frozen=True)
class Statement:
    """Something said about the layout. Two statements that say the same thing are equal,
    wherever they were written."""

    source: Source | None = field(default=None, compare=False, repr=False, kw_only=True)

    def mentions(self) -> tuple[Part, ...]:
        """Every part it speaks of, the ones it is about first."""
        raise NotImplementedError

    def claims(self) -> dict[tuple[str, str], object]:
        """What it fixes, as ``(reference, aspect): value``: the things only one statement
        can say about a part."""
        return {}

    def data(self) -> dict[str, Any]:
        """The statement as plain data, the same however it was written."""
        raise NotImplementedError

    def check(self, circuit: Circuit) -> None:
        """Refuse a statement that speaks of something *circuit* has not got."""
        for part in self.mentions():
            circuit.part(part.ref)


@dataclass(frozen=True)
class Place(Statement):
    """Where a part goes, by what it is related to. Made with ``place``."""

    part: Part
    against: Edge | None = None
    inset: Length | None = None
    between: tuple[Part, Part] | None = None
    facing: Edge | None = None
    near: Pin | Part | None = None
    within: Length | None = None
    side: Side | None = None
    toward: Edge | None = None
    centre: bool = False
    outward: str | None = None
    along: float | Length | None = None
    after: Part | None = None
    before: Part | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.part, Part):
            raise TypeError(f'place() takes a part, such as board["U1"], not {self.part!r}')
        for name, other in (("after", self.after), ("before", self.before)):
            if other is None:
                continue
            if not isinstance(other, Part):
                raise TypeError(f"{self.part}: {name}= takes a part, not {other!r}")
            if other == self.part:
                raise ValueError(f"{self.part}: {name}= {other} is the part itself")
            if self.against is None:
                raise ValueError(f"{self.part}: {name}= says where along an edge the part "
                                 "is: give against=")  # fmt: skip
        if self.after is not None and self.after == self.before:
            raise ValueError(f"{self.part}: it cannot be both after and before {self.after}")
        if self.along is not None:
            if self.against is None:
                raise ValueError(f"{self.part}: along= says where along an edge the part "
                                 "is: give against=")  # fmt: skip
            if self.after is not None or self.before is not None:
                raise ValueError(f"{self.part}: along= says where along the edge, and "
                                 "after= or before= leaves it to be found: give one")  # fmt: skip
            if isinstance(self.along, bool) or not isinstance(self.along, int | float | Length):
                raise TypeError(f"{self.part}: along= takes a share of the edge, such as "
                                f"1 / 3, or a distance along it, not {self.along!r}")  # fmt: skip
            if isinstance(self.along, Length):
                if self.along < Length(0):
                    raise ValueError(f"{self.part}: along= {self.along} is off the edge")
            elif not 0 <= self.along <= 1:
                raise ValueError(f"{self.part}: along= {self.along} is a share of the edge, "
                                 "from 0 to 1; a distance has its unit: 12 * mm")  # fmt: skip
        if self.outward is not None:
            if not isinstance(self.outward, str) or not self.outward:
                raise TypeError(f"{self.part}: outward= takes the name of a side of the "
                                f"part, such as \"socket\", not {self.outward!r}")  # fmt: skip
            if self.against is None:
                raise ValueError(f"{self.part}: outward= says which side of the part is to "
                                 "an edge: give against=")  # fmt: skip
        for name, edge in (("against", self.against), ("facing", self.facing),
                           ("toward", self.toward)):  # fmt: skip
            if not isinstance(edge, Edge | None):
                raise TypeError(f"{self.part}: {name}= takes an edge, such as Edge.LEFT, "
                                f"not {edge!r}")  # fmt: skip
        if not isinstance(self.side, Side | None):
            raise TypeError(f"{self.part}: side= takes Side.FRONT or Side.BACK, not {self.side!r}")
        if not isinstance(self.centre, bool):
            raise TypeError(f"{self.part}: centre= takes True, not {self.centre!r}")
        if not (self.against or self.between or self.centre or self.facing or self.near
                or self.side):  # fmt: skip
            raise ValueError(f"place({self.part}) does not say where: give against=, "
                             "between=, centre=True, facing=, near= or side=")  # fmt: skip
        if self.toward is not None and self.near is None:
            raise ValueError(f"{self.part}: toward= says which side of what it is near: "
                             "give near=")  # fmt: skip
        if self.inset is not None and self.against is None:
            raise ValueError(f"{self.part}: inset= is measured from an edge: give against=")
        if self.inset is not None and self.inset < Length(0):
            raise ValueError(f"{self.part}: inset= {self.inset} is outside the board")
        if (self.near is None) != (self.within is None):
            raise ValueError(f"{self.part}: near= and within= go together: what it is near, "
                             "and how near")  # fmt: skip
        if self.near is not None:
            if not isinstance(self.near, Part | Pin):
                raise TypeError(f"{self.part}: near= takes a part or a pin, not {self.near!r}")
            if _part_of(self.near) == self.part:
                raise ValueError(f"{self.part}: near= {self.near} is the part itself")
        if self.within is not None and self.within <= Length(0):
            raise ValueError(f"{self.part}: within= {self.within} leaves no room")
        if self.between is not None:
            pair = tuple(self.between)
            if len(pair) != 2 or not all(isinstance(p, Part) for p in pair):
                raise TypeError(f"{self.part}: between= takes two parts, not {self.between!r}")
            if pair[0] == pair[1] or self.part in pair:
                raise ValueError(f"{self.part}: between= takes two other parts, not "
                                 f"{pair[0]} and {pair[1]}")  # fmt: skip
            # Between A and B is between B and A.
            object.__setattr__(self, "between", tuple(sorted(pair, key=_by_ref)))

    def _said(self) -> Iterator[tuple[str, Any]]:
        for name in ("against", "inset", "between", "facing", "near", "within", "side",
                     "toward", "centre", "outward", "along", "after", "before"):  # fmt: skip
            if (value := getattr(self, name)) is not None and value is not False:
                yield name, value

    def __str__(self) -> str:
        said = [f"{name}={_shown(value)}" for name, value in self._said()]
        return f"place({', '.join([self.part.ref, *said])})"

    def mentions(self) -> tuple[Part, ...]:
        near = () if self.near is None else (_part_of(self.near),)
        beside = tuple(p for p in (self.after, self.before) if p is not None)
        return tuple(dict.fromkeys((self.part, *(self.between or ()), *near, *beside)))

    def claims(self) -> dict[tuple[str, str], object]:
        claims: dict[tuple[str, str], object] = {}
        if self.against is not None:
            claims[self.part.ref, f"inset from the {self.against.value} edge"] = self.inset
        if self.facing is not None:
            claims[self.part.ref, "facing"] = self.facing
        if self.along is not None:
            assert self.against is not None
            claims[self.part.ref, f"place along the {self.against.value} edge"] = self.along
        if self.near is not None:
            claims[self.part.ref, f"distance from {self.near}"] = self.within
        if self.toward is not None:
            claims[self.part.ref, f"side of {self.near}"] = self.toward
        if self.side is not None:
            claims[self.part.ref, "side"] = self.side
        return claims

    def data(self) -> dict[str, Any]:
        return {"place": self.part.ref, **{name: _data(value) for name, value in self._said()}}

    def check(self, circuit: Circuit) -> None:
        super().check(circuit)
        if isinstance(self.near, Pin):
            circuit.part(self.near.part.ref).pin(self.near.number)
        if self.outward is not None:
            circuit.part(self.part.ref).side(self.outward)


@dataclass(frozen=True)
class Align(Statement):
    """Parts a whole number of grid steps apart, across and along. Made with ``align``."""

    parts: tuple[Part, ...]
    grid: Length

    def __post_init__(self) -> None:
        parts = tuple(self.parts)
        if not all(isinstance(p, Part) for p in parts):
            raise TypeError(f'align() takes parts, such as board["U1"], not {self.parts!r}')
        if len(set(parts)) < 2:
            raise ValueError("align() takes two parts or more: the grid is between them")
        if self.grid <= Length(0):
            raise ValueError(f"align(): grid= {self.grid} is not a step")
        # Aligning A with B is aligning B with A.
        object.__setattr__(self, "parts", tuple(sorted(set(parts), key=_by_ref)))

    def __str__(self) -> str:
        return f"align({', '.join(p.ref for p in self.parts)}, grid={self.grid})"

    def mentions(self) -> tuple[Part, ...]:
        return self.parts

    def data(self) -> dict[str, Any]:
        return {"align": [p.ref for p in self.parts], "grid": self.grid.nm}


@dataclass(frozen=True)
class Row(Statement):
    """Parts spread along an edge, in the order named. Made with ``row``."""

    parts: tuple[Part, ...]
    along: Edge
    pitch: Length | str = "even"
    inset: Length | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "parts", tuple(self.parts))
        if not all(isinstance(p, Part) for p in self.parts):
            raise TypeError(f'row() takes parts, such as board.parts("P3..P6"), not {self.parts!r}')
        if twice := [p.ref for p in dict.fromkeys(self.parts) if self.parts.count(p) > 1]:
            raise ValueError(f"row() has {', '.join(twice)} twice")
        if len(self.parts) < 2:
            raise ValueError("row() takes two parts or more: one is placed against= the edge")
        if not isinstance(self.along, Edge):
            raise TypeError("row(): along= takes an edge, such as Edge.BOTTOM, "
                            f"not {self.along!r}")  # fmt: skip
        if isinstance(self.pitch, Length):
            if self.pitch <= Length(0):
                raise ValueError(f"row(): pitch= {self.pitch} is not a step")
        elif self.pitch != "even":
            raise TypeError(f'row(): pitch= takes "even" or a length, not {self.pitch!r}')
        if self.inset is not None and self.inset < Length(0):
            raise ValueError(f"row(): inset= {self.inset} is outside the board")

    def __str__(self) -> str:
        pitch = '"even"' if self.pitch == "even" else self.pitch
        inset = "" if self.inset is None else f", inset={self.inset}"
        return (f"row({', '.join(p.ref for p in self.parts)}, along={self.along}, "
                f"pitch={pitch}{inset})")  # fmt: skip

    def mentions(self) -> tuple[Part, ...]:
        return self.parts

    def claims(self) -> dict[tuple[str, str], object]:
        claims: dict[tuple[str, str], object] = {}
        for part in self.parts:
            claims[part.ref, f"inset from the {self.along.value} edge"] = self.inset
            claims[part.ref, f"row along the {self.along.value} edge"] = str(self)
        return claims

    def data(self) -> dict[str, Any]:
        inset = {} if self.inset is None else {"inset": self.inset.nm}
        return {"row": [p.ref for p in self.parts], "along": self.along.value,
                "pitch": _data(self.pitch), **inset}  # fmt: skip


@dataclass(frozen=True)
class Decouple(Statement):
    """Capacitors by the supply pins of a part, one to a pin. Made with ``decouple``."""

    part: Part
    caps: tuple[Part, ...]
    within: Length

    def __post_init__(self) -> None:
        object.__setattr__(self, "caps", tuple(self.caps))
        if not isinstance(self.part, Part) or not all(isinstance(c, Part) for c in self.caps):
            raise TypeError('decouple() takes a part and its capacitors, such as board["U1"] '
                            f'and board.parts("C1", "C2"), not {self.part!r} and '
                            f"{self.caps!r}")  # fmt: skip
        if not self.caps:
            raise ValueError(f"decouple({self.part}) names no capacitor")
        if twice := [c.ref for c in dict.fromkeys(self.caps) if self.caps.count(c) > 1]:
            raise ValueError(f"decouple({self.part}) has {', '.join(twice)} twice")
        if self.part in self.caps:
            raise ValueError(f"decouple({self.part}): {self.part} is the part itself")
        if self.within <= Length(0):
            raise ValueError(f"decouple({self.part}): within= {self.within} leaves no room")

    def __str__(self) -> str:
        caps = ", ".join(c.ref for c in self.caps)
        return f"decouple({self.part.ref}, {caps}, within={self.within})"

    def mentions(self) -> tuple[Part, ...]:
        return (*self.caps, self.part)

    def claims(self) -> dict[tuple[str, str], object]:
        # A capacitor decouples one part, and a part's capacitors are said once: which
        # of them has which pin is the order they are named in, in the one statement.
        return {(ref, "decoupling"): str(self) for ref in (self.part.ref, *self.refs)}

    @property
    def refs(self) -> tuple[str, ...]:
        return tuple(cap.ref for cap in self.caps)

    def data(self) -> dict[str, Any]:
        return {"decouple": self.part.ref, "caps": [c.ref for c in self.caps],
                "within": self.within.nm}  # fmt: skip


@dataclass(frozen=True)
class Keepout(Statement):
    """What stays out of an area of a part. Made with ``keepout``."""

    area: Area
    copper: bool = False
    both_sides: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.area, Area):
            raise TypeError('keepout() takes an area of a part, such as u1.area("antenna"), '
                            f"not {self.area!r}")  # fmt: skip
        if not self.copper:
            raise ValueError(f"keepout({self.area}) does not say what is kept out: give "
                             "copper=True")  # fmt: skip

    def __str__(self) -> str:
        sides = ", both_sides=True" if self.both_sides else ""
        return f"keepout({self.area}, copper=True{sides})"

    def mentions(self) -> tuple[Part, ...]:
        return (self.area.part,)

    def data(self) -> dict[str, Any]:
        return {"keepout": self.area.part.ref, "area": self.area.name, "copper": True,
                "both_sides": self.both_sides}  # fmt: skip

    def check(self, circuit: Circuit) -> None:
        circuit.part(self.area.part.ref).area(self.area.name)


BOARD = "the board"


@dataclass(frozen=True)
class Rules(Statement):
    """The widths the board's copper is held to. Made with ``rules``."""

    track: Length
    clearance: Length
    edge: Length

    def __post_init__(self) -> None:
        for name, value in (("track", self.track), ("clearance", self.clearance)):
            if value <= Length(0):
                raise ValueError(f"rules(): {name}= {value} is not a width")
        if self.edge < Length(0):
            raise ValueError(f"rules(): edge= {self.edge} is outside the board")

    def __str__(self) -> str:
        return f"rules(track={self.track}, clearance={self.clearance}, edge={self.edge})"

    def mentions(self) -> tuple[Part, ...]:
        return ()

    def claims(self) -> dict[tuple[str, str], object]:
        return {(BOARD, "track width"): self.track, (BOARD, "clearance"): self.clearance,
                (BOARD, "clearance from the edge"): self.edge}  # fmt: skip

    def data(self) -> dict[str, Any]:
        return {"rules": {"track": self.track.nm, "clearance": self.clearance.nm,
                          "edge": self.edge.nm}}  # fmt: skip


@dataclass(frozen=True)
class Route(Statement):
    """That the board is routed when it is built. Made with ``route``."""

    def __str__(self) -> str:
        return "route()"

    def mentions(self) -> tuple[Part, ...]:
        return ()

    def data(self) -> dict[str, Any]:
        return {"route": True}


def place(
    part: Part,
    *,
    against: Edge | None = None,
    inset: Length | str | None = None,
    between: tuple[Part, Part] | None = None,
    facing: Edge | None = None,
    near: Pin | Part | None = None,
    within: Length | str | None = None,
    side: Side | str | None = None,
    toward: Edge | None = None,
    centre: bool = False,
    outward: str | None = None,
    along: float | Length | str | None = None,
    after: Part | None = None,
    before: Part | None = None,
) -> Place:
    """Say where *part* goes: *against* an edge of the board, *inset* from it, with the
    side of it named *outward* to that edge (``annotate(sides=)`` names a part's sides),
    and *along* the edge by a share of it, ``1 / 3``, or a distance, ``12 * mm``, from
    its top end or its left end to the part's middle, or *after* or *before* another
    part along it, as near that part as there is room;
    *between* two parts; *facing* an edge; *near* a pin or a part, *within* a distance of it, and
    on the side of it that is *toward* an edge; at the *centre* of the board; on which
    *side* of the board, ``Side.BACK`` or ``"back"``. One statement can say several.
    Nothing moves until the board is built."""
    inset = None if inset is None else length(inset)
    within = None if within is None else length(within)
    if isinstance(side, str) and side in ("front", "back"):
        side = Side(side)
    return Place(part, against, inset, between, facing, near, within, side,  # type: ignore[arg-type]
                 toward, centre, outward, length(along) if isinstance(along, str) else along,
                 after, before, source=_written_at())  # fmt: skip


def align(*parts: Part, grid: Length | str) -> Align:
    """Say that *parts* sit a whole number of *grid* steps from each other, across and
    along: what puts two headers into one breadboard."""
    return Align(parts, length(grid), source=_written_at())


def row(parts: Iterable[Part], *, along: Edge, pitch: Length | str = "even",
        inset: Length | str | None = None) -> Row:  # fmt: skip
    """Say that *parts* go in a row *along* an edge of the board, in the order named:
    from the left along the top or bottom, from the top down a side. Each lies against
    the edge as ``place(part, against=)`` has it, *inset* from it likewise. With
    *pitch* ``"even"`` the gaps are equal: between the parts, and from each end of the
    edge to the part nearest it. With a length, the parts' middles are that far apart
    and the row is about the middle of the edge."""
    return Row(tuple(parts), along, pitch if pitch == "even" else length(pitch),
               None if inset is None else length(inset), source=_written_at())  # fmt: skip


def decouple(part: Part, caps: Iterable[Part], *, within: Length | str) -> Decouple:
    """Say that *caps* decouple *part*. Each is across one of the part's supplies and
    ground, which ``board.ground`` declares, and goes by one of the part's pins on that
    supply: its own pad on the supply *within* that distance of the pin, and one
    capacitor to a pin, in the order named and the order of the pin numbers. A part's
    capacitors are said in one statement. A capacitor with no pin left is a problem,
    not a second capacitor on a pin, and so is one that is not across ground and a net
    the part is on: either belongs by some other part."""
    if isinstance(caps, Part):
        raise TypeError(f"decouple({part}) takes its capacitors together, as in "
                        f"decouple({part}, [{caps}], within=...)")  # fmt: skip
    return Decouple(part, tuple(caps), length(within), source=_written_at())


def keepout(area: Area, *, copper: bool = False, both_sides: bool = False) -> Keepout:
    """Say what stays out of *area*, a named area of a part such as
    ``u1.area("antenna")``, wherever the part is placed. *copper*: no other part, and no
    track, via or pour, on the part's face of the board, or on both with *both_sides*.
    Keepouts add up: an area is clear of everything any of them says."""
    return Keepout(area, bool(copper), bool(both_sides), source=_written_at())


def rules(*, track: Length | str, clearance: Length | str,
          edge: Length | str = 0.5 * mm) -> Rules:  # fmt: skip
    """Say the widths the board's copper is held to: how wide a *track* is, the
    *clearance* between copper of two nets, and how far copper stays from the board's
    *edge*. They are the rules the router is given and the ones written into the
    project for KiCad's DRC. Each is said once: a second ``rules`` that gives one
    differently is a conflict."""
    return Rules(length(track), length(clearance), length(edge), source=_written_at())


def route() -> Route:
    """Say that the board is routed when it is built: every net, to the board's
    ``rules``, around its parts and out of every area kept clear of copper."""
    return Route(source=_written_at())


@dataclass(frozen=True)
class Conflict:
    """One aspect of one part, or of the board, given differently by two statements."""

    part: str
    aspect: str
    first: Statement
    second: Statement

    def __str__(self) -> str:
        a, b = (_spoken(s.claims()[self.part, self.aspect]) + (f" ({s.source})" if s.source else "")
                for s in (self.first, self.second))  # fmt: skip
        return f"{self.part}: {self.aspect} is {a} and {b}"


def canonical(statements: Iterable[Statement]) -> list[Statement]:
    """*statements* in an order that depends on what they say and where they were written,
    never on when they were added."""
    return sorted(statements, key=_order)


def conflicts(statements: Iterable[Statement]) -> tuple[Conflict, ...]:
    """Each aspect of a part that two of *statements* give differently, by part and then by
    aspect. The statement written first in the file is the one the others are held to."""
    said: dict[tuple[str, str], list[tuple[object, Statement]]] = {}
    for statement in canonical(statements):
        for claim, value in statement.claims().items():
            said.setdefault(claim, []).append((value, statement))
    found = []
    for (ref, aspect), values in sorted(said.items(), key=lambda kv: (natural(kv[0][0]), kv[0][1])):
        seen = [values[0][0]]
        for value, statement in values[1:]:
            if value not in seen:
                seen.append(value)
                found.append(Conflict(ref, aspect, values[0][1], statement))
    return tuple(found)


def _order(statement: Statement) -> tuple:
    at = statement.source
    return (at.file if at else "", at.line if at else 0,
            json.dumps(statement.data(), sort_keys=True))  # fmt: skip


def _by_ref(part: Part) -> tuple:
    return natural(part.ref)


def _part_of(thing: Part | Pin) -> Part:
    return thing.part if isinstance(thing, Pin) else thing


def _shown(value: Any) -> str:
    """A value as the board file wrote it."""
    if isinstance(value, tuple):
        return f"({', '.join(map(str, value))})"
    if isinstance(value, str):
        return f'"{value}"'
    return str(value)


def _spoken(value: object) -> str:
    """A value as a sentence has it."""
    if value is None:
        return "left unsaid"
    if isinstance(value, Side):
        return f"the {value.value}"
    return f"the {value.value} edge" if isinstance(value, Edge) else str(value)


def _data(value: Any) -> Any:
    if isinstance(value, Length):
        return value.nm
    if isinstance(value, bool | int | float):
        return value
    if isinstance(value, Edge | Side):
        return value.value
    if isinstance(value, tuple):
        return [str(v) for v in value]
    return str(value)
