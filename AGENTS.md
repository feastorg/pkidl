# AGENTS.md

Instructions for AI coding agents working in this repository.

## Project

`kidl-spike` regenerates three real BREAD boards — `Loaf_x004`, `Slice_DCMT`, `Slice_RLHT`
— from Python instead of hand-drawing them in KiCad. It uses **SKiDL** for the electrical
layer and **pkidl** (new, under development) for the physical layer.

The end state: **KiCad files are build artifacts, not source.** Python is committed;
`.kicad_sch` / `.kicad_pcb` are generated in CI or on demand.

Planning lives in `../_planning/`; evidence and analysis in `../_working/`. Read
`../_planning/00-prereqs.md` first.

## Stack

- **Python 3.13**, managed with `uv` (`.python-version` pins it)
- **SKiDL** — consumed from the sibling `../skidl` checkout, **pinned**, not from PyPI.
  Upstream has no KiCad 10 backend and we expect to carry patches.
- **KiCad 10.0.4** — flatpak locally; `KICAD_CLI` overrides the invocation
- **KiCad-Master-Lib** — via `$KICAD_MASTER_LIB`; supplies every non-stock symbol/footprint
- **ruff** (format + lint), **pyright** (types), **pytest**

## Layout

```
src/kidl_spike/
    libs.py      # library resolution — the reproducibility boundary
    doctor.py    # environment check; run this before trusting any output
    boards/      # one module per board
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
```

## Conventions

- Run `just check && just test` before every commit. Never `--no-verify`.
- Conventional Commits: `type(scope): description`.
- **Always call `libs.configure_skidl()` before any `Part()` lookup.** Without it SKiDL
  silently falls back to the developer's global KiCad config, which is exactly the
  non-reproducibility this project exists to eliminate.

## Constraints

- **Never modify `../Loaf_x004`, `../Slice_DCMT`, `../Slice_RLHT`.** They are read-only
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
  explicitly; do not assume DRC is checking what you think it is.
