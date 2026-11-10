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
