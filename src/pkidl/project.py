"""Write a KiCad project file (``.kicad_pro``) with explicit rules and severities.

A generated board must not inherit KiCad's defaults: ``footprint_symbol_mismatch``
defaults to a warning, so a default DRC passes a schematic/board mismatch
(F-005). Everything the checks depend on is stated here. KiCad fills in any
setting not written.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

# Schematic/board parity rules KiCad ships as warnings (F-005, P7). A generated
# board escalates them, so a mismatch fails DRC instead of scrolling past.
PARITY_ERRORS = {
    "duplicate_footprints": "error",
    "extra_footprint": "error",
    "footprint_symbol_mismatch": "error",
    "lib_footprint_mismatch": "error",
    "missing_footprint": "error",
    "net_conflict": "error",
}
# Silkscreen over exposed copper is unreadable and smears at fab; placed references
# keep off it (pkidl.silk), so any new case fails the build.
SILK_ERRORS = {"silk_over_copper": "error"}


@dataclass(frozen=True)
class NetClass:
    name: str
    clearance: float
    track_width: float
    via_diameter: float = 0.8
    via_drill: float = 0.4

    def as_json(self, priority: int) -> dict:
        return {
            "name": self.name,
            "clearance": self.clearance,
            "track_width": self.track_width,
            "via_diameter": self.via_diameter,
            "via_drill": self.via_drill,
            "microvia_diameter": 0.3,
            "microvia_drill": 0.1,
            "diff_pair_gap": 0.25,
            "diff_pair_via_gap": 0.25,
            "diff_pair_width": 0.2,
            "bus_width": 12,
            "wire_width": 6,
            "line_style": 0,
            "priority": priority,
        }


# What KiCad reads in a netclass pattern as other than itself, and how each is written
# to be read as itself.
_MEANT = {
    **{c: "\\" + c for c in "\\^$.|+()[]"},
    "{": "[{]",
    "}": "[}]",
    "*": "\\x2a",
    "?": "\\x3f",
}


def exactly(net: str) -> str:
    """The netclass pattern that puts the net named *net* in a class, and no other net.

    KiCad reads a pattern two ways and takes a net that either matches whole, with
    the case as written: as a regular expression, and as a wildcard, in which ``*``
    and ``?`` stand for any characters and the rest for themselves (KiCad 10.0.8,
    by its DRC). A name written as it is is so a pattern for other names: ``V+``
    takes ``V`` and ``VV``, ``A.B`` takes ``AxB`` and ``Net-(U1-Pad3)`` takes
    ``Net-U1-Pad3``. Here each character an expression reads as other than itself has
    a backslash before it; a brace is in a class of its own, ``[{]``, since two with
    backslashes round a name match nothing; and ``*`` and ``?`` are by their numbers,
    so the wildcard has neither to read. A name with none of them is its own pattern.

    What is left: a net named as the pattern itself is written, ``V\\+`` beside
    ``V+``, is taken with it, by the wildcard."""
    return "".join(_MEANT.get(c, c) for c in net)


def write_project(
    path: Path,
    *,
    netclasses: list[NetClass],
    members: dict[str, list[str]],
    rules: dict[str, float | bool],
    severities: dict[str, str],
) -> Path:
    """Write *path*. ``members`` maps a netclass name to exact net names: each is
    written as the pattern that matches that name alone (``exactly``).

    The first netclass must be ``Default``; it applies to every net not listed.
    """
    if not netclasses or netclasses[0].name != "Default":
        raise ValueError("the first netclass must be 'Default'")
    patterns = [
        {"netclass": cls, "pattern": exactly(net)}
        for cls in sorted(members)
        for net in sorted(members[cls])
    ]
    project = {
        "board": {
            "design_settings": {
                "meta": {"version": 2},
                "rules": rules,
                "rule_severities": dict(sorted(severities.items())),
            }
        },
        "meta": {"filename": path.name, "version": 3},
        "net_settings": {
            "classes": [
                # Lower number wins; Default is the fallback, so it gets the largest.
                c.as_json(priority=2147483647 if c.name == "Default" else i - 1)
                for i, c in enumerate(netclasses)
            ],
            "meta": {"version": 5},
            "netclass_patterns": patterns,
        },
    }
    path.write_text(json.dumps(project, indent=2) + "\n")
    return path


@dataclass(frozen=True)
class DruRule:
    """One KiCad custom design rule: ``constraint`` must be at least ``min_mm``.

    ``condition`` is a KiCad rule expression (``A.NetClass == 'HV Relay'``); empty
    applies to everything. ``why`` is written above the rule as a comment.
    """

    name: str
    constraint: str  # track_width, clearance, creepage, hole_clearance, ...
    min_mm: float
    condition: str = ""
    severity: str = "warning"
    why: str = ""


def width_rules(
    netclasses: list[NetClass],
    severity: str = "warning",
    minimums: dict[str, tuple[float, str]] | None = None,
) -> list[DruRule]:
    """One minimum-width rule per netclass, at the class's own width, or at the
    (width, reason) *minimums* gives for it.

    KiCad treats a netclass width as the default for new tracks, not a minimum:
    a narrower track passes DRC unless a rule like these says otherwise.
    """
    minimums = minimums or {}
    out = []
    for c in netclasses:
        width, why = minimums.get(
            c.name, (c.track_width, f"the {c.name} netclass width, as a minimum")
        )
        condition = "" if c.name == "Default" else f"A.NetClass == '{c.name}'"
        out.append(DruRule(f"{c.name} width", "track_width", width, condition, severity, why))
    return out


def write_rules(path: Path, rules: list[DruRule]) -> Path:
    """Write a ``.kicad_dru`` custom rules file. KiCad reads ``<project>.kicad_dru``."""
    out = ["(version 1)"]
    for r in rules:
        out.append("")
        if r.why:
            out.append(f"# {r.why}")
        out.append(f'(rule "{r.name}"')
        out.append(f"  (severity {r.severity})")
        if r.condition:
            out.append(f'  (condition "{r.condition}")')
        out.append(f"  (constraint {r.constraint} (min {r.min_mm:g}mm)))")
    path.write_text("\n".join(out) + "\n")
    return path
