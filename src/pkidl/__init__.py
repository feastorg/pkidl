"""pkidl: design PCBs in Python, and generate KiCad files from them.

The counterpart to SKiDL. SKiDL says what connects to what; pkidl says where it
goes on the board. It writes native KiCad files directly and lets ``kicad-cli``
judge them. See ``docs/charter.md``.
"""

from pkidl.board import Board
from pkidl.circuit import on_net, where
from pkidl.intent import (
    Edge,
    Side,
    align,
    apart,
    area,
    decouple,
    inside,
    keepout,
    path,
    place,
    row,
)
from pkidl.units import A, degC, inch, mA, mil, mm

__all__ = ["A", "Board", "Edge", "Side", "align", "apart", "area", "decouple", "degC",
           "inch", "inside", "keepout", "mA", "mil", "mm", "on_net", "path", "place", "row",
           "where"]  # fmt: skip
