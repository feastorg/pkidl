# Verdict: can BREAD boards be generated from Python? (2026-11-10)

## Answer

**Yes for circuits, placement and logic-level routing; not yet for power layout.**

- **Circuits:** generated netlists match the originals.
- **Physical layer:** boards come out manufacturable and pass KiCad's own checks.
- **New Slices:** one built from existing blocks is a YAML file.
- **Power copper:** a two-layer board carrying amps still needs a designer's decisions. Which layer each power net owns, where the pours go, how they stitch. The autorouter doesn't make those decisions. It can respect them once given (a pour as a plane that blocks other nets, found 2026-11-10), so the decisions have to come from a designer, as data.

The end state the spike set out for is reached. KiCad files are build artifacts: Python and YAML are committed, and CI regenerates, checks and fabricates every board on every change.

## The evidence

**The boards** (`main` at `cd22f17`, five boards):

| Board | Source | Netlist vs the original | DRC errors | Unconnected |
|---|---|---|---|---|
| Loaf_x004 | `loaf.py` + `loaf.yaml` | matches (`test_loaf.py::test_netlist_matches_original`) | 0 | 0 |
| Slice_RLHT | `rlht.yaml` + blocks | matches (`test_rlht.py`) | 0 | 0 |
| Slice_DCMT | `dcmt.yaml` + blocks | matches (`test_dcmt.py`, also parts, hierarchy, no-connects) | 0 | 0 |
| Slice_HBTC (new) | `hbtc.yaml` + a 16-line layout | no original | 0 | 0 |
| Slice_TC4 (new) | `tc4.yaml` only, 32 lines | no original | 0 | 0 |

DRC: `kicad-cli pcb drc --refill-zones --save-board` on fresh builds, 2026-11-10. The warnings that remain, by kind:

| Board | Warnings |
|---|---|
| Loaf | silk 76 |
| RLHT | silk 39, mains spacing 57, track width 2 |
| DCMT | silk 43, track width 9, hole 1 |
| HBTC | silk 40, track width 8, hole 1 |
| TC4 | silk 35, track width 4 |

- **Silk:** mostly inherited (`05-board-review.md` §8).
- **Mains spacing:** RLHT's 57 come partly from the circuit (Slice_RLHT#90) and partly from routing under the relays.

**The code:**

- pkidl: 1713 lines (`wc -l src/pkidl/*.py`).
- The BREAD board layer: 2158 lines of Python and 184 of YAML.
- Merged PRs: 37.
- Tests: 87 pass and 9 skip (KiCad-only checks that CI runs), in 6 min 36 s locally (`just test`, 2026-11-09).

**What pkidl does now:**

- Footprint placement, project files and generated DRC rules (class minimum widths, mains spacing, hole keepouts, silk on copper).
- Canonical, byte-stable DSN.
- Two-stage routing through Freerouting:
  - power first, at full width;
  - signals second, around it.

  Output is identical across runs (`--router.optimizer.max_threads=1`, #29).
- Pours, keepouts and rule areas.
- Thermal vias at fixed positions.
- GND stitching that predicts each layer's fill.
- Reference placement.

## What works

- **Logic and low-current boards.** The Loaf at its 5 A budget, TC4, and the logic side of every Slice come out clean, with nothing a reviewer had to fix by hand.
- **Composition.** HBTC (an H-bridge and two thermocouples) and TC4 (four thermocouples) were new boards built from the existing blocks. TC4 needed no Python at all.
- **Composition needs blocks to carry their electrical context, not just their parts.** HBTC first came out with its thermocouples over the motor ground. Each thermocouple block now brings its own ground region and keepouts (#36), and the same pattern applies to any sensitive block.
- **Determinism.** Two builds of a board are byte-identical, DSN, SES and board alike. The tests check it on every Slice.

## What doesn't, and why

**As we drove it, the autorouter didn't know the pours existed, and on a two-layer power board that is the whole problem.** pkidl gave Freerouting every net as tracks to route. Pours added afterwards filled around whatever the tracks left, so other nets' tracks cut the power pours into pieces. Measured on DCMT (`05-board-review.md`, phase ⑤½):

| Attempt | Result |
|---|---|
| Pours as Freerouting `plane`s | Gives the plane's own net its connectivity, but with the default settings other nets still route across it. 15 connections left unrouted. *Corrected 2026-11-10:* that is a setting, `plane_as_obstacle` (default false). With it on, no foreign track enters the plane (the original's CH1 VS pour on our DCMT; without it, +12V crosses). |
| Power classes on one layer (`use_layer`) | 9 connections left unrouted. |
| Pours as keepouts for other nets | 22 unrouted: the outlines cover other nets' pins. |
| +12V trunk sized for both channels (6 A, IPC-2221) | 3.6 mm leaves 15 unrouted, 2.5 mm leaves 5, 2.0 mm leaves 6. |

So DCMT ships with a 1.4 mm +12V trunk (about 3 A against a 6 A need) and its GNDPWR pour in three pieces. The original solves it by hand: +12V as a pour on both layers with 184 vias, and GNDPWR as one board-wide B.Cu pour (2306 mm²). That is a layer plan. With `plane_as_obstacle`, Freerouting can route around one; it can't make one.

**"0 DRC errors" was weak evidence at every stage.** It was true of every board throughout, and it hid:

- tracks necked to half their class width;
- pours under a hot tab;
- labels off the board;
- a sense line under thermocouple inputs.

What caught them was writing rules for what mattered and gating on them, plus looking at the boards: two reviews with renders and coordinates.

**The two reviews found real defects that every automated check passed.** A generated board needs the same review a drawn one does, at least until the rules cover what the reviews keep finding.

## What it cost

- **Test time.** The suite takes about 7 minutes, mostly routing; deterministic routing runs single-threaded.
- **Workarounds, each recorded:**
  - **SKiDL**, pinned at 2.3.0: its schematic placer crashes on pinless parts (F-019) and its two-pin snap drops labels (F-020). Two other bugs we reported are fixed on SKiDL's master, not yet released (skidl#331, skidl#332).
  - **Freerouting:** a startup error from `FREEROUTING__USER_DATA_PATH` (freerouting#1109, fixed on master as `a3b36e3`, not yet released) and output varying with optimizer threads.
- **My own corrections.** Several of my claims needed correcting:
  - the necking cause in phase ③;
  - the pour claims in phase ④;
  - one line count.

  Each is recorded where it was made. Mutation tests (break the thing, watch its test fail) and byte-identity gates were the checks that held.

## Options from here

These aren't exclusive. My assessment of each:

1. **Designer-authored power copper per block.** A block carries its power pours, wide tracks and via fields as data, drawn once and placed with the block. The router routes only signals, around fixed copper, which pkidl already supports (fixed vias and wiring, keepouts, protected stages).
   - **For:** it attacks exactly the measured limit, and keeps blocks reusable. The router side exists: authored pours go into the DSN as planes with `plane_as_obstacle` on.
   - **Against:** someone draws each block's power layout once, and the layer plan for the bus and supply between blocks is still per board.
   - **Cost:** moderate. DCMT's bridge block is the test case: its +12V and GNDPWR back to one piece each.
2. **Graduate pkidl** into feastorg/pkidl, with kidl-spike as the BREAD generator.
   - **For:** pkidl already imports nothing from kidl_spike.
   - **Against:** its API is still moving with every fix. Graduating before option 1 fixes an API that option 1 will change.
   - **When:** after option 1, or whichever option is next.
3. **Expand the reference set beyond BREAD** with open-hardware KiCad boards.
   - **For:** five boards from one family and one form factor say little about generality.
   - **Cost:** two different exercises at very different prices:
     - **routing someone else's board** (their placement and netlist, exported to DSN, judged by DRC) is cheap, and tests the router and our DSN path;
     - **regenerating** one needs its circuit written in SKiDL, roughly a phase each.
   - **For router evaluation:** the cheap form, which is what Freerouting's own PCBench does.
4. **Compare routers.** The DSN/SES boundary and the byte-comparison tooling make a bake-off cheap: the same DSNs through each router, judged by DRC and our unrouted counts.
   - **Caveat:** fastroute is a port of Freerouting, so it likely behaves the same way with pours. That's an inference, not measured.
   - **Router survey:** `04-router-research.md` is from 2026-10-23 and the field moves fast, so it needs a fresh pass first.
   - **Best answers:** whether our limits are Freerouting's or every router's.
5. **Commit to Freerouting upstream.**
   - **For:** #1109 went from report to merged fix in under two days (opened 2026-11-08 18:43, closed 2026-11-10 09:40 UTC). Candidate reports, none yet reproduced on a minimal DSN:
     - neck-down narrowing along whole straights, where the setting's own doc says it lowers the width "at static pins";
     - a fixed via inside a same-net pad counted as a violation.

     A third candidate, a plane not keeping other nets out, turned out to be the `plane_as_obstacle` setting: the reason every candidate is checked against the source first.
   - **Against:** Freerouting 2.5 builds on Java 25, and this machine has a Java 25 runtime but only a Java 21 compiler (`/usr/lib/jvm`, 2026-11-10). Building it here needs a JDK 25 added to the machine's managed tooling.
   - **Cost:** filing issues with our reproductions is cheap; fixing them is a Java codebase of its own.

**My recommendation:** option 1 next, on DCMT's bridge block, since it's the only option that changes what the boards can be. Alongside it, file the Freerouting gaps that survive a minimal reproduction (the cheap half of option 5) and run a small bake-off (option 4) on our five DSNs plus a few external boards (the cheap half of option 3). Those answer whether to invest in a router at all. Graduate pkidl (option 2) once option 1 has settled its API.

## Decision (2026-11-10)

**Option 1 next, on DCMT's bridge block.** Then, alongside or after it:

- **The router bake-off (options 3 and 4) is required.**
- **Freerouting issues are filed only once each gap is confirmed:**
  - reproduced on a minimal DSN;
  - checked against the Specctra spec and Freerouting's own docs and issues;
  - shown to be a defect rather than intended behaviour.

  This is the start of a working relationship with that project, so every report has to stand up.

pkidl graduates after option 1 has settled its API.
