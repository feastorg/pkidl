# Phase 6: authored power copper per block

Option 1 of `../_working/06-verdict.md` (decided 2026-11-10).

> **Status, 2026-11-10: step 0 is a no-go.** Pours that block other nets leave DCMT's signals no way through (24 unrouted). Pours that signals may cross get cut into pieces again. See `../_working/05-board-review.md`, "Phase 6, step 0". The next direction is open.

## Goal

A block carries its power copper as data, the way a designer would draw it once:

- pours, with their layers and priorities;
- via fields;
- the few fixed tracks a pour can't reach.

The root layout carries the board-level plan the same way: the bus supply from J1 and the board-wide power ground. The router gets those pours as planes that block every other net (`plane_as_obstacle`), and routes only what the pours don't connect.

**Test case: DCMT.** Its bridge block and the DCMT root, with HBTC following through the shared bridge block.

## Done when

On DCMT, measured on the filled board:

- **+12V** reaches both switches through copper at least 3.6 mm wide at its narrowest. That's both channels at `MOTOR_AMPS`, by IPC-2221: 6 A, 10 °C rise, 1 oz. Today it's a 1.4 mm track.
- **GNDPWR** on B.Cu is one piece; today it's three. Each channel's return and bulk-capacitor loop stays inside its own channel.
- **CH1_VS and CH2_VS** are one piece each, and C5.1/C10.1 reach their U pin 6 through the pour, not over 25 mm of track.
- DRC: 0 errors, 0 unconnected, schematic parity clean.
- The netlist still matches the original's, and two builds are byte-identical.
- HBTC passes the same checks, and its thermocouple ground (#36) still holds.

## The copper

**Source: the original DCMT's power zones and vias, relative to the parts they serve.** Our placement of the bridge block and root parts is the original's (`05-board-review.md` §6), so its layer plan fits:

| Copper | Original | Carried by |
|---|---|---|
| +12V, both layers, J1 to S1/S2 | 2 zones, x 127–164, y 63–100; 184 vias | DCMT root |
| GNDPWR, B.Cu, board-wide above the logic area | 1 zone, 2306 mm² filled | DCMT root |
| GNDPWR, F.Cu under each LMD18200, with its via grid | 2 zones | bridge block (exists: `BODY_GNDPWR`, `THERMAL_VIAS`) |
| VS, F.Cu | 1 zone per channel | bridge block |
| VDC, F.Cu | 1 zone per channel | bridge block |
| OUT1, OUT2, B.Cu strips | 2 zones per channel | bridge block (exists: `OUT_STRIPS`) |
| GND, B.Cu, logic area | 1 zone, 1400 mm² | DCMT root (the current hull pour) |

The shape is the original's, where layout elsewhere was free to differ: it's a proven plan for this placement. A redesign would be a second variable while the mechanism is still unproven.

## Steps

0. **Probe, before any code** (script in the session scratchpad):
   - DCMT with every row above as a DSN plane and `plane_as_obstacle` on, through the two-stage route;
   - report unrouted counts per stage, then fill and count pieces per pour net.

   **Go** if it routes completely or nearly so. **No-go** findings go into the review doc, and I bring them back before writing code.
1. **pkidl:**
   - `write_dsn` gains `planes` (net, layer, polygon);
   - `route` gains the planes and turns `plane_as_obstacle` on;
   - `-mp` moves to `--router.autorouter.max_passes`, since 2.5.0 warns that the old path is deprecated;
   - unit tests on the DSN text.
2. **Block and root copper as data:**
   - a `Copper` record (pours, vias, fixed tracks), relative to an anchor;
   - each block kind and each `Root` may carry one;
   - `slice_build` places it on the board, and passes the pours to routing as planes and the vias as fixed;
   - DCMT's hull pours for these nets go.
3. **Measure against "done when".** A width probe along the +12V fill, piece counts, DRC, byte identity. Tests pin each figure, and a mutation per test shows it fails.
4. **HBTC:** rebuild, check, and record any difference.
5. **Record it in the review doc**, with what's still open.

## Out of scope

- RLHT's HV on both layers (parked, `feat/rlht-hv-power`).
- The Loaf above 5 A.
- Any change of circuit or placement.

If step 0 shows a placement change is needed, that comes back to you before it's made.

## Alongside, not in this phase

- **The router bake-off** (verdict options 3 and 4): required, planned separately.
- **Freerouting reports:** filed only after a minimal DSN reproduction and a check against the source. The two candidates left:
  - neck-down along straights;
  - a fixed via in a same-net pad counted as a violation.

## Revision: authored crossings (2026-11-10)

**Decided 2026-11-10,** after the router bake-off (`../_working/07-router-bakeoff.md`).

**What it settled:**
- No router keeps a pour whole while routing across it.
- Freerouting with `plane_as_obstacle` keeps DCMT's pours intact and leaves 17 signals open.
- Routers that may cross the pours cut them into pieces.

**What the original does instead.** Its designer chose where signals cut each pour. This revision makes that choice data.

### The idea

A block or root carries, alongside its pours, **crossings**: corridors (a polyline and a width, on one layer) where other nets may pass through a pour.

**Routing:**
- each pour is filled before routing;
- its corridors are cut out of the fill;
- the result goes to Freerouting as planes, with `plane_as_obstacle` on.

Signals can then cross a pour only at a corridor. A corridor is drawn so the pour stays one piece around it: along an edge, or with the pour carried on the other layer and stitched.

### Done when

The same targets as above, on DCMT:
- every connection routed (DRC 0 unconnected);
- GNDPWR B.Cu one piece;
- +12V at least 3.6 mm at its narrowest;
- VS one piece per channel;
- DRC 0 errors;
- byte-identical builds;
- HBTC still holds.

### Steps

0. **Probe** (scratch, no pkidl code):
   - take step 0's crux: KiCad's pre-route fill, the original's power tracks fixed;
   - cut corridors where the original's signal tracks cross the pours. Our Nano, U2 and U3 sit where the original's do (U3 0.36 mm off), so the original's crossings are a designer's choice that fits;
   - route with `plane_as_obstacle` on, then fill and DRC;
   - **go** if it routes completely and the pours stay in one piece; anything else comes back to you with the numbers.
1. **The fill step** (*decided 2026-11-10: pkidl with shapely*, a pinned Python dependency, so that `gen` stays free of KiCad and works in a sandboxed session). The options were:
   - **(a) KiCad, in the build:** `kicad-cli pcb drc --refill-zones --save-board`. That adds KiCad to `gen`; CI has it, and a sandboxed session needs its own wrapper for it;
   - **(b) pkidl's own polygon fill:** a new dependency, or the raster fill model in `stitch.py` traced back to polygons.

   This is a build-architecture choice, so it comes to you with a recommendation, informed by the probe.
2. **pkidl:** planes (with corridors cut) in `write_dsn`, and the flag in `route`.
3. **Data:** pours and crossings in `Copper`, per block and root.
4. **Measure, test, HBTC, record,** as in the original steps 3–5.

### Step 0 result (2026-11-10)

**The mechanism works; the probe isn't complete.**

**Setup:**
- 76 corridors: rectangles 0.6 mm either side of each original DCMT signal segment that crosses our pre-route pours (5 on F.Cu, 71 on B.Cu);
- KiCad refills around them;
- the fills go to Freerouting 2.5.0 as planes, with `plane_as_obstacle` on;
- everything routes in one stage;
- then KiCad fills and DRCs the result.

**Pour regions after routing** (fill pieces joined across layers by the net's vias and through-hole pads):

| | +12V | CH1_VS | CH2_VS | GND (B.Cu) | GNDPWR | Unconnected |
|---|---|---|---|---|---|---|
| The original DCMT | 2 | 1 | 1 | 6 | 2 | — |
| Corridors, pours block | 2 | 1 | 1 | 5 | 2 | 5 |
| No corridors, pours block (bake-off) | 2 | 1 | 1 | 1 | 2 | 17 |
| No corridors, pours crossable (bake-off) | 3 | 5 | 3 | 5 | 4 | 7 |

**The five unconnected:**
- **2 are known probe artefacts:** the region filter dropped the original's tracks at S1 (+12V) and R1 (GNDPWR).
- **3 come from offsets between our parts and the corridors:** R2 (GNDPWR), CH2_DIR and CH2_THRM. The corridors follow the original's tracks, while our U3 sits 0.36 mm and R2 0.73 mm from the original's. The design draws corridors relative to our parts.
- **1, the Nano's A1.29 (GND), is unexplained.** That makes six against KiCad's five; my checker counts within about ±1 (bake-off doc).

**Target corrected.** The original isn't one piece per net either: +12V is 2 regions, GND 6 and GNDPWR 2. The fair target is pour structure no worse than the original's, plus the +12V width. The corridor result meets the structure on every net. The +12V width isn't measured yet.

**Iteration 2 (2026-11-10):**
- the misfitting GNDPWR stubs at R1/R2 were removed (6 tracks);
- channel 2's corridors were shifted onto our U3 (+0.362 mm);
- GND gets a 20 mm² minimum island area.

KiCad, after routing and fill (`drc --refill-zones --severity-all`):
- **3 unconnected:** CH2_BRAKE and CH2_THRM into U3, and one GND sliver not joined to the main pour;
- **otherwise clean:** 2 starved thermals, no clearance errors;
- **pour regions as the original's:** +12V 2, CH1_VS 1, CH2_VS 1, GNDPWR 2.

**+12V trunk** (`widest.py`: the widest path from J1's +12V pins to each switch, starting and ending 2.5 mm out from the pads, layer changes at vias; ±0.2 mm):

| | to S1 | to S2 |
|---|---|---|
| Corridors, iteration 2 | 1.60 mm | 1.40 mm |
| `main` today | 1.33 mm | 1.33 mm |
| The original | 1.60 mm | 1.60 mm |

**A second target correction.** By the same measure, the original's trunk is 1.6 mm too. It carries current through parallel paths on both layers, which a widest-path measure can't see. The 3.6 mm single-path target was set from one track's IPC-2221 width. The fair test is total copper cross-section, a min-cut across both layers. That isn't built yet.

**Decided 2026-11-10: go, with revised targets.**
- Every connection routed.
- Pour regions per net no worse than the original's.
- +12V copper cross-section (a min-cut across both layers, still to build) at least the original's.
- DRC 0 errors, byte-identical builds, HBTC still holds.

The three remaining gaps come from copying the original's tracks onto parts that sit differently. Corridors authored relative to our own parts remove that by construction.
