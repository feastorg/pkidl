<!-- The checklist the 2026-11-08 board review used (05-board-review.md). Paths point at the
     untracked build/review/ tree that review produced; regenerate it to rerun. -->

# PCB review procedure (generated BREAD boards)

You are reviewing PCBs generated from Python by this repo (kidl-spike): SKiDL for the
circuit, our own `pkidl` for placement/board files, Freerouting 2.5.0 for routing, KiCad
10.0.6 for zone fill and DRC. The boards pass KiCad DRC with 0 errors; your job is to find
everything DRC does not catch or does not gate, plus anything DRC flags as a warning that
matters. Review every tile assigned to you, every view, edge to edge. A first-pass board:
expect many issues.

## Inputs

Board root: `build/review/` (generated, untracked)

- Generated board as CI built it (zones unfilled): `<board>/<board>.kicad_pcb`
- Same board with KiCad's zone fill applied: `<board>-filled/<board>.kicad_pcb`
- The hand-drawn original, same coordinates: `orig-rlht/BREAD_Slice.kicad_pcb`,
  `orig-dcmt/BREAD_Slice.kicad_pcb` (none for the Loaf comparison images)
- CI's DRC/ERC reports (all severities): `<board>/drc.rpt`, `<board>/erc.rpt`
- Router log: `<board>/freerouting.log`; router input/output: `<board>/<board>.dsn`, `.ses`
- Project rules and netclasses: `<board>/<board>.kicad_pro` (JSON; `net_settings`)
- Tiles: `img/tiles/<board>/<view>/r<row>c<col>.png`, 40 px/mm, black background. The
  strip at the top of each tile gives its board-coordinate window (mm, y down).
  Overviews (whole board, 10 px/mm): `img/png/<board>-<view>-overview.png`.
  Views:
  - `cu_unfilled`: F.Cu (red) + B.Cu (blue) tracks, pads, vias; no pours. Shows routing.
  - `front_filled`: F.Cu with pours filled + F.SilkS (light) + edge.
  - `back_filled`: B.Cu with pours filled + B.SilkS + edge (seen from the top, so back
    text appears mirrored).
  - `silk_fab`: silkscreen both sides, F.Fab, courtyards, edge.
  - `orig_cu_filled` (Slices only): the ORIGINAL board's copper, both layers, filled.
- Query tool (run from `spike/`):
  `uv run python _working/review/board_query.py BOARD window X0 Y0 X1 Y1`
  (also `net NAME`, `nets`, `footprints`). Use it to put exact nets, widths and coordinates
  on everything you report. Do not report a width or clearance you did not measure; say
  "visual estimate" if you only eyeballed it.

## Design intent (what the board is supposed to be)

- Slice boards: 70 x 100 mm, 2 layers, 1.6 mm. Slice design constraints: min track 0.5 mm,
  min spacing 0.2 mm, 1206 or larger parts preferred, boards should be millable.
- Netclasses are in the .kicad_pro. RLHT: Default 0.5/0.2, `HV Relay` 3.0 mm track /
  1.25 mm clearance on the relay-switched lines (mains-like heater lines). DCMT: Default
  0.5/0.2, `Motor` 1.4 mm / 0.6 mm (3 A per channel, VS can be an external supply up to
  55 V), `Power` (+12V, GNDPWR) 1.4 mm / 0.2 mm. Loaf: BREAD 0.4 mm bus.
- Design decisions already taken (report consequences, do not re-argue them): the router
  routes every net; pours are added on top for current capacity, generated as the hull
  around each power net's pads; the Nano and the bus connector J1 positions are fixed by
  the case; mounting holes are board-only footprints; each subcircuit is placed as a block
  repeated by translation.
- DCMT: GND (logic) and GNDPWR (motor) are joined only at net tie NT1.

## Checklist (apply to every tile)

A. Copper geometry
  1. Track narrower than its netclass width (neck-down) — where, how much, why there.
  2. Tracks running across a pour of another net, splitting it into fragments or slivers;
     pours that end up thin necks, islands, or that fail to reach the pads they are for.
  3. A track or pour crowding a neighbouring pad (other net) — tight but DRC-legal is
     still worth a finding if it hurts solderability or HV spacing.
  4. Acute angles / acid traps, odd jogs, stubs, dangling segments, overlapping
     duplicate segments, segments that end off a pad centre.
  5. Vias: unnecessary, in or touching pads, in the pour where they cut it up, too
     small for the current, dangling.
  6. Detours and long loops a person would not route.
B. Electrical intent
  1. High-current paths (RLHT HV lines, DCMT motor/VS/OUT/GNDPWR, +12V): width along the
     whole path, bottlenecks, current crowding through a thermal relief or a neck.
  2. HV / motor clearance and creepage to low-voltage copper (RLHT 1.25 mm intent).
  3. Return paths and ground: GND vs GNDPWR separation on DCMT (any place they touch or
     the split makes no sense), ground pour continuity, slots/islands.
  4. Decoupling / bootstrap / bulk caps: distance and loop to the pins they serve.
     Buck converter (U1, C1-C4, L1): switch-node loop, input cap placement, FB trace.
  5. Sensitive signals (thermocouple inputs, current sense, I2C) next to noisy ones
     (relay coils, motor outputs, switch node).
C. Mechanical / assembly
  1. Parts too close for hand soldering; SMD under the Nano socket or other THT parts;
     bottom-side parts that are hard to reach.
  2. Silkscreen: overlapping text, text over pads or holes, unreadable labels,
     polarity/pin-1 marks missing, labels that would be hidden by a part body.
  3. Connector bodies off the edge (J1 is meant to overhang; others?), parts vs holes.
D. Manufacturability
  1. Anything below 0.5 mm track / 0.2 mm space (Slice constraint) or awkward to mill.
  2. Annular rings, pad-to-pad gaps, copper to board edge.

## Classify every finding

- `severity`: blocker (would not work, or would fail fab/assembly) / major (works but
  degraded reliability, current capacity, safety margin or assembly) / minor (quality,
  cosmetic).
- `vs_original`: same-as-original / worse / better / new (no counterpart) / n-a.
- `cause` (your best attribution; say "unsure" when you are):
  - `placement` — our block/fixed positions or orientations
  - `netclass-rules` — widths/clearances/vias we give KiCad or the router
  - `pour-generation` — our hull pours, priorities, connect mode
  - `dsn-export` — what we tell (or fail to tell) the router: e.g. pours, keepouts,
    pad shapes, edge clearance
  - `router` — Freerouting's own behaviour given correct input (neck-down, angles, vias)
  - `kicad-fill` — KiCad's zone fill result
  - `silk-labels` — our generated text
  - `inherited` — the original design does the same; not ours
  - `not-yet` — a capability the pipeline does not have yet (say which)
  - `upstream` — a bug in SKiDL / KiCad / Freerouting

## Output

Return a markdown table, one row per finding, columns:
`id | board | tile | location (x,y mm) | layer | nets/refs | checklist item | severity | vs_original | cause | finding (what, measured) | suggested fix`
Then a short list of the tiles and views you actually opened (coverage), and anything you
could not determine. Do not edit any file. Do not run kicad-cli.
