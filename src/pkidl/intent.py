"""Intent: what a board file says about where things go, as statements.

A statement is an immutable value. ``place(p1, against=Edge.LEFT, inset=1.27 * mm)`` makes
one and moves nothing; a board collects them (``board.place``, ``board.add``) and solves
them together when it is built, so the order they were written in never matters. A block
is a function that returns statements, to add to any board that has those parts.

Each aspect of a part is said once. Two statements that give it differently are a
conflict, reported with the line each was written on; neither wins.
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

from pkidl.circuit import Circuit, Part, Pin, natural
from pkidl.units import Length, length

_HERE = str(Path(__file__).parent) + os.sep


class Edge(Enum):
    """A side of the board, as it is seen from the front."""

    LEFT = "left"
    RIGHT = "right"
    TOP = "top"
    BOTTOM = "bottom"

    def __str__(self) -> str:
        return f"Edge.{self.name}"


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

    def __post_init__(self) -> None:
        if not isinstance(self.part, Part):
            raise TypeError(f'place() takes a part, such as board["U1"], not {self.part!r}')
        for name, edge in (("against", self.against), ("facing", self.facing)):
            if not isinstance(edge, Edge | None):
                raise TypeError(f"{self.part}: {name}= takes an edge, such as Edge.LEFT, "
                                f"not {edge!r}")  # fmt: skip
        if not (self.against or self.between or self.facing or self.near):
            raise ValueError(f"place({self.part}) does not say where: give against=, "
                             "between=, facing= or near=")  # fmt: skip
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
        for name in ("against", "inset", "between", "facing", "near", "within"):
            if (value := getattr(self, name)) is not None:
                yield name, value

    def __str__(self) -> str:
        said = [f"{name}={_shown(value)}" for name, value in self._said()]
        return f"place({', '.join([self.part.ref, *said])})"

    def mentions(self) -> tuple[Part, ...]:
        near = () if self.near is None else (_part_of(self.near),)
        return tuple(dict.fromkeys((self.part, *(self.between or ()), *near)))

    def claims(self) -> dict[tuple[str, str], object]:
        claims: dict[tuple[str, str], object] = {}
        if self.against is not None:
            claims[self.part.ref, f"inset from the {self.against.value} edge"] = self.inset
        if self.facing is not None:
            claims[self.part.ref, "facing"] = self.facing
        if self.near is not None:
            claims[self.part.ref, f"distance from {self.near}"] = self.within
        return claims

    def data(self) -> dict[str, Any]:
        return {"place": self.part.ref, **{name: _data(value) for name, value in self._said()}}

    def check(self, circuit: Circuit) -> None:
        super().check(circuit)
        if isinstance(self.near, Pin):
            circuit.part(self.near.part.ref).pin(self.near.number)


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


def place(
    part: Part,
    *,
    against: Edge | None = None,
    inset: Length | str | None = None,
    between: tuple[Part, Part] | None = None,
    facing: Edge | None = None,
    near: Pin | Part | None = None,
    within: Length | str | None = None,
) -> Place:
    """Say where *part* goes: *against* an edge of the board, *inset* from it; *between*
    two parts; *facing* an edge; *near* a pin or a part, *within* a distance of it. One
    statement can say several. Nothing moves until the board is built."""
    inset = None if inset is None else length(inset)
    within = None if within is None else length(within)
    return Place(part, against, inset, between, facing, near, within, source=_written_at())


def align(*parts: Part, grid: Length | str) -> Align:
    """Say that *parts* sit a whole number of *grid* steps from each other, across and
    along: what puts two headers into one breadboard."""
    return Align(parts, length(grid), source=_written_at())


@dataclass(frozen=True)
class Conflict:
    """One aspect of one part, given differently by two statements."""

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
    return str(value)


def _spoken(value: object) -> str:
    """A value as a sentence has it."""
    if value is None:
        return "left unsaid"
    return f"the {value.value} edge" if isinstance(value, Edge) else str(value)


def _data(value: Any) -> Any:
    if isinstance(value, Length):
        return value.nm
    if isinstance(value, Edge):
        return value.value
    if isinstance(value, tuple):
        return [str(v) for v in value]
    return str(value)
