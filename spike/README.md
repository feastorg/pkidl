# kidl-spike

Generate BREAD KiCad boards from Python — [SKiDL](https://github.com/devbisme/skidl) for
the electrical layer, `pkidl` (under development, in `src/pkidl/`) for the physical layer.

A spike to prove that `Loaf_x004`, `Slice_DCMT` and `Slice_RLHT` — three real boards from
the BREAD thesis platform, currently hand-drawn in KiCad — can be regenerated from
version-controlled Python.

The goal: **KiCad files become build artifacts, not source.** Python is committed;
`.kicad_sch` and `.kicad_pcb` are generated on demand or in CI.

## Quick start

```sh
just setup     # install dependencies
just doctor    # verify the toolchain and library resolution actually work
just test
```

Run `just doctor` first. It checks that KiCad 10 is reachable, that `$KICAD_MASTER_LIB`
resolves, and — critically — that SKiDL can actually pull a real part through the committed
library tables: one from stock KiCad, one first-party, one vendored. Counting library
entries proves nothing; resolving a part proves the toolchain works.

## Requirements

- Python 3.13 and [`uv`](https://docs.astral.sh/uv/)
- KiCad 10 (flatpak by default; set `KICAD_CLI` to override the invocation). The exact
  version is pinned in `src/kidl_spike/doctor.py`; a bump is a reviewed event
- A [KiCad-Master-Lib](https://github.com/feastorg/KiCad-Master-Lib) checkout, found via
  `$KICAD_MASTER_LIB` (defaults to `../../KiCad-Master-Lib`)
- A `../../skidl` checkout, beside the pkidl repo — SKiDL is pinned to a local clone, not taken from PyPI
- [Freerouting](https://github.com/freerouting/freerouting) for the boards that are
  autorouted (the Slices): a `freerouting` command, or `$FREEROUTING` set to one. The version
  is pinned in `src/kidl_spike/doctor.py`; it needs Java 25

`pkidl` (the physical layer) is developed inside this repo, in `src/pkidl/`. It
imports nothing from `kidl_spike`, so it can move to the `pkidl` repo once its
primitives settle.

## Generating a board

```sh
just gen loaf      # write build/loaf/: netlist, schematic, board, project, lib tables
just verify loaf   # generate, then run KiCad's own ERC and DRC against the result
just fab loaf      # Gerbers, drill files and a PDF render into build/loaf/fab/
just verify rlht   # Slice_RLHT, likewise; routed by Freerouting during `gen`
just verify dcmt   # Slice_DCMT, likewise
```

The gates fail on errors only; the full reports (`build/<board>/erc.rpt`, `drc.rpt`) list
warnings too. The generated `.kicad_pro` sets the schematic-parity rules to errors, so a
board that has drifted from its schematic fails DRC instead of passing with a warning.

Everything under `build/` is generated and gitignored. Never hand-edit it — fix the
generator.

KiCad is the authority on correctness: we emit native files and let `kicad-cli` judge them.
Success means the netlist matches the original board's, DRC passes, and the layout is
genuinely manufacturable — *not* that the layout resembles the hand-drawn original.

## Where the thinking lives

- `_planning/01-kidl-spike.md` — the plan, and what's done
- `_working/` — the analysis and evidence behind it
