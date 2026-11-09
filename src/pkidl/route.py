"""Run the autorouter: Freerouting on a DSN file, writing an SES file.

Freerouting is run single-threaded, the mode in which 2.5.0 is deterministic for
a given input. ``$FREEROUTING`` overrides the command (default ``freerouting``,
the pinned wrapper that runs the 2.5.0 jar headless).
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path


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
        [*cmd, "-de", str(dsn), "-do", str(ses), "-mp", str(passes), "-mt", "1", *options],
        capture_output=True, text=True, env=env,
    )  # fmt: skip
    if log is not None:
        log.write_text(result.stdout + result.stderr)
    if result.returncode != 0 or not ses.exists():
        tail = (result.stdout + result.stderr).strip().splitlines()[-20:]
        raise RouterError(f"freerouting exited {result.returncode}:\n" + "\n".join(tail))
    return ses
