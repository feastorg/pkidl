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

## Progress

- **Steps 1–3 are done** (#25, #26, #27, #28). Through each, RLHT, DCMT and the Loaf came out identical to `main`: 29 generated files compared at each step.
- **Step 4: Slice_HBTC** (2026-11-09). One H-bridge channel (DCMT's) and two thermocouple channels (RLHT's) on one Nano:
  - ERC 0 errors.
  - DRC 0 errors, 0 unconnected items, 0 parity issues, with `--refill-zones --schematic-parity`. Its warnings are the same kinds as DCMT's.
  - It routes completely in both stages, and the tests show it is byte-stable.
- **Step 5: what it cost.** All counts are of lines in the files that make up HBTC.

| File | Lines | What it is |
|---|---|---|
| `hbtc.yaml` | 39 | The composition: Nano pins, three channels, anchors. No references: all 24 are generated. |
| `hbtc.py` | 53 | Load the YAML, build the circuit. The same shape as `dcmt.py`. |
| `hbtc_layout.py` | 133 | Root spots, netclasses and HS1 vias taken from DCMT; then the build sequence. |
| `tests/test_hbtc.py` | 81 | Nano pins used once, unique references, routed, byte-stable. |
| `check.yml` | +14 | Verify, fab and upload the new board. |

- **What came free:**
  - the circuits of both blocks, and the references;
  - routing, pours, thermal vias, stitching and silk;
  - the DRC rules, and CI.
- **What did not:** about 60 of `hbtc_layout.py`'s 133 lines repeat DCMT's build sequence: place, vias, route, logo, labels, pours, project, rules, references, label. Each Slice layout repeats it because netclasses, pours and labels are still per board in Python. The next step toward "a new Slice is a YAML file" is one Slice build sequence driven by the spec, with netclasses and pours declared per block kind.
- **Found on the way, and fixed (#29):** Freerouting's optimizer ignored `-mt 1`. The same HBTC DSN routed six times gave three different sessions. RLHT and DCMT happened not to vary.
