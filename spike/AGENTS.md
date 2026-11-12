# AGENTS.md

Instructions for AI coding agents working in this repository.

## Project

`kidl-spike` regenerates three real BREAD boards — `Loaf_x004`, `Slice_DCMT`, `Slice_RLHT`
— from Python instead of hand-drawing them in KiCad. It uses **SKiDL** for the electrical
layer and **pkidl** (new, under development) for the physical layer.

The end state: **KiCad files are build artifacts, not source.** Python is committed;
`.kicad_sch` / `.kicad_pcb` are generated in CI or on demand.

pkidl lives at the repository root (`../src/pkidl`), and its rules in `../AGENTS.md`
apply here too. In particular, a board is written from its circuit and mechanical
requirements, never from a reference board's layout. DCMT's `dcmt_copper.py` and
`scripts/extract_dcmt_copper.py` predate that rule: they copy the original's copper and
are to be replaced by pkidl intent (`../docs/charter.md`), not extended.

Planning lives in `_planning/`; evidence and analysis in `_working/`. Read
`_planning/01-kidl-spike.md` first.

## Stack

- **Python 3.13**, managed with `uv` (`.python-version` pins it)
- **SKiDL** — consumed from the sibling `../../skidl` checkout, **pinned**, not from PyPI.
  Pinned to release 2.3.0 and its `kicad10` backend (`SKIDL_REF` in CI; the sibling
  checkout is detached at that tag). A bump is a reviewed PR, gated by `tests/test_loaf.py`.
- **KiCad 10** — flatpak locally; `KICAD_CLI` overrides the invocation. The exact version is
  pinned in `doctor.py` (`WANT_KICAD`); a bump is a reviewed event, not an auto-update
- **KiCad-Master-Lib** — via `$KICAD_MASTER_LIB`; supplies every non-stock symbol/footprint
- **Freerouting** — the autorouter for the Slices, run on a DSN pkidl writes. A `freerouting`
  command or `$FREEROUTING`; version pinned in `doctor.py` (`WANT_FREEROUTING`), jar sha256
  in CI. Needs Java 25. Runs single-threaded, where its output is deterministic
- **ruff** (format + lint), **pyright** (types), **pytest**

## Layout

```
src/kidl_spike/
    libs.py      # library resolution — the reproducibility boundary
    doctor.py    # environment check; run this before trusting any output
    boards/      # one module per board (+ <board>_layout.py for the physical layer);
                 # common.py: the bus pinout, the Slice format, shared parts, the build;
                 # slice.py: Slice placement, routing and pours
tests/
build/           # GENERATED. Gitignored. Never hand-edit.
```

## Commands

```sh
just setup        # install dependencies
just doctor       # verify toolchain + library resolution actually work
just fmt          # format
just check        # fmt-check + lint + typecheck (CI-equivalent)
just test         # run tests
just gen loaf     # generate a board's KiCad files into build/
just verify loaf  # generate, then run KiCad's own ERC + DRC against the result
just fab loaf     # Gerbers, drill, PDF render into build/loaf/fab/
just gen rlht     # Slice_RLHT; routing runs Freerouting during gen
just gen dcmt     # Slice_DCMT, likewise
just gen tc4      # a Slice with no module: built from boards/tc4.yaml alone
```

A new Slice is a YAML file in `src/kidl_spike/boards/`: a root layout (`root: rlht` or
`root: dcmt`) and its channels (`relay`, `thermocouple`, `bridge`, `encoder`), each with
its Nano pins and anchor. `kidl_spike.build` builds it through `slice_build`; references
are generated unless a channel lists its own. See `rlht.yaml`, `dcmt.yaml`, `tc4.yaml`.

Where a recipe cannot start KiCad, as in a sandboxed agent session that reaches it only
through a wrapper of its own, `just erc`/`drc`/`verify`/`fab` do not run: call that
wrapper directly with the arguments the recipe uses.

## Conventions

- Run `just check && just test` before every commit. Never `--no-verify`.
- Conventional Commits: `type(scope): description`.
- **Always call `libs.configure_skidl()` before any `Part()` lookup.** Without it SKiDL
  silently falls back to the developer's global KiCad config, which is exactly the
  non-reproducibility this project exists to eliminate.

## Constraints

- **Never modify `../../Loaf_x004`, `../../Slice_DCMT`, `../../Slice_RLHT`.** They are read-only
  reference. Generated output is *compared* against them; the originals are never touched.
- **Never hand-edit anything under `build/`.** It is generated. Fix the generator.
- Do not resolve libraries through the global KiCad config, or by hardcoding paths.
  Everything goes through `libs.py` and the tables committed in KiCad-Master-Lib.
- Do not unpin SKiDL. A library silently changing the netlist we generate is the precise
  failure mode this project exists to prevent.

## Gotchas

- **SKiDL writes schematics to the current working directory**, ignoring the output path
  you pass. Generation code must account for this.
- SKiDL looks for a file named exactly `fp-lib-table`. Ours is committed as
  `kmlib.fp-lib-table`, so `libs.write_fp_lib_table()` materialises a standard-named one
  into `build/kicad-env/`.
- KiCad's **`footprint_symbol_mismatch` DRC rule defaults to `warning`, not `error`** — so
  a schematic/PCB footprint mismatch will pass a default DRC run. Set severities
  explicitly; do not assume DRC is checking what you think it is. Generated projects do
  this through `pkidl.project.PARITY_ERRORS`.
- **A netclass width is a default, not a minimum.** KiCad passes a track narrower than its
  class. Minimums, mains spacing and hole keepouts live in the generated `<board>.kicad_dru`
  (`pkidl.project.write_rules`). KiCad's zone fill honours those rules too, so a refilled
  pour keeps out of the keepouts on its own.
- **A part with no pins crashes SKiDL's schematic placer** (F-019). Mounting holes go on
  the board as board-only footprints (`Placement(board_only=True)`), not into the circuit.
- **SKiDL's two-pin snap drops net labels**, and KiCad then renames those nets `Net-(...)`,
  so the board's pad nets no longer match (F-020). `common.generate` holds the workaround: every
  net stubbed, the snap switched off for the `generate_schematic` call. Each no-connect pin
  also needs KiCad's own net name on its pad, `unconnected-(<ref>-<pin name>-Pad<n>)`.
