# kidl-spike

Generate BREAD KiCad boards from Python — [SKiDL](https://github.com/devbisme/skidl) for
the electrical layer, `pkidl` (under development) for the physical layer.

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
- KiCad 10.0.4 (flatpak by default; set `KICAD_CLI` to override the invocation)
- A [KiCad-Master-Lib](https://github.com/feastorg/KiCad-Master-Lib) checkout, found via
  `$KICAD_MASTER_LIB` (defaults to `../KiCad-Master-Lib`)
- A sibling `../skidl` checkout — SKiDL is pinned to a local clone, not taken from PyPI

`pkidl` (the physical layer) is **not a dependency yet** — SKiDL (the electrical
layer) is wired in first. It lives in the sibling `../pkidl` checkout and is its
own early-stage library; this spike will depend on it once it has content.

## Generating a board

```sh
just gen loaf      # write build/loaf/*.kicad_sch, *.kicad_pcb
just verify loaf   # generate, then run KiCad's own ERC and DRC against the result
```

Everything under `build/` is generated and gitignored. Never hand-edit it — fix the
generator.

KiCad is the authority on correctness: we emit native files and let `kicad-cli` judge them.
Success means the netlist matches the original board's, DRC passes, and the layout is
genuinely manufacturable — *not* that the layout resembles the hand-drawn original.

## Where the thinking lives

- `../_planning/01-kidl-spike.md` — the plan, and what's done
- `../_working/` — the analysis and evidence behind it
