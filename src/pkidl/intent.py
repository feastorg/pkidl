"""Intent: what a board file says about where things go, as statements.

A statement is an immutable value. ``place(p1, against=Edge.LEFT, inset=1.27 * mm)`` makes
one and moves nothing; a board collects them (``board.place``, ``board.add``) and solves
them together when it is built, so the order they were written in never matters. A block
is a function that returns statements, to add to any board that has those parts.

Each aspect of a part is said once. Two statements that give it differently are a
conflict, reported with the line each was written on; neither wins.

``row(fans, along=Edge.BOTTOM)`` is about several parts at once: where they go along an
edge, in the order they are named. ``row(resistors, beside=switch, toward=Edge.RIGHT)``
is a row beside a part, on the side of it toward that edge.

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
from fractions import Fraction
from numbers import Real
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
class Fixed:
    """Something on the board that the board file does not place, a mounting hole say:
    what it is called in a problem, its footprint's name in the library, where its
    origin is, its rotation in degrees and whether it is on the back."""

    label: str
    footprint: str
    x: Length
    y: Length
    rot: float = 0.0
    back: bool = False

    def __str__(self) -> str:
        return self.label


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
    at_least: Length | None = None
    at: tuple[Length, Length] | None = None
    of: Pin | None = None
    on: Fixed | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.part, Part):
            raise TypeError(f'place() takes a part, such as board["U1"], not {self.part!r}')
        if self.on is not None:
            if not isinstance(self.on, Fixed):
                raise TypeError(f"{self.part}: on= takes something fixed on the board, as "
                                f"board.fixed(name) gives it, not {self.on!r}")  # fmt: skip
            if self.at is None:  # on a thing is at its origin, where nothing says
                object.__setattr__(self, "at", (Length(0), Length(0)))
        if self.at is not None:
            if not (isinstance(self.at, tuple | list) and len(self.at) == 2
                    and all(isinstance(v, Length) for v in self.at)):  # fmt: skip
                raise TypeError(f"{self.part}: at= takes two lengths, across and down, such "
                                f"as (72 * mm, 76 * mm), not {self.at!r}")  # fmt: skip
            object.__setattr__(self, "at", tuple(self.at))
            word = "at" if self.on is None else "on"
            for name in ("against", "between", "centre", "near", "along", "after", "before"):
                if getattr(self, name) not in (None, False):
                    raise ValueError(f"{self.part}: {word}= says where the part is, and so "
                                     f"does {name}=: give one")  # fmt: skip
        if self.of is not None:
            if not isinstance(self.of, Pin):
                raise TypeError(f"{self.part}: of= takes a pin of the part, not {self.of!r}")
            if self.at is None:
                raise ValueError(f"{self.part}: of= says which pin of the part is at a point: "
                                 "give at= or on=")  # fmt: skip
            if self.of.part != self.part:
                raise ValueError(f"{self.part}: of= takes a pin of the part itself, such as "
                                 f"{self.part}.pin(1), not {self.of}")  # fmt: skip
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
            if isinstance(self.along, bool) or not isinstance(self.along, Real | Length):
                raise TypeError(f"{self.part}: along= takes a share of the edge, such as "
                                f"1 / 3, or a distance along it, not {self.along!r}")  # fmt: skip
            if isinstance(self.along, Length):
                if self.along < Length(0):
                    raise ValueError(f"{self.part}: along= {self.along} is off the edge")
            elif 0 <= self.along <= 1:
                object.__setattr__(self, "along", float(self.along))  # a fraction is its share
            else:
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
                or self.side or self.at):  # fmt: skip
            raise ValueError(f"place({self.part}) does not say where: give against=, at=, "
                             "between=, centre=True, facing=, near=, on= or side=")  # fmt: skip
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
        if self.at_least is not None:
            if self.within is None:
                raise ValueError(f"{self.part}: at_least= is how far at the least from what "
                                 "it is near: give near= and within=")  # fmt: skip
            if not Length(0) < self.at_least < self.within:
                raise ValueError(f"{self.part}: at_least= {self.at_least} is more than "
                                 f"nothing and less than within= {self.within}")  # fmt: skip
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
        for name in ("on", "at", "of", "against", "inset", "between", "facing", "near",
                     "within", "side", "toward", "centre", "outward", "along", "after",
                     "before", "at_least"):  # fmt: skip
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
        if self.at is not None:
            # The point, which of the part is at it, and what it is a point of.
            where = _shown(self.at)
            where = where if self.of is None else f"{self.of} at {where}"
            if (on := self.on) is not None:
                # All that makes it the thing it is: two may go by one label.
                x, y = (str(v).removesuffix(" mm") for v in (on.x, on.y))
                turn = on.rot if float(f"{on.rot:g}") != on.rot else f"{on.rot:g}"
                where = (f"{where} on {on.footprint} at ({x}, {y}) turned {turn} degrees on "
                         f"the {'back' if on.back else 'front'}")  # fmt: skip
            claims[self.part.ref, "place on the board"] = where
        return claims

    def data(self) -> dict[str, Any]:
        data = {"place": self.part.ref, **{name: _data(value) for name, value in self._said()}}
        if self.at is not None:
            data["at"] = [v.nm for v in self.at]
        if self.of is not None:
            data["of"] = self.of.number
        if self.on is not None:
            data["on"] = {"footprint": self.on.footprint, "x": self.on.x.nm, "y": self.on.y.nm,
                          "rot": self.on.rot, "back": self.on.back}  # fmt: skip
        return data

    def check(self, circuit: Circuit) -> None:
        super().check(circuit)
        if isinstance(self.near, Pin):
            circuit.part(self.near.part.ref).pin(self.near.number)
        if self.of is not None:
            circuit.part(self.part.ref).pin(self.of.number)
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
    """Parts spread along an edge, or side by side beside a part on the side of it
    toward an edge, in the order named. Made with ``row``."""

    parts: tuple[Part, ...]
    along: Edge | None = None
    pitch: Length | str | None = None
    inset: Length | None = None
    beside: Part | None = None
    toward: Edge | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "parts", tuple(self.parts))
        if not all(isinstance(p, Part) for p in self.parts):
            raise TypeError(f'row() takes parts, such as board.parts("P3..P6"), not {self.parts!r}')
        if twice := [p.ref for p in dict.fromkeys(self.parts) if self.parts.count(p) > 1]:
            raise ValueError(f"row() has {', '.join(twice)} twice")
        if len(self.parts) < 2:
            raise ValueError("row() takes two parts or more: one is placed against= the edge, "
                             "or near= the part")  # fmt: skip
        if self.along is not None and self.beside is not None:
            raise ValueError("row(): along= says the row is along an edge, and beside= that "
                             "it is beside a part: give one")  # fmt: skip
        if self.toward is not None and self.beside is None:
            raise ValueError("row(): toward= says which side of a part the row is on: give "
                             "beside=")  # fmt: skip
        if self.along is None and self.beside is None:
            raise ValueError("row() does not say where: give along= an edge, or beside= a "
                             "part and toward= an edge")  # fmt: skip
        if self.beside is None:
            if not isinstance(self.along, Edge):
                raise TypeError("row(): along= takes an edge, such as Edge.BOTTOM, "
                                f"not {self.along!r}")  # fmt: skip
            if self.pitch is None:  # what is meant when no pitch is given
                object.__setattr__(self, "pitch", "even")
        else:
            if not isinstance(self.beside, Part):
                raise TypeError('row(): beside= takes a part, such as board["SW1"], '
                                f"not {self.beside!r}")  # fmt: skip
            if self.toward is None:
                raise ValueError(f"row(): beside= {self.beside} does not say which side of "
                                 "it: give toward= an edge")  # fmt: skip
            if not isinstance(self.toward, Edge):
                raise TypeError("row(): toward= takes an edge, such as Edge.RIGHT, "
                                f"not {self.toward!r}")  # fmt: skip
            if self.beside in self.parts:
                raise ValueError(f"row(): beside= {self.beside} is one of the row's parts")
            if self.inset is not None:
                raise ValueError("row(): inset= is measured from an edge: give along=")
            if self.pitch == "even":
                raise ValueError('row(): pitch="even" spreads a row along an edge: beside a '
                                 "part, give a length or leave it out")  # fmt: skip
        if isinstance(self.pitch, Length):
            if self.pitch <= Length(0):
                raise ValueError(f"row(): pitch= {self.pitch} is not a step")
        elif self.pitch != "even" and (self.pitch is not None or self.beside is None):
            raise TypeError(f'row(): pitch= takes "even" or a length, not {self.pitch!r}')
        if self.inset is not None and self.inset < Length(0):
            raise ValueError(f"row(): inset= {self.inset} is outside the board")

    def __str__(self) -> str:
        parts = ", ".join(p.ref for p in self.parts)
        if self.beside is not None:
            pitch = "" if self.pitch is None else f", pitch={self.pitch}"
            return f"row({parts}, beside={self.beside.ref}, toward={self.toward}{pitch})"
        pitch = '"even"' if self.pitch == "even" else self.pitch
        inset = "" if self.inset is None else f", inset={self.inset}"
        return f"row({parts}, along={self.along}, pitch={pitch}{inset})"

    def mentions(self) -> tuple[Part, ...]:
        return self.parts if self.beside is None else (*self.parts, self.beside)

    def claims(self) -> dict[tuple[str, str], object]:
        claims: dict[tuple[str, str], object] = {}
        for part in self.parts:
            if self.along is None:
                claims[part.ref, "row beside a part"] = str(self)
            else:
                claims[part.ref, f"inset from the {self.along.value} edge"] = self.inset
                claims[part.ref, f"row along the {self.along.value} edge"] = str(self)
        return claims

    def data(self) -> dict[str, Any]:
        if self.beside is not None:
            assert self.toward is not None
            pitch = {} if self.pitch is None else {"pitch": _data(self.pitch)}
            return {"row": [p.ref for p in self.parts], "beside": self.beside.ref,
                    "toward": self.toward.value, **pitch}  # fmt: skip
        assert self.along is not None
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


@dataclass(frozen=True)
class Region:
    """A part of the board, for parts to be said to be inside: a *share* of it from an
    *edge*, the whole of that edge's length, or a *box*, its left, top, right and bottom
    from the board's top left corner. Made with ``area``."""

    edge: Edge | None = None
    share: float | None = None
    box: tuple[Length, Length, Length, Length] | None = None

    def __post_init__(self) -> None:
        if (self.edge is None) == (self.box is None) or (
            self.box is not None and self.share is not None
        ):
            raise ValueError("area() takes an edge and a share of the board from it, or a "
                             "box=: one of them")  # fmt: skip
        if self.edge is not None:
            if not isinstance(self.edge, Edge):
                raise TypeError(f"area() takes an edge, such as Edge.LEFT, not {self.edge!r}")
            if isinstance(self.share, bool) or not isinstance(self.share, Real):
                raise TypeError("area(): share= is how much of the board from that edge, "
                                f"such as 1 / 3, not {self.share!r}")  # fmt: skip
            if not 0 < self.share <= 1:
                raise ValueError(f"area(): share= {self.share} is a share of the board, more "
                                 "than 0 and no more than 1")  # fmt: skip
            object.__setattr__(self, "share", float(self.share))
        else:
            assert self.box is not None
            x0, y0, x1, y1 = self.box
            if not (Length(0) <= x0 < x1 and Length(0) <= y0 < y1):
                raise ValueError("area(): box= is two opposite corners, each across and down "
                                 "from the board's top left, with room between them")  # fmt: skip

    def __str__(self) -> str:
        if self.edge is not None:
            assert self.share is not None
            # As short as says which share it is: two that differ read differently.
            short = format(self.share, "g")
            return f"area({self.edge}, share={short if float(short) == self.share else self.share})"
        assert self.box is not None
        x0, y0, x1, y1 = self.box
        return f"area(box=(({x0}, {y0}), ({x1}, {y1})))"

    def within(self, board: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        """Where it is on a board with the box *board*, in nanometres."""
        x0, y0, x1, y1 = board
        if self.box is not None:
            a, b, c, d = (v.nm for v in self.box)
            return x0 + a, y0 + b, x0 + c, y0 + d
        assert self.share is not None and self.edge is not None
        w, h = round(self.share * (x1 - x0)), round(self.share * (y1 - y0))
        return {
            Edge.LEFT: (x0, y0, x0 + w, y1),
            Edge.RIGHT: (x1 - w, y0, x1, y1),
            Edge.TOP: (x0, y0, x1, y0 + h),
            Edge.BOTTOM: (x0, y1 - h, x1, y1),
        }[self.edge]


@dataclass(frozen=True)
class Inside(Statement):
    """Parts that go inside an area of the board. Made with ``inside``."""

    area: Region
    parts: tuple[Part, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.area, Region):
            raise TypeError("inside() takes an area of the board, such as "
                            f"board.area(Edge.LEFT, share=1 / 3), not {self.area!r}")  # fmt: skip
        if not self.parts or not all(isinstance(p, Part) for p in self.parts):
            raise TypeError(f"inside({self.area}) takes the parts that go inside it")
        object.__setattr__(self, "parts", tuple(sorted(dict.fromkeys(self.parts), key=_by_ref)))

    def __str__(self) -> str:
        return f"inside({self.area}, {', '.join(p.ref for p in self.parts)})"

    def mentions(self) -> tuple[Part, ...]:
        return self.parts

    def data(self) -> dict[str, Any]:
        # The area as it is and not as it reads, so that two never have one order by chance.
        area = self.area
        if area.box is not None:
            said: dict[str, Any] = {"box": [v.nm for v in area.box]}
        else:
            assert area.edge is not None
            said = {"edge": area.edge.value, "share": area.share}
        return {"inside": said, "parts": [p.ref for p in self.parts]}


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
    along: float | Fraction | Length | str | None = None,
    after: Part | None = None,
    before: Part | None = None,
    at_least: Length | str | None = None,
    at: tuple[Length | str, Length | str] | None = None,
    of: Pin | None = None,
    on: Fixed | None = None,
) -> Place:
    """Say where *part* goes: *at* a point of the board, two lengths across and down
    from its top left corner, where the footprint's origin goes, or the pin *of* the
    part that is named; *on* something fixed on the board, as ``board.fixed`` gives it,
    *at* a point of that thing in its own footprint's coordinates, and free to overlap
    it; *against* an edge of the board, *inset* from it, with the
    side of it named *outward* to that edge (``annotate(sides=)`` names a part's sides),
    and *along* the edge by a share of it, ``1 / 3``, or a distance, ``12 * mm``, from
    its top end or its left end to the part's middle, or *after* or *before* another
    part along it, as near that part as there is room;
    *between* two parts; *facing* an edge; *near* a pin or a part, *within* a distance of it and
    *at_least* a distance from it, and
    on the side of it that is *toward* an edge; at the *centre* of the board; on which
    *side* of the board, ``Side.BACK`` or ``"back"``. One statement can say several.
    Nothing moves until the board is built."""
    inset = None if inset is None else length(inset)
    within = None if within is None else length(within)
    if isinstance(side, str) and side in ("front", "back"):
        side = Side(side)
    if isinstance(at, tuple | list) and len(at) == 2:
        at = tuple(length(v) if isinstance(v, str) else v for v in at)  # type: ignore[assignment]
    return Place(part, against, inset, between, facing, near, within, side,  # type: ignore[arg-type]
                 toward, centre, outward,
                 length(along) if isinstance(along, str)
                 else float(along) if isinstance(along, Fraction) else along,
                 after, before, None if at_least is None else length(at_least),
                 at=at, of=of, on=on, source=_written_at())  # type: ignore[arg-type]  # fmt: skip


def align(*parts: Part, grid: Length | str) -> Align:
    """Say that *parts* sit a whole number of *grid* steps from each other, across and
    along: what puts two headers into one breadboard."""
    return Align(parts, length(grid), source=_written_at())


def row(parts: Iterable[Part], *, along: Edge | None = None,
        pitch: Length | str | None = None, inset: Length | str | None = None,
        beside: Part | None = None, toward: Edge | None = None) -> Row:  # fmt: skip
    """Say that *parts* go in a row, in the order named, one of two ways.

    *along* an edge of the board: from the left along the top or bottom, from the top
    down a side. Each lies against the edge as ``place(part, against=)`` has it, *inset*
    from it likewise. With *pitch* ``"even"``, which is what no pitch means, the gaps
    are equal: between the parts, and from each end of the edge to the part nearest it.
    With a length, the parts' middles are that far apart and the row is about the
    middle of the edge.

    *beside* a part, on the side of it *toward* an edge: one above another down its left
    or right side, the first uppermost, or from the left along its top or bottom. Each
    stands across the row, its length away from the part, like the rungs of a ladder,
    and all are turned the same way. Their middles are *pitch* apart, or as close as
    keeps their outlines clear of each other and their pads as far apart as the board's
    rules say. The row is as near the part as it is clear, its middle level with the
    part's, and further out or along from there where something is in the way."""
    return Row(tuple(parts), along, pitch if pitch is None or pitch == "even" else length(pitch),
               None if inset is None else length(inset), beside, toward,
               source=_written_at())  # fmt: skip


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


def area(
    edge: Edge | None = None,
    *,
    share: float | Fraction | None = None,
    box: tuple[tuple[Length | str, Length | str], tuple[Length | str, Length | str]] | None = None,
) -> Region:
    """An area of the board: a *share* of it from an *edge*, ``area(Edge.LEFT, share=1 /
    3)`` the left third, or a *box* by two opposite corners, each across and down from
    the board's top left corner. It says nothing by itself: ``inside`` puts parts in it."""
    if box is None:
        return Region(edge, share)  # type: ignore[arg-type]
    if not (isinstance(box, tuple | list) and len(box) == 2
            and all(isinstance(xy, tuple | list) and len(xy) == 2 for xy in box)):  # fmt: skip
        raise TypeError("area(): box= is two opposite corners, as in box=((0 * mm, 0 * mm), "
                        f"(30 * mm, 40 * mm)), not {box!r}")  # fmt: skip
    (ax, ay), (bx, by) = ((length(x), length(y)) for x, y in box)
    return Region(edge, share, (min(ax, bx), min(ay, by), max(ax, bx), max(ay, by)))  # type: ignore[arg-type]


def inside(area: Region, parts: Iterable[Part]) -> Inside:
    """Say that *parts* go inside *area*: the whole outline of each. An area keeps parts
    in and does nothing else: it does not spread them over itself."""
    if isinstance(parts, Part):
        raise TypeError(f"inside({area}) takes its parts together, as in "
                        f"inside({area}, [{parts}])")  # fmt: skip
    return Inside(area, tuple(parts), source=_written_at())


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
