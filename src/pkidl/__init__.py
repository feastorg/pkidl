"""pkidl — the physical layer: write KiCad boards from Python.

The counterpart to SKiDL. SKiDL says what connects to what; pkidl says where it
goes on the board. It writes native KiCad files directly and lets ``kicad-cli``
judge them. Developed inside kidl-spike for now; it imports nothing from
``kidl_spike`` so it can move to its own repo once the primitives settle.
"""
