"""pkidl: design PCBs in Python, and generate KiCad files from them.

The counterpart to SKiDL. SKiDL says what connects to what; pkidl says where it
goes on the board. It writes native KiCad files directly and lets ``kicad-cli``
judge them. See ``docs/charter.md``.
"""

from pkidl.board import Board

__all__ = ["Board"]
