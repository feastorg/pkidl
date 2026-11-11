# Test boards beyond BREAD (2026-11-10)

Option 3 of `06-verdict.md`: should we test on boards other than our five, and how?

**Since then (2026-11-11).** Written before the bake-off ran. Two things have changed:

- **Recommendation 1 is done.** The bake-off (#42) restored planes from `reference-routed.dsn` on 3 PCBench boards (gimbal 6, BMS 4, OpenMPPT 9), and they loaded and routed in Freerouting (`07-router-bakeoff.md`). `04-router-bakeoff.md` now says PCBench's MIT covers its code, not the designs.
- **pkidl writes planes** since #44 (`write_dsn(..., planes=...)`). So (b) is no longer blocked on a plane writer.

## Answer

**Yes, but only in the cheap form, and PCBench as it ships doesn't test the crux.**

- Freerouting's PCBench fixtures are the right source for router evaluation.
- Their unrouted DSNs carry no pours, though. I found 0 planes in 15 of 15 sampled.
- The bake-off needs the pours put back before PCBench says anything about pour-aware routing.
- The same fixtures can also test pkidl's DSN writer against KiCad's. That is a cheap test we don't have.
- Full regeneration in SKiDL isn't worth it for any external board today.
- The larger sources (Open Schematics, kicad-happy's corpus) test what pkidl doesn't do: parse and round-trip arbitrary boards.

## What a bigger set would test

| Purpose | What it exercises | Cost per board | Source that fits |
|---|---|---|---|
| (a) Router evaluation | Route someone else's placement and netlist. Judge by unrouted count, DRC, run time, determinism | Minutes of CPU, no authoring | PCBench fixtures |
| (b) pkidl primitives | pkidl's DSN writer, keepouts, fill model and stitching, against KiCad on boards we didn't draw | A small adapter, then seconds | PCBench fixtures (they ship KiCad 10's own DSN of each board) |
| (c) Full regeneration | SKiDL circuit, blocks and layout for the board | "Roughly a phase each" (`06-verdict.md`) | Not worth it now |

**(a)** is what `_planning/04-router-bakeoff.md` already plans.

**(b) is new and cheap.** `pkidl.dsn.write_dsn` takes placed footprint nodes, an outline and netclasses (`src/pkidl/dsn.py:170`). Those are the same s-expressions a `.kicad_pcb` holds. So an adapter can:

1. read a fixture's `unrouted.kicad_pcb`;
2. write pkidl's DSN;
3. diff it against the fixture's `unrouted.dsn`, which KiCad 10.0.2 exported with `pcbnew.ExportSpecctraDSN` (`board-manifest.json`, `conversion_tools`).

The comparison covers pins, padstacks, net membership and the boundary. It needs no KiCad in our loop, which matters for two reasons:

- `kicad-cli` has no DSN export (`kicad-cli pcb export --help` lists 23 formats, none Specctra);
- this sandbox can't run `pcbnew`.

The same boards can feed `stitch.stitch_points` and compare the predicted fill against KiCad's refill (`kicad-cli pcb drc --refill-zones`).

Two gaps first:

- **The fixture boards are KiCad 5 format.** The sample has `(version 20171130)` and `module` nodes, and all 1142 catalog entries have a source version at or below `20220914`. pkidl reads `footprint` nodes only (`footprint.py:109`, `silk.py:160`, `stitch.py:69`). So each board needs `kicad-cli pcb upgrade` first.
- ~~**pkidl's DSN writer emits no `plane`**~~ Closed by #44: `write_dsn` takes `planes`.

**(c) only pays if a board family matters to BREAD.** Regeneration tests SKiDL authoring and our block library, not pkidl or the router. One external power board in SKiDL would cost a phase and prove what HBTC and TC4 already showed: composition works.

**Where the pasted research's parser/round-trip scope fits.** It assumed pkidl verifies "geometry, footprints, … serialization against KiCad" on arbitrary boards. pkidl doesn't load arbitrary boards. It writes boards it assembled. The scope fits in one place: the reader half of (b), the adapter, which must parse real `.kicad_pcb` files. Corpora sized for parser coverage (kicad-happy: 18,751 PCB files; Open Schematics: 87,931 rows) test a reader we don't have and don't plan to make general. A few dozen boards cover the adapter.

## Claims in the pasted research, checked

| Claim | Status | Evidence |
|---|---|---|
| Open Schematics: 87,931 records | True | `datasets-server.huggingface.co/size?dataset=bshada/open-schematics`: `num_rows` 87931 |
| 317 GB | True | Same call: `num_bytes_parquet_files` 316,776,497,910 |
| KiCad + legacy + Altium | Partly | Card: schematics `.kicad_sch`, `.sch`, `.SchDoc`. PCBs only `.kicad_pcb`/`.pcb`: no Altium boards |
| CC-BY-4.0 at dataset level; designs keep their own | True as stated, but unusable | Card says so. No per-row licence, commit or file path: the 10 columns are schematic, images, `pcb_files`, components, JSON/YAML, `name`, description, extensions |
| "PCB data where available" | True, with a defect | 3 rows via `/rows?...&offset=1000&length=3`: 5 PCB strings. 2 end mid-expression at an exact 1 KiB multiple (720,896 and 1,507,328 chars, parens unbalanced). The viewer reports no truncated cells. Whether the parquet holds truncated files is unverified: one shard is about 336 MB (estimate: 316.8 GB over about 940 shards) |
| kicad-happy-testharness: ~5,800 repos pinned in repos.md | True | `repos.md`: 5,820 lines `- URL @ <40 hex>`; README says 5,822. `checkout.py`, `discover.py` exist (`gh api repos/aklofas/kicad-happy-testharness/contents`) |
| "tested over 18,000 PCB files and 36,000 schematic files" | True | kicad-happy README: 18,751 PCB, 36,463 schematic files analyzed. "Tested" means kicad-happy's own analyzers, not KiCad |
| (not claimed) the harness's licence | No licence | `gh repo view`: `licenseInfo` null. The tool, kicad-happy, is MIT |
| Olimex ~158 repos | True | `gh api orgs/OLIMEX`: 158 |
| SparkFun ~1,400, mostly EAGLE | True | 1,492 repos. Code search: 644 `.brd` vs 20 `.kicad_pcb`. Search skips large files, so `.kicad_pcb` is undercounted |
| Adafruit ~2,000, mostly EAGLE | True | 2,053 repos; 491 `.brd` vs 12 `.kicad_pcb`, same caveat |
| KiCad demos: ~18 dirs | True | `gh api repos/KiCad/kicad-source-mirror/contents/demos`: 18 dirs. Freerouting already ships 14 DSN files from them, 4 disabled (`fixtures/KiCad_10_demos`) |
| KiCad Test Boards wiki | Exists; wrong size for us | `gitlab.com/api/v4/projects/kicad%2Fcode%2Fkicad/wikis/Test-Boards`: 7 KiCad boards, 1,624–3,161 pads, multilayer. The rest is importer tests (Altium, CADSTAR) |
| HardLabs, October 2026: 51% of repos lacked a GitHub-detectable licence | Unverified | Two web searches ("HardLabs survey open hardware repositories licence 51% October 2026", `"HardLabs" hardware repositories license survey`) found no such survey. Our own counts below are different numbers from different populations |
| pkidl's scope is parsing and round-tripping arbitrary boards | False | See above |

## PCBench, measured

All from `scripts/benchmark/fixtures/PCBench/catalog.json` in freerouting/freerouting at `842ad83` (2026-11-10). Scripts are in my scratchpad, run with `python3 -I`.

- **1142 boards, not about 1000.** `gh api .../git/trees/<PCBench tree>`: 1144 entries, 1142 directories. The contents API caps a listing at 1000, which is likely where "about 1000" came from.
- **1026 are two-layer; 866 of those have zones** (`board.zones > 0`).
- **Each board ships:** `raw.kicad_pcb` (the original, routed), `unrouted.kicad_pcb`, `unrouted.dsn`, `reference-routed.dsn`, `ground_truth.json`, `board-manifest.json` with sha256s. About 0.8 MB for the sample `kitspace_hbridge_driver`.
- **Every source is KiCad 3 to KiCad 7 era**, converted with KiCad 10.0.2.

**The unrouted DSNs have no pours.**

- 15 two-layer zoned boards drawn at random (seed 20261110): `unrouted.dsn` has a `plane` in 0 of 15, and `unrouted.kicad_pcb` has a zone in 0 of 15. `reference-routed.dsn` has planes in 7 of 15.
- 4 hand-picked power boards: 0 planes in `unrouted.dsn` in all 4.
- Freerouting's `scripts/pcbench/README.md` says the strip "remove[s] segments, vias, and zone fills" and keeps outlines. The committed files don't match that. I haven't found the cause.
- **Consequence for the bake-off:** choosing boards "by layer count and zones" (`04-router-bakeoff.md`) picks boards whose zones never reach the router. Without a fix, the crux isn't tested on any external board.
- **The cheap fix:** copy each board's `plane` statements from `reference-routed.dsn` into `unrouted.dsn`. The bake-off did this on 3 boards; all three loaded and routed.

**Crux candidates.** 97 two-layer zoned boards have a power word (motor, driver, supply, buck, relay, …) in their name or source URL. 48 have planes in `reference-routed.dsn`. Of those, 7 have a permissive SPDX licence in the catalog:

| Board | Licence | Planes | Reference unconnected |
|---|---|---|---|
| bldc-gimbal-1d_gimbal-board (and its r1, a near-duplicate) | MIT | 6 | 0 |
| FRM16_Relay_Module_I2C_Controller_relay_controller | MIT | 1 | 0 |
| makerspace-emonth_load_box | CC-BY-4.0 | 3 | 53 |
| OpAmpPassXsistorBenchSupply | MIT | 9 | 0 (catalog says 0 nets, suspect) |
| Open-Source-Power-Supply_PowerSupply_PCB | MIT | 2 | 0 |
| rufs_spv1040_power_controller | Apache-2.0 | 2 | 0 |

**Ground truth is "a human finished it", not "it's clean".**

- 736 of the 866 zoned two-layer boards have 0 unconnected in KiCad 10 DRC of the original.
- 0 of 866 have 0 DRC errors (`by_severity.error`). Old footprints and rules under KiCad 10 produce clearance and library errors.
- So compare a router against the original by unrouted count and track and via totals, not by DRC passing.

## Is PCBench enough for (a)?

**Yes, once the planes are restored.**

- It has what the others would add: two-layer power boards with pours, and routed originals as reference (`reference-routed.dsn`, `ground_truth.json`).
- It's already DSN, already pinned in a GPL repo we track, and catalogued by layers, zones, licence and tier.

The others add little for routing:

- **KiCad demos:** 14 DSN files (10 enabled) are already in the same fixtures tree.
- **Olimex:** KiCad boards with no DSN or routing reference prepared, and 55 of 158 repos have no detectable licence (40 none, 15 `NOASSERTION`: `api.github.com/orgs/OLIMEX/repos`, two pages).
- **SparkFun, Adafruit:** EAGLE; not worth a converter.
- **kicad-happy, Open Schematics:** no DSN, no routing reference, and in Open Schematics no pin to a commit. Its card calls it "self-growing".

**What would change this:** the crux candidates above being too small or too simple to stress a router. Then the place to look is kicad-happy's "Motor controllers / robotics" and "Power / battery" sections of `repos.md`. They're pinned to commits. Each repo's licence still has to be checked by hand: `repos.md` records none.

## Licensing and redistribution

- **PCBench's MIT licence covers PCBench, not the boards.** The catalog records a licence per board:
  - 612 have an empty licence;
  - 14 say "License not found";
  - 91 are `NOASSERTION`.

  That's 717 of 1142 (63%) with no licence we can rely on. (Rechecked 2026-11-11 from `catalog.json` at `842ad83`: 594 `None` plus 18 empty, 14, 91. Another 117 have no SPDX tag but name a licence with a link; they need reading by hand.) `04-router-bakeoff.md` has since been corrected.
- **No licence means all rights reserved.** Use such boards only by fetching them at test time from the pinned upstream. Never commit them.
- **Permissive (MIT, Apache, BSD, CC0, CC-BY): fixtures may be committed** with the board's licence text and attribution beside them.
- **Share-alike (GPL, CC-BY-SA):** usable locally and fetched at test time. Committing them binds the fixture files to their terms. I wouldn't.
- **Open Schematics' CC-BY-4.0 doesn't relicense the designs**, and the dataset gives no per-row licence to check. Unusable for anything we'd commit.
- I'm not a lawyer. This is the conservative reading. It costs us little, because fetching is cheap.

**So commit a manifest, plus fixtures for permissive boards only.** One row per board:

- `board_id`;
- source URL;
- Freerouting commit (`842ad83…`) and fixture path;
- sha256 of each file used (copied from `board-manifest.json` and re-hashed on fetch);
- KiCad conversion version;
- licence, read from the source repo, not trusted from the catalog;
- the expected outcome we measured.

The pasted research proposed the same manifest fields. That part is right.

## Cost

| Item | Size | Evidence |
|---|---|---|
| PCBench catalog | 1.99 MB | downloaded |
| One fixture board | about 0.8 MB | `kitspace_hbridge_driver`, 7 files |
| 8–15 boards for the bake-off | about 10 MB | estimate from the sample |
| All 1142 fixtures | about 0.9 GB | estimate (1142 × 0.8 MB). Not needed |
| Freerouting clone | 2.4 GB | `gh api repos/freerouting/freerouting --jq .size`. Fetch files raw, never clone |
| Open Schematics | 316.8 GB | above. Rows are reachable through the viewer API; nothing needs downloading |

**Tooling.** No new tools:

- fetch with `curl` over raw URLs, verify sha256;
- `kicad-cli pcb upgrade` for (b);
- Freerouting for (a), already pinned.

**CI.** The suite already takes about 7 minutes.

- **Router runs stay out of `just test`.** At 30 s–3 min per route (`04-router-bakeoff.md` estimate), 8 boards would add 4–24 minutes. Put them in a separate recipe, run on demand or nightly.
- **(b) can go in `just test`** if it stays per board in seconds. That is plausible for a pure-Python DSN write and diff, but unmeasured.

**Environment finding.** `kicad-cli-session pcb upgrade` returns exit 3, "Board file does not exist or is not accessible", on a scratchpad path: the flatpak doesn't see the scratchpad. On an absolute path under the repo's `build/` it works ("Successfully saved board file using the latest format", 7 of 7 bake-off boards, 2026-11-10).

## Recommendation

In order:

1. **Done in #42.** **Fix the bake-off's external boards now, before it runs** (smallest useful step). Take the 6 distinct permissive crux candidates above. Restore their planes from `reference-routed.dsn` into `unrouted.dsn`, and check the result loads in Freerouting. Correct "The corpus is MIT-licensed" in `04-router-bakeoff.md`. Without this, the bake-off's external half can't answer question 1.
2. **Add the manifest** under `tests/fixtures/external/`, pinned to Freerouting `842ad83`. Commit fixtures only for permissive boards.
3. **Next: the plane writer landed in #44, so build the (b) adapter:** upgrade, read, `write_dsn`, then diff against KiCad's `unrouted.dsn` on the same 6 boards. Then grow it to about 30 zoned two-layer boards across licences, fetched at test time.
4. **Leave out** Open Schematics, kicad-happy's corpus, SparkFun and Adafruit, and full SKiDL regeneration of external boards.

**What would change my mind:**

- **Restored planes don't load, or give nonsense.** Then the crux on external boards waits for pkidl's plane writer, and step 1 merges into step 3.
- **The six candidates route trivially for every router.** Then add larger power boards: from the 48 with planes regardless of licence (fetched, not committed), or from kicad-happy's power section.
- **pkidl graduates and claims to load arbitrary boards.** Then a parser corpus earns its place, and kicad-happy's pinned list is the one to use. Open Schematics is not: it has no commits, no paths, and samples that look truncated.
