"""Freerouting as a router: a job written as a DSN file, routed into an SES file.

``Freerouting`` is the ``pkidl.routing.Router``; ``freerouting`` runs the command.

Freerouting is run single-threaded, the mode in which 2.5.0 is deterministic for
a given input. ``-mt 1`` limits only the autorouter: the optimizer has its own thread
count (one fewer than the cores by default), and with several threads the same DSN
routed six times gave three different sessions. Both are set to one.

``$FREEROUTING`` overrides the command (default ``freerouting``, the pinned wrapper that
runs the 2.5.0 jar headless).

In 2.5.0 the fan-out stage narrows its stubs out of SMD pads to three quarters of the
track width whatever ``automatic_neckdown`` is: on the fan controller, 13 paths at
0.1874 mm under a 0.25 mm minimum with neck-down off, and none with fan-out off as
well. A job says each on its own (``neck_down``, ``fan_out``): two boards with wide
power tracks leave connections unmade when their power stage has no fan-out.

What the router says of its own work is read from its log: the last
``(N unrouted and M violations)`` of its auto-routing stage, as 2.5.0 writes it.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from pkidl.dsn import read_ses, write_dsn
from pkidl.routing import Job, Run


class RouterError(RuntimeError):
    pass


def router_command() -> list[str]:
    """The Freerouting command, from ``$FREEROUTING``. Raises ``RouterError`` if absent."""
    cmd = shlex.split(os.environ.get("FREEROUTING", "freerouting"))
    if not cmd or shutil.which(cmd[0]) is None:
        raise RouterError(f"{cmd[:1]!r} not found; set $FREEROUTING or install Freerouting")
    return cmd


def freerouting(
    dsn: Path,
    ses: Path,
    *,
    passes: int = 100,
    log: Path | None = None,
    options: Sequence[str] = (),
) -> Path:
    """Route *dsn* into *ses*, passing *options* to the router. Raises ``RouterError`` if
    no session is written."""
    cmd = router_command()
    ses.unlink(missing_ok=True)
    # Settings and log go next to the output, not into the user's home.
    env = dict(os.environ, FREEROUTING__USER_DATA_PATH=str(ses.parent.resolve() / "freerouting"))
    result = subprocess.run(
        [*cmd, "-de", str(dsn), "-do", str(ses), "-mp", str(passes), "-mt", "1",
         "--router.optimizer.max_threads=1", *options],
        capture_output=True, text=True, env=env,
    )  # fmt: skip
    if log is not None:
        log.write_text(result.stdout + result.stderr)
    if result.returncode != 0 or not ses.exists():
        tail = (result.stdout + result.stderr).strip().splitlines()[-20:]
        raise RouterError(f"freerouting exited {result.returncode}:\n" + "\n".join(tail))
    return ses


@dataclass(frozen=True)
class Freerouting:
    """Freerouting, run for at most *passes* passes of its autorouter.

    A run leaves ``<name>.dsn``, ``<name>.ses`` and ``freerouting.log`` in the
    directory it is given, each with ``-<stage>`` after its stem for a named stage.
    """

    passes: int = 100

    def route(self, job: Job, outdir: Path, name: str, stage: str = "") -> Run:
        suffix = f"-{stage}" if stage else ""
        dsn = write_dsn(
            outdir / f"{name}{suffix}.dsn",
            list(job.footprints),
            list(job.outline),
            list(job.netclasses),
            {c: list(nets) for c, nets in job.members.items()},
            edge_clearance=job.edge_clearance,
            hole_clearance=job.hole_clearance,
            only=None if job.only is None else set(job.only),
            fixed=(list(job.wires), list(job.vias)),
            class_clearances=None if job.class_clearances is None else dict(job.class_clearances),
            areas=[(layer, list(poly)) for layer, poly in job.keepouts],
            planes=[(net, layer, list(poly)) for net, layer, poly in job.planes],
        )
        log = outdir / f"freerouting{suffix}.log"
        ses = freerouting(dsn, outdir / f"{name}{suffix}.ses", passes=self.passes, log=log,
                          options=options(job))  # fmt: skip
        wires, vias = read_ses(ses)
        return Run(tuple(wires), tuple(vias), unrouted(log.read_text()))


def options(job: Job) -> list[str]:
    """Freerouting's settings for how *job* is to be routed."""
    fanout_off = job.quick or not job.fan_out
    return [
        *(["--router.automatic_neckdown=false"] if not job.neck_down else []),
        *(["--router.plane_as_obstacle=true"] if not job.cross_planes else []),
        *(["--router.fanout.enabled=false"] if fanout_off else []),
        *(["--router.optimizer.enabled=false"] if job.quick else []),
    ]  # fmt: skip


def unrouted(log: str) -> int | None:
    """How many connections Freerouting's *log* says its autorouter left unmade: None
    when the log does not say."""
    _, completed, after = log.rpartition("Auto-routing stage completed")
    said = re.search(r"\((\d+) unrouted and \d+ violations\)", after) if completed else None
    return int(said[1]) if said else None
