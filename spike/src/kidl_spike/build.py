"""Generate a board: ``python -m kidl_spike.build <name>``.

A board with its own module (``kidl_spike.boards.<name>``: the Loaf, and the Slices
written before the YAML) builds through it; any other Slice is built from
``boards/<name>.yaml`` alone (``slice_build.build``).
"""

from __future__ import annotations

import importlib
import importlib.util
import sys

from kidl_spike.boards import slice_build


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m kidl_spike.build <board>", file=sys.stderr)
        return 2
    name = argv[1]
    if importlib.util.find_spec(f"kidl_spike.boards.{name}") is not None:
        return importlib.import_module(f"kidl_spike.boards.{name}").main()
    outdir = slice_build.build(name)
    print(f"Generated {name} from {name}.yaml into {outdir}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
