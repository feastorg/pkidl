# Phase ⑤: Generalize (plan approved 2026-11-09)

Goal, from `01-kidl-spike.md`: boards driven from `slice.yaml`/`loaf.yaml`, KiCad files
not committed, regenerated in CI, and a new Slice variant that falls out almost free.

## Already done

- **KiCad files are build artifacts.** `build/` is gitignored and no `.kicad_*` file is
  committed.
- **CI regenerates every board on every change.** It also verifies them (ERC, DRC with
  parity, the generated rules) and fabricates them (Gerbers, drill, PDF), uploading the
  results. Phase ⑤ adds no CI machinery beyond running the new board.

## What moves into YAML, and what stays in Python

The rule: **YAML says what a board is made of; Python says how a block is built.**

| In YAML (`boards/<name>.yaml`) | Stays in Python |
|---|---|
| Name, format (`slice-s`), source label spot | The Slice format, holes, bus connector (`common.py`, `slice.py`) |
| Channels: block type, channel name, Nano pins, anchor | Block circuits (relay, MAX31855K, LMD18200 bridge) and their part choices |
| Root parts the board keeps (Nano, buck, LED, net tie) | Block placement geometry (`*_BLOCK` spots relative to the anchor) |
| Netclasses and their members; DRC rules that are board data (mains spacing) | Routing stages, pours, vias and silk algorithms (pkidl) |
| Pours, thermal-via fields and HS1 vias, by block | Reference designator assignment: generated per block and channel, deterministic |

Reference designators are written out by hand in the tables today. In YAML they're
generated from block and channel, in a fixed order, unless a channel lists its own
(decided 2026-11-09). `rlht.yaml` and `dcmt.yaml` list theirs, so they keep the
originals' numbering, which the parity tests compare. The new variant uses generated
references only: that's the cheap path it demonstrates. **The two existing boards must
come out byte-identical to `main`, apart from the source label**, before any new
variant is added. That is the regression gate for the refactor.

## Steps (one PR each)

1. **Block registry in Python.** Each block becomes `(circuit fn, layout spots, pours,
   vias, labels)`, and RLHT/DCMT build from lists of block instances. The boards stay
   byte-identical to `main`.
2. **YAML loader**, a typed schema with `dataclasses`; validation errors name the file
   and key. `rlht.yaml` and `dcmt.yaml` replace the Python tables; still byte-identical.
3. **`loaf.yaml`.** The Loaf has no channel blocks: its interface table, outline and
   labels move.
4. **The new variant**: one YAML file, plus whatever the block registry lacks. It must
   pass ERC/DRC with 0 errors, route completely, pass byte stability, and go into CI
   and the artifacts.
5. **Write-up.** What the new variant cost: files and lines touched, and what wasn't free.
6. **A second variant: four thermocouples** (added 2026-11-09). An existing Slice already
   has four thermocouple channels and can serve as the reference to compare against, the
   way the originals do for RLHT and DCMT. Which repository it is gets settled when the
   step starts.

## Decisions (2026-11-09)

- **The plan above is approved as drafted**, with references generated and overridable.
- **The new variant is mixed:** one LMD18200 H-bridge channel (from DCMT) and two
  MAX31855K thermocouple channels (from RLHT) on one Slice. Blocks from two boards share
  a Nano and one routing run. Its Nano pins and placement are worked out in step 4.
- **YAML library:** PyYAML, already a direct dependency (`pyyaml>=6.0` in
  `pyproject.toml`). Nothing to add.

## Not in scope

- Moving pkidl into its own repository (feastorg/pkidl).
- RLHT's step 5 (placement rework).
- New footprints, or new symbols in KiCad-Master-Lib.
