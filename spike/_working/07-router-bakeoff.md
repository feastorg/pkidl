# Router bake-off (2026-11-10)

Plan: `../_planning/04-router-bakeoff.md`.

## Answer

1. **No router keeps a pour in one piece while routing across it.**
   - Freerouting with `plane_as_obstacle` keeps DCMT's pours intact, but leaves 17 connections unconnected.
   - Every other router connects all or most of the board by cutting the pours into pieces.

   Pour-aware routing isn't available off the shelf. Power layout stays a designer's job, or becomes something to build.
2. **Freerouting 2.5.0 stays pkidl's router.**
   - It's the only router that completes all four of our Slices, and 5 of the 7 external boards.
   - Every run is deterministic.
   - It's the slowest of the field, and timed out at 10 minutes on the largest board.
3. **fastroute is the runner-up, and worth watching.**
   - It's faster: a median of 4× over Freerouting with one start (range 1.1–25×), and 5× at its defaults.
   - It was deterministic in 22 of 23 repeated pairs.
   - It completes the large board Freerouting couldn't.
   - It routes the hardest board better (17 open against 26).
   - It leaves 2–3 connections open on our DCMT and HBTC.
4. **The others fall short.**
   - rpmroute and OpenRoute leave connections open, or route with clearance errors.
   - copperline couldn't read any of our inputs.

## Setup

| Router | Version | Built from |
|---|---|---|
| Freerouting | 2.5.0, the pinned jar | — |
| fastroute | v0.1.14 (`19c3b75`) | `cargo build --release --locked` |
| rpmroute | 2026.10.7 (`08a7ac7`) | `uv sync --frozen` |
| OpenRoute (openpcb) | 0.1.0 (`7600571`) | `npm install --ignore-scripts`, `tsc`. The lockfile is out of sync with `package.json` (it lacks `@openpcb/schematic`), and `tsc` reports 8 missing-`@types/node` errors but emits the CLI. |
| copperline | v0.1.0 (`4ce0908`) | `cmake -G Ninja`, Release |

**Run settings:**
- Each router runs single-threaded where it allows it, with its documented options only, capped at 600 s.
- **Freerouting:** `-mt 1 --router.optimizer.max_threads=1 --router.autorouter.max_passes=100`. A second variant adds `--router.plane_as_obstacle=true`.
- **fastroute:** a second variant at its defaults, four parallel starts.
- Every board runs twice, to check determinism.

**Boards (15):**
- **Our four Slices:** the built DSN with stage-one wires dropped, so every net routes in one stage.
- **The DCMT crux:** the original DCMT's power copper, filled by KiCad on our board, given as planes, plus its power tracks fixed (phase 6, step 0).
- **7 PCBench boards:** from Freerouting's fixtures at `842ad83`. They're used locally and not committed, because each keeps its own licence.
- **3 of those with planes:** PCBench's unrouted DSNs carry no pours, so their planes are restored from `reference-routed.dsn` (gimbal 6, BMS 4, OpenMPPT 9).

## Completion

Connections left open (0 = complete), from run 1, with its time. † marks the one run that differed byte-for-byte from its repeat. Every other pair was identical.

| Board | Freerouting | FR, planes as obstacles | fastroute, 1 start | fastroute, default | rpmroute | OpenRoute |
|---|---|---|---|---|---|---|
| RLHT | 0 (13 s) | 0 (11 s) | 1 (11 s) | 0 (5 s) | 0 (11 s) | 79 (450 s) |
| DCMT | 0 (16 s) | 0 (16 s) | 3 (10 s) | 3 (3 s) | 1 (120 s) | 4 (31 s) |
| HBTC | 0 (46 s) | 0 (41 s) | 2 (10 s) | 2 (3 s) | 5 (115 s) | 5 (58 s) |
| TC4 | 0 (32 s) | 0 (27 s) | 0 (8 s) | 0 (3 s) | 1 (11 s) | 0 (1 s) |
| DCMT crux (pours as planes) | 1 (107 s) | 18 (278 s) | 2 (32 s) | 1 (18 s) | 2 (124 s) | 0 (10 s) |
| Brushless ESC | 0 (53 s) | 0 (50 s) | 0 (15 s) | — | 7 (40 s) | 0 (2 s) |
| C-BISCUIT buck | 0 (31 s) | 0 (31 s) | 0 (5 s) | — | 0 (3 s) | 0 (14 s) |
| DualLM317BenchSupply | 0 (5 s) | 0 (6 s) | 0 (0 s) | — | 0 (5 s) | 3 (2 s) |
| OpenMPPT | 0 (96 s) | 0 (96 s) | 8 (12 s) | — | 1 (69 s) | 8 (82 s) |
| arduino-led-driver | timeout (600 s) | timeout (600 s) | 0 (88 s) † | — | 2 (120 s) | 0 (4 s) |
| bldc-gimbal-1d | 0 (94 s) | 0 (97 s) | 0 (14 s) | — | 1 (19 s) | 0 (1 s) |
| free-of-charge BMS | 26 (213 s) | 26 (217 s) | 24 (54 s) | 17 (181 s) | 12 (224 s) | 59 (550 s) |
| OpenMPPT + planes | 2 (16 s) | 7 (22 s) | 2 (8 s) | 2 (7 s) | 1 (57 s) | 1 (67 s) |
| bldc-gimbal-1d + planes | 0 (164 s) | 51 (9 s) | 0 (12 s) | — | 1 (20 s) | 0 (1 s) |
| free-of-charge BMS + planes | 22 (162 s) | 228 (34 s) | 16 (53 s) | 16 (122 s) | 12 (239 s) | 58 (552 s) |

**OpenRoute exits 1** on 18 runs. Its CLI returns 1 when any connection is routed with conflicts, so its routes carry clearance violations of its own count (2 on the crux).

### How "open" is counted, and how far to trust it

- **The checker.** `connectivity.py` reads the DSN and SES with pkidl's s-expression parser and the pads from the KiCad board. It joins:
  - pads, using their real size and rotation;
  - track segments, end to segment, and segments crossing pads;
  - vias, with their radius;
  - plane polygons.

  It counts, per net, the pad groups beyond one.
- **Validated:**
  - all 7 routed PCBench originals come out at 0;
  - every unrouted DSN comes out at its full count (55–280);
  - our built DCMT comes out at 0.
- **Against KiCad's DRC** (unconnected items, board with the router's tracks, floating vias removed), on 5 results:

  | Result | KiCad | Checker |
  |---|---|---|
  | Freerouting DCMT | 0 | 0 |
  | OpenRoute TC4 | 0 | 0 |
  | rpmroute HBTC | 4 | 4 |
  | OpenRoute DCMT | 1 | 0 |
  | fastroute DCMT | 3 | 2 |

  The two differences are KiCad counting a dangling track-and-via fragment, and the net tie NT1's custom pad. **Treat the table as accurate to about ±1 per board.**
- **Getting there took three fixes** to the checker, each caught by a control:
  - net names with parentheses;
  - a 0.8 mm point model of pads, which wrongly failed fastroute on large pads;
  - via radius ignored.

## The crux: do the pours survive?

**Method.** Each router's crux result is put on the pre-filled DCMT. KiCad refills it and runs DRC (`--refill-zones --severity-all`). I then count the pieces of each pour net. "Before" is the fill with only the fixed power tracks.

| | Unconnected | +12V B.Cu / F.Cu | CH1_VS | CH2_VS | GNDPWR B.Cu | Other errors |
|---|---|---|---|---|---|---|
| Before routing | — | 2 / 2 | 1 | 1 | 2 | — |
| FR, planes as obstacles | 17 | **2 / 2** | **1** | **1** | **2** | starved thermal 1 |
| Freerouting | 7 | 3 / 4 | 5 | 3 | 4 | starved thermal 2 |
| fastroute, default | 12 | 3 / 4 | 2 | 1 | 4 | starved thermal 1 |
| fastroute, 1 start | 11 | 3 / 6 | 2 | 1 | 4 | starved thermal 1 |
| rpmroute | 2 | 3 / 4 | 3 | 3 | 6 | clearance 52, starved thermal 4 |
| OpenRoute | **0** | 4 / 4 | 5 | 3 | 6 | clearance 6, hole clearance 7, starved thermal 5 |

The two ends of the trade:

- **Pours as obstacles:** the pours are kept whole, and 17 connections are left. They are the Nano-to-LMD18200 signals, which have no way through (phase 6, step 0).
- **Pours crossable:** connectivity comes back, and the pours fragment. GNDPWR goes from 2 pieces to 4–6, and CH1_VS from 1 to 2–5.

**Nobody does both.** None of the projects claims to. copperline, which treats foreign pours as obstacles, would sit on the first side, but it couldn't be run.

## copperline: not run

It read none of the four input forms we have:

| Input | Error |
|---|---|
| pkidl's DSN | `DSN: image 'C1' has no pin '2'` |
| KiCad's exported DSN | `DSN: missing (structure (boundary ...)) extents`. It reads `(boundary (rect\|polygon))`, not KiCad's `(boundary (path ...))` (`src/dsn.cpp:375`). With the boundary renamed: `pin 'C1-1' names an unplaced component`. |
| KiCad 5 boards | Loads, but `"terminals":0`: it reads no pads from `module` nodes |
| KiCad 10 boards | `bad number '<net name>' in pad net`. It parses `(net N "name")`, and KiCad 10 pads write `(net "name")` (`src/kicad.cpp:304`). That covers 7 boards upgraded by `kicad-cli pcb upgrade` and 4 written by pkidl. |

I stopped there. Converting formats further would have tested my converter, not the router.

## Candidate upstream reports (not filed)

Each one is filed only after a minimal reproduction and your approval. The Freerouting one waits on a run of the `master` snapshot (decided 2026-11-10).

1. **Freerouting: a fixed via inside a plane of its own net counts as a clearance violation when `plane_as_obstacle` is on.**
   - **Reproduction:** `build/bakeoff/repro/via-in-plane.dsn`, 50 lines: one GND plane, two GND pads, one fixed GND via.
   - **With the flag on, 2.5.0 reports:** `ObstacleArea#2 [net GND] <-> FixedVia#5 [net GND]`.
   - **Controls:** with the flag off, no violation; with the via outside the plane, no violation.
   - **On DCMT:** 678 violations before routing with the flag, 53 without.
   - **Fixed on `master`; not filed.** Checked 2026-11-10 on the snapshot jar built from `842ad83` (`freerouting-SNAPSHOT-20261110_153900.jar`):
     - `via-in-plane.dsn` reports no violation;
     - a control, `via-foreign-in-plane.dsn` with the via on another net, reports `FixedVia#5 [net SIG] <-> ObstacleArea#2 [net GND]`.

     The fix is after 2.5.0 and not yet in a release; likely the same change as `098f5f2`'s pin fix. Pinning the next release removes it here.
2. **copperline: KiCad 10 boards and KiCad's DSN boundary can't be read.** Confirmed in the source (above). *Filed 2026-11-10 as iamdarshg/copperline#50*, with an upgraded public PCBench board as the reproduction.
3. **fastroute: why it leaves 2–3 open on DCMT and HBTC** where Freerouting completes (it claims Freerouting parity). Not investigated. Its own `--report` lists them, so `--diagnose` is the next step.

## What it means for the plan

- **Keep Freerouting 2.5.0** and the two-stage routing. Nothing here routes our boards better.
- **Re-run fastroute when it moves.** It's the only candidate that beats Freerouting on any board, and it's fast enough to make the test suite quicker. A `--diagnose` look at our DCMT comes before any switch.
- **Power layout:** the crux needs either the designer's crossings as data (phase 6's "authored crossings"), or a router that weighs pour integrity while routing, which no project has.

## Reproducing

Everything lives under `build/bakeoff/` (generated, untracked):

- `runner.py`: the runs;
- `evaluate.py` with `connectivity.py`: the completion table;
- `assemble.py` and `kicad-cli pcb drc`: the KiCad checks;
- `pieces.py`, in the session scratchpad: the pour pieces.

The candidates are cloned and built under `build/bakeoff/<name>/`.

## Decision (2026-11-10)

**Authored crossings.** Blocks and roots carry their pours plus designer-chosen corridors where signals may cross a pour. The router treats pours as obstacles everywhere else. This revises phase 6 (`../_planning/03-block-power-copper.md`).
