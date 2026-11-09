"""Physical layer of Slice_HBTC: nothing of its own. ``hbtc.yaml`` names its root layout
(DCMT's: Nano, buck, net tie, LED, and their pours) and its channels; ``slice_build``
does the rest.
"""

from __future__ import annotations

from pathlib import Path

from kidl_spike.boards.hbtc import SPEC
from kidl_spike.boards.slice_build import build_pcb as _build_pcb


def build_pcb(outdir: Path, name: str, pad_nets: dict, fields: dict, source: str) -> Path:
    """Write the routed board, project, rules and lib tables (``slice_build.build_pcb``)."""
    return _build_pcb(SPEC, outdir, name, pad_nets, fields, source)
