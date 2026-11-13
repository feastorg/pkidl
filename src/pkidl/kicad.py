"""KiCad as the judge of a board's connections, where it is installed.

``pkidl.fill.cut_off`` models how KiCad fills a pour and joins pads to it. KiCad itself
is the thing modelled: where its command line is there, ``unconnected`` has it fill a
board's pours and say what it leaves unconnected, and a build takes that over the
model's word.

``$KICAD_CLI`` is the command (default ``kicad-cli``).
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path

from pkidl.fill import Cut


class KicadError(RuntimeError):
    pass


def kicad_command() -> list[str] | None:
    """The KiCad command line, from ``$KICAD_CLI``, or None where it is not installed."""
    cmd = shlex.split(os.environ.get("KICAD_CLI", "kicad-cli"))
    return cmd if cmd and shutil.which(cmd[0]) is not None else None


def unconnected(board: Path, *, timeout: float = 300.0) -> list[Cut] | None:
    """What KiCad leaves unconnected on *board* once it has filled its pours: a ``Cut``
    for each item of its report (see ``cuts``), with the net and the pads it names and
    its own words. The board file is not changed; the report is left beside it as
    ``<stem>-drc.json``, and KiCad leaves a ``<stem>.kicad_prl`` there as well.

    None where KiCad does not finish within *timeout* seconds, which it does not for
    some boards. Raises ``KicadError`` where it is not installed or does not report.
    """
    cmd = kicad_command()
    if cmd is None:
        raise KicadError("KiCad's command line is not found; set $KICAD_CLI or install KiCad")
    report = board.with_name(f"{board.stem}-drc.json")
    report.unlink(missing_ok=True)
    try:
        result = subprocess.run(
            [*cmd, "pcb", "drc", "--refill-zones", "--severity-all", "--format", "json",
             "-o", str(report), str(board)],
            capture_output=True, text=True, timeout=timeout,
        )  # fmt: skip
    except subprocess.TimeoutExpired:
        return None
    if not report.exists():
        tail = (result.stdout + result.stderr).strip().splitlines()[-10:]
        raise KicadError(f"{cmd[0]} exited {result.returncode} with no report:\n" + "\n".join(tail))
    return cuts(json.loads(report.read_text()))


def cuts(report: dict) -> list[Cut]:
    """What a KiCad DRC *report* (its JSON) says a board's pours do not carry: each
    unconnected item, and each pad joined to its pour by fewer spokes than KiCad asks
    (``starved_thermal``), which KiCad counts as connected and as an error. Each is a
    ``Cut`` with the net and the pads KiCad names, in its words."""
    starved = [v for v in report.get("violations", []) if v.get("type") == "starved_thermal"]
    found = []
    for item in [*report.get("unconnected_items", []), *starved]:
        said = [str(part.get("description", "")) for part in item.get("items", [])]
        nets = [m.group(1) for text in said if (m := re.search(r"\[(.*?)\]", text))]
        pads = [f"{m.group(2)}.{m.group(1)}" for text in said
                if (m := re.search(r"[Pp]ad (\S+) \[.*?\] of (\S+)", text))]  # fmt: skip
        what = " and ".join(said)
        if item in starved:
            what = f"{item.get('description', 'starved thermal')}: {what}"
        found.append(Cut(nets[0] if nets else "", tuple(pads), seen=what))
    return found
