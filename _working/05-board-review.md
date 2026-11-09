# Generated-board review: Loaf, Slice_RLHT, Slice_DCMT (2026-11-08)

## Scope and method

- **Boards reviewed.** I reviewed the three boards exactly as CI built them on PR #14's merge commit (`df2ba7e`), using the run 42390244039 artifacts. I filled them with KiCad 10.0.6 (`pcb drc --refill-zones --save-board`) and compared them with the originals at the same coordinates.
- **Images.** I rendered each board at 40 px/mm and cut it into tiles of about 25 × 27 mm, each labelled with its coordinates, 128 tiles in all:
  - Unfilled copper on both layers.
  - Filled front with front silk.
  - Filled back with back silk.
  - Silk with fab and courtyards.
  - The original's filled copper (Slices only).
- **Reviewers.** Six read-only reviewers worked to one checklist ([05-board-review-procedure.md](05-board-review-procedure.md)): four covering half a Slice each, one covering the Loaf, and one on the routing pipeline (the DSN, Freerouting 2.5.0's bytecode and our code). Their raw reports and the tiles stay in `build/review/` (generated, untracked).
- **Measurements.** Every reported number was measured with a query tool or with scripts over the board files. Sub-reports mark visual estimates.
- **My checks.** I independently re-measured the headline findings (session scripts, not tracked). Each claim below marked ✔ was re-measured by me.
- **Not covered.**
  - Copper weight: no stackup is set, and current figures assume 1 oz with a 10 °C rise.
  - Solder mask and tenting.
  - 3D and mechanical fit with the case.
  - Anything electrical beyond layout.

DRC reports 0 errors on all three boards. Almost everything below is either outside what DRC checks, or something DRC checks but does not gate.

## Findings, grouped by root cause

Severity: **B** blocker, **M** major, **m** minor. Origin: **ours** (our code or our decisions), **FR** (a Freerouting setting), **not-yet** (a pipeline capability we haven't built), **inherited** (the original does the same), **upstream** (a bug elsewhere).

### 1. Freerouting narrows tracks below their class width. Origin: FR setting, our code didn't turn it off and doesn't gate it

- **Mechanism (from the jar).** `RouterSettings.automaticNeckdown` and `fanout.enabled` both default to true. When a full-width segment doesn't fit, the router tries the pad's width, then 3/4, 3/5 and 1/2 of the class width. Every off-class width on both boards matches one of those steps:
  - 0.375 = 3/4 × 0.5
  - 1.05 = 3/4 × 1.4
  - 1.5 = 1/2 × 3.0
  - 2.5998, 2.2998, 2.1998, 1.1498, 0.9498 and 0.5078 are pad widths.
- **Not an import bug.** `read_ses` is correct: the widths in the SES and on the board match exactly.
- **Extent ✔**:
  - RLHT Default: 47 of 318 segments, 86.7 mm.
  - RLHT HV Relay: 28 of 60 segments, 75.5 of 262 mm.
  - DCMT Default: 88.7 mm.
  - DCMT Power: 40.9 mm.
  - DCMT Motor: 8.2 mm.
  - Only 24 of RLHT's 75 narrowed segments and 8 of DCMT's 54 touch a pad centre. The necking runs along whole straights, not just at pin entries. Examples ✔: RLHT CH1_CTRL 17.6 mm at 0.375; DCMT CH2_DIR 22.3 mm at 0.375; DCMT +12V 15.9 mm at 1.05.
- **The worst cases:**
  - **RLHT, M:** CH1_LINE and CH2_LINE drop to 1.5 mm for 5.3 mm. They thread under each relay between NC and NO, 1.39 mm from K.4. Each CH_LINE runs below 3.0 mm for 21 mm in all. The original routes LINE around the relay at 3.0 mm.
  - **DCMT, M:** the only CH2 +12V feed is 1.05 mm for 17 mm with nothing forcing it. +12V and GNDPWR narrow to 1.05 at J1 (your screenshot 1).
- **Nothing gates it.** KiCad treats a netclass width as a default, not a minimum. Our rules set `min_track_width 0.2`, so all of this passes DRC.
- **Fix:** turn off neck-down and fanout (`--router.automatic_neckdown=false --router.fanout.enabled=false`), and gate each class's minimum width in a generated `.kicad_dru`.
  - **Caveat, measured 2026-10-24:** with neck-down off, RLHT left 11 nets unrouted. Placement has to change too. This is not a one-flag fix.

### 2. Tracks crowd through-hole pins at the 0.2 mm minimum. Origin: ours (the DSN gives the router a single clearance)

- **DCMT, M:** seven tracks run between adjacent Nano socket pins on the solder side, 0.22 mm from each pin. A clearance scan of the original found nothing under 0.3 mm in the same window.
- **RLHT, M:** five similar cases. Both Nano pin rows are flanked on both layers.
- **RLHT, M ✔:** +12V loops around GND pin J1.10 at 0.208 mm, a 12 V-to-GND gap at a hand-soldered bus pin.
- **DCMT, M:** GNDPWR (1.4 mm) passes 0.21–0.25 mm from U2's BOOT, DIR and PWM pins (your screenshot 2).
- **DCMT, M:** +12V passes 0.29 mm from J1.3.
- **Thermocouple front end, M:** the inputs and SPI escapes run 0.26 mm from neighbouring SOIC pins, and tracks thread 0.95 mm gaps between stacked 1206 pairs.
- **Fix:** raise the clearance around through-hole pins in the DSN. Freerouting supports clearance types and per-class rules. Alternatively, add keepouts between header pins.

### 3. The router doesn't know the pours exist. Origin: ours (the "route every net, pours on top" design, and its consequences are worse than I described)

- Other nets' tracks cut through the pours. Measured foreign track inside each pour outline: DCMT +12V 461 mm, GND B.Cu 326 mm, CH1_VS 31.4 mm.
- **Channels that should match don't.** Placement and pour outlines are identical by translation, but the fills differ: CH1_VS fills 109 mm² against CH2_VS's 184; CH1_VDC is split in two against CH2_VDC's single piece.
- **DCMT +12V F.Cu pour, M:** it carries no current. It breaks into pieces (J1-only 336 mm², S2.1-only 126 mm², 21.7 mm²) that join nothing.
- **DCMT CH1_VS, M:** CH2_CSENS runs through channel 1's power section and truncates the CH1_VS pour. VS then reaches the bulk cap through 34 mm of track. C5.1 and C10.1 sit in 3.9 mm² VS islands inside the higher-priority VDC pours.
- **DCMT CH1_VDC, M:** a GNDPWR track cuts it in two. Channel 1's external-supply current then rides a B.Cu track that narrows to 1.05.
- **Fix:** write the pours into the DSN before routing, as planes, or as keepouts for other nets. The pours depend only on pad positions, so they can be computed before routing. Or drop pour nets from routing and let the fill connect them, which reverses the "connectivity never depends on a pour" decision.

### 4. Pour design errors. Origin: ours

- **DCMT ✔, M:** the GND/GNDPWR split doesn't exist on F.Cu. The whole-board GNDPWR F.Cu pour leaves a 1319.5 mm² piece over the entire logic area (y 99.8–139.3: Nano, buck, encoders, LED). Its only GNDPWR connection is the C5.2 thermal relief. The original's front GNDPWR stays in the motor block (x 167–181.5, y 41–93).
- **DCMT ✔, M:** CH2_VS fills 20 mm² under U3's metal tab, which is at ground, with only solder mask between. VS can reach 55 V. U2 escapes only because its pour is cut short (§3).
- **All three boards ✔, M:** the fill reaches 0.25 mm from every mounting-hole edge, on both layers. The originals keep 1.9–5.7 mm. Consequences:
  - **Loaf:** +12V is on the front and GND on the back of every hole, so metal hardware bridges the supply.
  - **DCMT H4:** GND and GNDPWR both reach the hole on B.Cu, so a screw bridges the ground split.
  - **DCMT H3:** the CH2_OUT1 pour comes within 1.45 mm on B.Cu.
- **RLHT, M:** both GND pours sit exactly 1.25 mm from all HV copper. They form a tongue under the relay between COM and NO, wedges between HV terminal pins, a strip outside J4/J5, and 0.24–0.30 mm slivers between the fuse-clip pads. This is legal under the rule, but 1.25 mm of creepage to bus ground is low if the heater lines are mains.
- **Loaf, M:** each net lives on one layer only, so all +12V and GND current enters through thermal reliefs on a single layer. At the jack that is 4 × 0.5 mm spokes (estimate ~5.8 A); at each slice +12V pin, 2 spokes (~2.9 A). The original pours both nets on both layers, with 383 stitching vias.
- **m:** hulls swallow unrelated circuitry (DCMT +12V hull 40.7 × 61.9 mm). The GND hull edge crosses J3. A 0.29 mm GNDPWR sliver runs along DCMT's right edge. Hulls against diagonal tracks leave voids. The zone `min_thickness` of 0.25 is below the Slice 0.5 mm minimum.

### 5. Not built yet. Origin: not-yet

- **Thermal vias, M:**
  - HS1 on both Slices has 0 vias; the original has 8 (RLHT) and 25 (DCMT).
  - The LMD18200s have 0 vias under either part; the original has 64 GNDPWR vias under each.
  - DCMT has no GNDPWR vias anywhere: the two layers join only through through-hole pads.
- **Stitching, m–M:** RLHT has 4 GND vias against the original's 48, and the Loaf has 0 against 383.
- **HV on both layers, M:** the original draws every HV segment at 3.0 mm on both layers. Ours is one layer, about half the copper.
- **A Power class on RLHT, m:** +12V, +5V and BUCK_SW run at 0.5 mm; the original uses 1.0–1.5.
- **Post-route clean-up, m:** zero-length and overlapping segments, a hairpin (CH2_COIL), detours (LED, FB about 30 mm against the original's 10–12), redundant GND tracks inside pours that block other routes (the cause of RLHT's J1.10 loop).
- **Fuse-clip duplicate pads, m:** the router lays HV track between the two clips of one holder. Fix: `duplicate_pad_numbers_are_jumpers`, and one DSN pin per pad number.
- **Silkscreen placement, m:** refs sit on pads and neighbours, terminal labels are clipped by outlines, refs fall off the board, and labels the originals have are missing. The Loaf alone is missing 60 per-pin labels.
- **Teardrops:** none on ours or the originals. Low value.

### 6. Placement. Origin: ours

- **RLHT, M:** the relay block leaves CH_LINE no 3 mm path around the relay. The NC-to-NO gap is 5.32 mm, short of the 5.5 a 3.0 mm track at 1.25 mm clearance needs.
- **RLHT, m:** the thermocouple block is packed tight. C5/C6's pad pitch (3.12) doesn't match U pins 2/3 (1.27), which forces the necked, crowded escapes in §1 and §2.
- **DCMT, M:** the 1 µF VS cap sits 22.6 mm from U3.6. The placement is the same as the original's; the impact is ours, through §3.

### 7. Pipeline and CI

- **Upstream, m (cosmetic):** CI runs the bare jar, which logs an `IllegalArgumentException` for `FREEROUTING__USER_DATA_PATH`. *Corrected 2026-11-08:* the variable still takes effect. `UserDataPathResolver.resolveAndLock` applies and locks it before the settings load, and only a later reflective write fails. Run bare with the variable set, the 2.5.0 jar writes `freerouting.json` and its log into that directory. So CI's router settings are pinned and our side needs no change. Filed as freerouting/freerouting#1109, with the one-line fix (skip `user_data_path` in `applyNonRouterEnvironmentVariables`). The analytics and GUI flags are passed in CI (check.yml lines 173–174 and 256–257).
- **m:** the DSN boundary is inset 0.5 mm, and the router adds its class clearance on top. That leaves at least 0.7 mm from the edge, or 1.75 mm for HV, which narrows the J1 channel. The NPTH keepout is the bare drill: the router keeps 0.2 mm, KiCad wants 0.25 (latent). An oval pad with w = h becomes a zero-length path (works today).

### 8. Inherited from the originals, or unchanged

- The Nano's USB overhangs the bottom edge; this is fixed by the case.
- The Loaf's J2 and J7 overhang its edges, which accounts for all 52 of its `silk_edge_clearance` warnings. J7's reference sits off the board.
- The Loaf's J6 footprint rectangle encloses J7's pad column on the opposite side. What the rectangle represents is unknown.
- The MAX31855s and the WS2812 have no bypass caps. This is a circuit-level question, the same on the original.
- The Loaf's bus tracks pass 0.01 mm off the pad centres.

### Checked and fine

- RLHT HV clearance: at least 1.25 mm everywhere (closest 1.252 mm at J5.3).
- RLHT thermocouple legs are symmetric.
- DCMT: NT1 is the only GND–GNDPWR junction on B.Cu.
- DCMT bootstrap caps sit about 3 mm from their pins.
- Motor-class copper is at least 0.6 mm from other copper, the holes excepted.
- Copper is at least 0.5 mm from the board edge.
- The Loaf's bus-to-+12V clearance is 0.40 mm.
- No dangling or off-centre track ends (RLHT top, with a positive control).

## Corrections to what I wrote earlier

1. **Phase 3 plan and PR #13.** I said the necking was "0.375 mm where they leave the 1.27 mm-pitch SOIC/SOP pads", and you accepted that on 2026-10-24. That was wrong: the necking runs along straights, at J1, at the Nano and at 1206 pads; HV goes down to 1.5 mm; DCMT's power nets to 1.05. You accepted it on incomplete evidence.
2. **Phase 4 plan and PR #14.** I said "+12V and GNDPWR share the width; the pours carry the rest". On DCMT the +12V pour carries nothing, and the whole-board GNDPWR fill defeats the GND/GNDPWR split on F.Cu.
3. **Phase 4 plan, "the second channel's pours are the first's, translated".** True of the outlines, which is what the test checks. The fills differ, because foreign tracks cut channel 1's.
4. **PRs #13 and #14 reported "DRC 0 errors".** True, but DRC doesn't gate track width or any of §2–§6. "0 errors" was weaker evidence than it read.

## What I'd do, in order

1. **Make the problems visible.** Generate a `.kicad_dru` with each netclass's minimum width (and the Slice 0.5 mm floor), plus checks for hole clearance and creepage. Expect the current boards to fail. That is the honest state.
2. **Fix the pour design (§4).** Keep pours clear of the holes. Confine GNDPWR on F.Cu to the motor block. Keep VS out of the tab footprint, or give the tab a GNDPWR pad. Fix the Loaf's single-layer feeds. These are all small changes in our code.
3. **Tell the router about the pours (§3) and the pin clearances (§2), and turn off neck-down and fanout (§1).** Then fix the placement fallout where nets go unrouted (§6).
4. **Thermal and stitching via generation (§5).** HS1, under the LMD18200 tabs, and pour stitching.
5. **HV on both layers, and a Power class on RLHT.**
6. **A silkscreen placement pass, and post-route clean-up.**
7. ~~Make the CI router invocation hermetic (§7).~~ Not needed: the setting is applied (§7, corrected). Filed as freerouting#1109.

## Decisions (2026-11-08)

- **RLHT heater lines are mains (120/240 VAC).** Between mains and the bus side (SELV), that means reinforced insulation. Per IEC 60664-1, as reproduced in [TI SLUP421](https://www.ti.com/lit/pdf/SLUP421), for 230 V mains, overvoltage category II, pollution degree 2, material group III:
  - **Clearance (Table F.2):** basic 1.5 mm at 2.5 kV; reinforced uses the next step, 4.0 kV, giving **3.0 mm**.
  - **Creepage (Table F.4):** basic is linearly interpolated between 63 V (1.25 mm) and 400 V (4.0 mm), giving about **2.8 mm** at 250 V; reinforced is twice basic, about **5.6 mm**.
  - **Between mains conductors** (NO/NC/COM/LINE), the spacing is functional insulation; the basic figures are the floor.
  - Our board keeps 1.25 mm, and the original reaches 0.5 mm. Neither meets this.
  - **Not fixable in layout (inherited circuit):** J4 and J5 pin 3 is GND (SELV), between mains pins 2 and 4 on the same 5.08 mm-pitch terminal. The pad gap is 2.48 mm, measured on the original. Only a circuit change fixes it: take GND off the mains terminal, or change the terminal.
  - **Not yet checked:** the G5Q-1 relay's own coil-to-contact insulation rating.
- **Loaf +12V budget: design for 5 A for now.** The real need is above 5 A. Going beyond it needs +12V and GND on both layers with stitching vias (as the original does), solid or wide thermal connections at the jack and the slice pins, and a jack and connector pins rated for the current. Kept to 5 A so the spike stays on pkidl, not on board design.
- **Mounting hardware is metal.** Keep copper out of a ring around every hole on both layers. The originals keep 1.9–5.7 mm.
- **Order of work: a quality pass on the three boards comes before phase ⑤.**

## Progress (phase 4½)

**2026-11-08: DRC rules, and a UUID bug.**

- **Rules.** Each board now gets a generated `.kicad_dru` (`pkidl.project.write_rules`):
  - every netclass width as a minimum (`width_rules`);
  - the mains spacing on RLHT;
  - a 2 mm copper keepout around the metal-hardware holes.

  They are all at warning for now, and each becomes an error as the fix it guards lands.
- **KiCad's zone fill honours these rules.** Refilled under them, the pours stop exactly 2.000 mm from the hole edges (Loaf J4 hole, RLHT H1, both layers; previously 0.250 mm) and 3.0 mm from the HV copper. So the mounting-hole finding in §4 is fixed for every pour, and what remains per rule is tracks and pads.
- **Baseline.** `kicad-cli pcb drc --refill-zones --schematic-parity --severity-all` on fresh builds of the branch:

| Board | Rule | Violations |
|---|---|---|
| Loaf | all custom rules | 0 |
| RLHT | Default width (0.5) | 47 |
| RLHT | HV Relay width (3.0) | 28 |
| RLHT | mains to LV clearance (3.0) | 22 |
| RLHT | mains to LV creepage (5.6) | 24 |
| RLHT | mains to mains clearance (1.5) | 14 |
| RLHT | mounting hole keepout | 0 |
| DCMT | Default width | 28 |
| DCMT | Motor width (1.4) | 8 |
| DCMT | Power width (1.4) | 18 |
| DCMT | mounting hole keepout | 1 (a routed CH2_OUT1 track at H3; the router sees only the drill) |

  The RLHT mains rules cannot reach 0 by layout alone. J4/J5 pin 3 is GND between mains pins (Slice_RLHT#90), and the G5Q-1's coil pin sits close to its contacts, an insulation rating not yet checked.
- **New finding, fixed.** `pkidl.footprint.place` kept library UUIDs on pads and graphics, so repeated footprints shared them: on the CI builds, Loaf 58 UUIDs by 232 items, RLHT 77 by 154, DCMT 87 by 174. KiCad attributes items by UUID, so a DRC run named all eight Loaf slice-connector holes as J3's. Every item in a placed footprint now has its own UUID.

**2026-11-09: pour design (§4).**

- **DCMT front GNDPWR is gone.** The B.Cu pour stays. On the filled board: F.Cu GNDPWR 0 pieces (6 pieces, 3485.5 mm² before).
- **No pour under an LMD18200 body.** A no-pour keepout covers each body's F.Fab outline. Sampled at 0.1 mm over each body: no fill of any net. Before: CH1_VS 33.9 mm² and GNDPWR 276.6 mm² under U2, CH2_VS 109.1 mm² and GNDPWR 213.9 mm² under U3. The 20 mm² in §4 was the tab strip only. Putting GNDPWR there, with vias to the back as the original does, waits for the thermal-via step: without vias the area holds no GNDPWR pad, and the fill removes it as an island.
- **Loaf supply pours connect solidly.** The fraction of a ring 0.25 mm outside each +12V/GND pad that is filled is now 1.00 at every pad (0.14–0.61 through spokes before). Single-layer pours with solid pads are what the 5 A budget needs; both layers and stitching are for above it.
- **DCMT pours fill nothing under 0.5 mm** (`POUR_MIN_WIDTH`). RLHT stays at 0.25 mm for now: at 0.5, U1.4 and U5.3 keep only one of their two GND thermal spokes (`starved_thermal`, an error). Revisit with RLHT's HV-on-both-layers rework.
- **Still open from §4:** RLHT's GND at 1.25 mm from HV copper (the mains rules now flag it); tighter hulls.

**2026-11-09: two-stage routing (§1, part of §2).**

- **How.** `slice.route` routes every class but Default first, alone, with neck-down off. It then routes the signals around those routes, which are fixed as protected wiring, with neck-down on. Signals may neck from 0.5 to 0.375 mm (decided 2026-11-09). With a strict 0.5 mm, 15 (RLHT) and 16 (DCMT) signal connections stayed unrouted: I2C from J1 to the Nano, and the Nano's lines to the LMD18200s.
- **Measured before choosing:** neck-down off in one stage left 11 connections unrouted on each board, and neck-down and fanout both off left 15 and 16. Power alone with neck-down off routes completely on both boards.
- **RLHT's signals keep 3 mm from mains copper in the router** (a DSN `class_class` rule). Asking the same of the mains stage leaves 6 connections unrouted, because pins sit closer than 3 mm by their footprints. With the signal-stage rule, the router adds no violations beyond the 16 present before it starts.
- **Result** (`drc --refill-zones --schematic-parity --severity-all`, 0 errors on both):

| Board | Rule | Before | After |
|---|---|---|---|
| RLHT | HV Relay width (now an error) | 28 | 0 |
| RLHT | Default width | 47 | 0 |
| RLHT | mains to LV clearance | 22 | 26 |
| RLHT | mains to LV creepage | 24 | 25 |
| RLHT | mains to mains clearance | 14 | 6 |
| DCMT | Default width | 28 | 2 |
| DCMT | Motor width | 8 | 4 |
| DCMT | Power width | 18 | 4 |

- **What remains.**
  - **DCMT Motor and Power:** pin entries up to 2.6 mm long (LMD18200 OUT pins at 1.05 mm, a +12V regulator pad at 0.84 mm).
  - **DCMT Default:** Freerouting's 3/5 neck, 0.3 mm (CH2_BRAKE for 12.9 mm).
  - **RLHT mains clearance:** 26 against 22. The full-width HV tracks are wider, and the rest are pad pairs set by the footprints and the circuit (Slice_RLHT#90).
- **Nano pads.** RLHT's Nano (A1) pads now join the GND pours solidly. A signal routed beside A1.29 had left its thermal one spoke short, a `starved_thermal` error.
- **Not done:** pours in the DSN (§3). As hard keepouts for the signal stage, the current hulls leave 22 DCMT connections unrouted, with 37 violations before routing, because they cover other nets' pins. That waits for tighter pours. Pin-clearance classes beyond the mains rule (§2) are also still open.
