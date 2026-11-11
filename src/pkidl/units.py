"""Lengths with their unit: ``1.27 * mm``, ``0.1 * inch``, ``"50mil"``.

A length is kept as a whole number of nanometres, as KiCad stores it, so two ways of
writing the same distance are the same value and sums do not drift. A bare number is not
a length: nothing here guesses its unit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import overload


@dataclass(frozen=True, order=True)
class Length:
    nm: int

    def __post_init__(self) -> None:
        if type(self.nm) is not int:
            raise TypeError(f"a length is a whole number of nanometres, not {self.nm!r}: "
                            "write 1.27 * mm")  # fmt: skip

    @property
    def mm(self) -> float:
        return self.nm / 1_000_000

    def __str__(self) -> str:
        return f"{self.nm / 1_000_000:.6f}".rstrip("0").rstrip(".") + " mm"

    def __mul__(self, k: float) -> Length:
        if isinstance(k, bool) or not isinstance(k, int | float):
            return NotImplemented
        return Length(round(self.nm * k))

    __rmul__ = __mul__

    @overload
    def __truediv__(self, other: Length) -> float: ...
    @overload
    def __truediv__(self, other: float) -> Length: ...
    def __truediv__(self, other: Length | float) -> Length | float:
        if isinstance(other, Length):
            return self.nm / other.nm
        if isinstance(other, bool) or not isinstance(other, int | float):
            return NotImplemented
        return Length(round(self.nm / other))

    def __add__(self, other: Length) -> Length:
        if not isinstance(other, Length):
            return NotImplemented
        return Length(self.nm + other.nm)

    def __sub__(self, other: Length) -> Length:
        if not isinstance(other, Length):
            return NotImplemented
        return Length(self.nm - other.nm)

    def __neg__(self) -> Length:
        return Length(-self.nm)


mm = Length(1_000_000)
mil = Length(25_400)
inch = Length(25_400_000)

_UNITS = {"mm": mm, "mil": mil, "in": inch, "inch": inch}


def length(value: Length | str) -> Length:
    """A length from how a board file wrote it: ``1.27 * mm`` or ``"1.27mm"``."""
    if isinstance(value, Length):
        return value
    if not isinstance(value, str):
        raise TypeError(f'{value!r} has no unit: write {value!r} * mm or "{value!r}mm"')
    m = re.fullmatch(r"\s*(-?(?:\d+\.?\d*|\.\d+))\s*(mm|mil|inch|in)\s*", value)
    if m is None:
        raise ValueError(f'{value!r} is not a length: write a number and its unit, as in '
                         '"1.27mm", "50mil" or "0.1in"')  # fmt: skip
    return float(m[1]) * _UNITS[m[2]]
