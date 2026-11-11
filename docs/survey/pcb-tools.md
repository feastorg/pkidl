# Prior-art survey, half 1: PCB design from code

Surveyed 2026-11-11 for the pkidl charter (`docs/charter.md`). Stars and push dates are
from `gh repo view <repo> --json stargazerCount,pushedAt,licenseInfo` on that date.

Notation: **[V]** read in a primary source (the project's repo, docs, release notes or
source code), URL given. **[unverified]** found only in a secondary source or inferred by
me; the reason is given. "Not found in X" names where I looked.

## Comparison table

| Tool | Licence | Activity (2026-11-11) | Covers | Layout expressed as | Copper intent | KiCad interop |
|---|---|---|---|---|---|---|
| **tscircuit** | MIT | 2,973 stars, pushed 2026-11-11; no GitHub releases | schematic, placement, routing (own router), pours, fab, many exports | TSX props: absolute `pcbX/pcbY`, `calc()` relative to parts, pins and board edges; `pcbGrid`/`pcbFlex`/`pcbPack` auto-layout (beta); manual drags in `manual-edits.json` | trace `width`, `minLength/maxLength`; diff pair = `maxLengthSkew` only, **no impedance/width/gap**; no current. Custom `<drccheck checkFn>` | exports `.kicad_pcb`, `.kicad_sch`, project zip, Specctra DSN; imports KiCad footprints |
| **JITX** | proprietary (free tier for CERN-OHL-P designs only) | Python API 4.6; docs updated 2026-11-10 | full: schematic, placement, topological router, pours, SI, ODB++ | Python: `self.place(obj, pos)`, `obj.at(pos)`, kinematic tree of parent-relative frames; code routes + GUI | **strongest SI**: `RoutingStructure(impedance=…)`, timing, skew, insertion loss constraints, **measured and reported satisfied/not met**; no current constraint found | KiCad/Altium "integration" on plans page; Altium extension removed in 4.6; exports ODB++/STEP |
| **atopile** | MIT | 4,057 stars, pushed 2026-10-14; last release v0.14.1004 (2026-02-12, pre-release) | language, parameter solver, parts; layout **delegated to KiCad** | `.ato` code for circuit; placement by hand in KiCad, or agent tool (absolute/relative moves). **Layout reuse:** sub-build `.kicad_pcb` pulled into a group | `DifferentialPair.impedance` is a parameter used to size termination resistors, **not geometry** | reads/writes `.kicad_pcb` with its own s-expr parser (Zig); KiCad plugin (SWIG `pcbnew`); IPC only to reload the open board; DRC via `kicad-cli` |
| **pcbflow** | BSD-3 | 201 stars, pushed 2025-02-12; "Releases: None yet" | placement, hand routing, pours, Gerbers | absolute `(x, y)` per part; "turtle" routing strings from a pad (`"r 90 f 5 l 90 f 10"`); named polygons | none; global DRC class only; README To-Do lists "DRC checking" | **none**: writes Gerbers directly; imports `.kicad_mod` |
| **KiCad-Autoplace** (DTU-EKB) | MIT | 3 stars, created 2026-06-28, pushed 2026-09-02 | auto-placement + Freerouting refine | none by code: lock parts in KiCad, mark connectors; multi-seed annealer picks | decap-to-IC-pin proximity term; no width/current | KiCad 10 SWIG `pcbnew` for I/O; pure-Python engine core |
| **KiCad SWIG `pcbnew`** | GPL (KiCad) | deprecated since 9.0; **removed from nightlies March 2026; gone in KiCad 11** | every board object | imperative object API | whatever you write | in-process, headless, no GUI |
| **KiCad IPC API / kicad-python (kipy)** | MIT client | kipy 0.8.0 (2026-08-30) | PCB editor objects; KiCad 11 adds schematic, plotting/export, rules | imperative RPC | none | **KiCad 9/10: running GUI only. Headless `kicad-cli api-server` is KiCad 11 (10.99 nightlies)** |
| **Freerouting** | GPL-3.0 | 2,208 stars, v2.5.0 2026-10-05; maintainer limited to ~4 h/week | routing only | Specctra DSN in, SES out; `.rules` file for classes/clearance | net classes, widths, clearances in DSN; no current, impedance or length intent found | via DSN/SES (KiCad exports DSN); CLI, REST API (self-hostable), MCP |
| **KiCadRoutingTools** | MIT | 768 stars, pushed 2026-11-11 | routing, planes, fanout, length matching, placement by function | CLI flags + JSON "routing plans"; design brief file for connector edges | **closest to pkidl layer 4**: graded `--net-min-widths`, plane resistance + IPC-2221/2152 max current, impedance-derived widths, `check_impedance.py`, length/time matching | reads/writes `.kicad_pcb`; KiCad 9/10 plugin; KiCad DRC as oracle |
| **kicad-tools** (`kct`) | MIT | 73 stars, created 2025-12-29, pushed 2026-11-11 | parse/edit, own A* router, placement optimisers, DRC, creepage | Python API + CLI over the board file | creepage audit vs IEC 60664-1 and export of creepage rules to KiCad DRC; impedance calculator | writes `.kicad_pcb` directly; `kicad-cli` as referee; no running KiCad |
| **circuit-synth** | MIT | 292 stars, pushed 2026-03-08 | schematic from Python; PCB file generated, layout in KiCad | `@circuit` functions; layout by hand | none found | generates `.kicad_pro/.kicad_sch/.kicad_pcb` |
| **padne** | GPL-3.0 | 46 stars, pushed 2026-10-28; NLnet-funded | DC IR-drop FEM solver | n/a (analysis) | **measures current density and voltage drop on real copper**, from `!padne CURRENT i=3A …` directives in the schematic | loads KiCad projects via SWIG `pcbnew`; headless `padne solve` |

AI layout **products** (closed, not libraries): Quilter, DeepPCB, Flux. Below, under
"AI-driven layout products".

## Per tool

### tscircuit
- What: "Create real electronics with Typescript and React", MIT, created 2024-03-14 [V]
  (`gh repo view tscircuit/tscircuit`). Backed by a company (tscircuit.com); funding not
  checked.
- Layout expression [V]: absolute `pcbX/pcbY`; `calc()` expressions over part bounds
  (`R1.maxX`), pad bounds (`R1.pin1.minX`) and board bounds; edge anchors
  `pcbLeftEdgeX` etc. (https://docs.tscircuit.com/guides/tscircuit-essentials/relative-positioning).
  Auto-layout `pcbGrid`, `pcbFlex`, `pcbPack` on `<board>`/`<group>`, flagged "Automatic
  layout is in beta!", "Combining Layout Methods" is a TODO
  (https://docs.tscircuit.com/guides/tscircuit-essentials/automatic-pcb-layout).
  GUI drags persist to `manual-edits.json`, imported back into the code as a prop
  (https://docs.tscircuit.com/guides/tscircuit-essentials/manual-edits).
- Routing [V]: own MIT autorouter (`tscircuit/tscircuit-autorouter`, 95 stars); `pcbPath`
  overrides it per trace; `autorouter` prop swaps it
  (https://docs.tscircuit.com/elements/trace).
- Copper intent [V]: `<trace width maxLength minLength>`; `<differentialpair>` "does not
  configure differential impedance, trace width, pair spacing, or parallel routing", only
  `maxLengthSkew` (https://docs.tscircuit.com/elements/differential-pair).
  `<copperpour>` has clearances, crosshatch, thermal reliefs, no current
  (https://docs.tscircuit.com/elements/copperpour). Built-in DRC checks are not listed;
  `<drccheck checkFn>` is for custom rules (https://docs.tscircuit.com/elements/drccheck).
- KiCad [V]: `tsci export -f kicad_pcb | kicad_sch | kicad_zip | specctra-dsn | gerbers`
  (https://docs.tscircuit.com/command-line/tsci-export).
- Painful [unverified, secondary: kicad-tools' own evaluation in its README,
  https://github.com/rjwalters/kicad-tools]: five tscircuit designs failed kicad-tools'
  `kicad-cli` DRC/LVS gate; schematic and PCB converters name the same net differently;
  via/netclass defaults below fab floors.
- Borrow: `calc()` placement relative to parts, pads and board edges; the "drag in GUI,
  persist as data the code imports" loop; a swappable router prop. Stops short: no
  copper physics; layout reuse comes only from React component reuse (inferred, no docs
  page found).

### JITX
- What [V]: commercial; "on-premises licensed software", annual per-seat; runtime runs
  locally (https://docs.jitx.com/en/latest/jumpstart-kits/shared/JITX_Architecture_and_Systems_Requirements_v2_0.html).
  Free tier "Free Indefinitely" for designs under CERN-OHL-P v2 only, "Incompatible with
  Proprietary or Copyleft/GPL Designs" (https://www.jitx.com/plans). Backed by Y Combinator
  and Sequoia (https://jitx.com/). Language: Python (4.x); formerly Stanza [unverified,
  third-party skill page].
- Placement [V]: `self.place(obj, (x, y), on=Side.Top)` relative to the circuit,
  `obj.at(...)` relative to parent; poses compose "inside-out" as a kinematic tree;
  circuits fixed at (0,0) unless `floating=True`
  (https://docs.jitx.com/en/latest/essentials/physical_design/kinematic-tree.html).
  This is per-subcircuit layout reuse by construction.
- Routing [V]: topological autorouter; 4.2 adds routes and control points from code; 4.6
  adds "scripted interactive layout: create and modify routes, vias, control points,
  pours, and area regions on a running design"; 4.4 captures placed geometry back into
  Python for introspection (https://docs.jitx.com/en/latest/release-notes.html).
- Copper intent [V]: `RoutingStructure(impedance=50, layers=…trace_width, clearance,
  velocity, insertion_loss)`, `Constrain(Topology(a,b)).timing(1e-9).insertion_loss(3)`,
  `ConstrainDiffPair(...).timing_difference(1e-12)`; after routing,
  `rt.submit(MyDesign).issues(satisfied=True)` reports each constraint "met"/"NOT MET" with
  measured values. Impedance is a lookup key: you supply width per layer; the page does
  not say JITX solves width from stackup. Same-net spacing and fab minimums are not
  enforced; "check these with your fabricator's design rule check"
  (https://docs.jitx.com/en/latest/essentials/SI/constraints.html). Pours: `Pour(shape,
  layer, isolate, rank)`; no current or neck constraint
  (https://docs.jitx.com/en/latest/essentials/physical_design/pours.html).
- KiCad: plans page lists "KiCad and Altium integration" [V]; Altium extension removed in
  4.6 as "stale and deprecated" [V, release notes]; whether KiCad export carries routed
  copper: not found in docs search (export page 404).
- Borrow: kinematic-tree placement; constraints that come back as a met/not-met report
  with measured numbers (exactly pkidl's layer 4 shape, for SI). Stops short: closed,
  licence excludes copyleft designs, no current/thermal intent.

### atopile
- What [V]: MIT, 4,057 stars, `.ato` language + faebryk Python core; last tagged
  release v0.14.1004 (2026-02-12, pre-release) (`gh release list -R atopile/atopile`).
  Docs moved into the hosted editor ("docs live in the editor now",
  https://docs.atopile.io/).
- Layout [V]: KiCad does placement and routing. The agent tool
  `src/atopile/server/agent/tool_layout.py` moves a footprint in absolute or relative mode,
  writes the `.kicad_pcb`, and returns bounding-box collisions and an on-board check.
- **Layout reuse [V]**, `src/faebryk/exporters/pcb/layout/layout_sync.py` and
  `examples/layout_reuse/`: each module can have its own build target and hand-made
  `.kicad_pcb`; footprints carry an `atopile_address` property; a KiCad "Pull Group"
  button copies footprints, tracks, arcs, vias, zones and graphics from the sub-layout into
  a group on the top board, remapping nets by matching pads (most frequent mapping wins).
  Offset = anchor footprint (most pads) position difference; source comment `# TODO
  rotation?`, so **instances cannot be rotated**. It prefers sub-layouts that have tracks,
  and the highest-level module when nested. Pull is a manual GUI step per the example's
  docstring.
- Copper intent [V]: `DifferentialPair.impedance` is a `NumericParameter` constrained
  against termination resistors (`terminated()`), not trace geometry
  (`src/faebryk/library/DifferentialPair.py`). Code search for `trace_width` in the repo:
  0 hits (`gh search code --repo atopile/atopile trace_width`).
- KiCad [V]: own s-expression parser in Zig (`src/faebryk/core/zig/src/sexp/kicad/`);
  DRC via `kicad-cli pcb drc --format json` (`src/faebryk/libs/kicad/drc.py`); IPC used to
  reload the open board (`src/atopile/kicad_plugin/README.md`); plugin targets SWIG
  `pcbnew` ("KiCAD 8.0 still uses Python 3.9").
- Borrow: stable logical address on every footprint (`atopile_address`) as the join key
  between circuit and layout; net remap by pad matching for block instances. Stops short:
  the reusable layout is hand-drawn KiCad, not code; no rotation; no copper intent.

### pcbflow
- What [V]: BSD-3, Python, based on CuFlow; "alpha and not fully documented"; "Releases:
  None yet"; last push 2025-02-12 (README, https://github.com/michaelgale/pcbflow).
- Layout [V]: `brd.add_part((x, y), R0603, side="bottom")`, or a drawing context
  `brd.DC((x,y)).right(90)`; routing by turtle strings from a pad,
  `usb_con.pad("D-").turtle("r 90 f 5 l 90 f 10").wire(width=0.25)`; `fanout(["GND"])` to
  vias; `fill_layer("GTL", "GND")`; `add_named_rect(..., "GP3", "VDD")` patches.
  SKiDL parts via `SkiPart`.
- Copper intent: none; one `Board.drc` object of global widths/clearances; To-Do: "Routing
  and Nets", "DRC checking".
- KiCad: none; emits Gerbers/BOM/centroids/SVG itself.
- Borrow: turtle routing relative to a pad as a compact hand-route form; SKiDL as the
  netlist source. Stops short: no KiCad, no DRC, so no judge; stalled.

### KiCad-Autoplace (DTU-EKB)
- What [V]: MIT, Python engine + Electron app, "Built for students at DTU Ballerup
  Campus"; 3 stars; created 2026-06-28 (README and `gh repo view DTU-EKB/KiCad-Autoplace`).
- How [V]: user locks crucial parts, marks connectors (placed on edges), draws outline and
  pours; app generates multi-seed placements scored by wirelength/crossings, user picks
  one, refines with Freerouting (pinned `freerouting-1.9.0.jar`), "Finalize" overwrites the
  project board (keeps `.bak`). Headless `cli.py place|refine|preflight|metrics`, run with
  KiCad 10's Python (SWIG `pcbnew`).
- Intent [V]: decap-to-IC-power-pin hinge term, target 3 mm, pad-to-pad, every change gated
  on a Freerouting routed-% non-regression on two corpus boards
  (`docs/superpowers/specs/2026-06-30-phase2a-decap-proximity-design.md`,
  `plugin/plugins/autoplace/electrical.py`). No width/current/return-path terms.
- Borrow: a placement term ships only if a router-in-the-loop metric does not regress
  (same shape as pkidl's scorecard); decap pairing detector (2-pad cap on POWER+GND to
  nearest >2-pad part on the rail). Stops short: SWIG dependency dies in KiCad 11
  (inferred from the SWIG removal below); tiny adoption.

### KiCad scripting: SWIG `pcbnew` and the IPC API
- SWIG [V]: "deprecated as of KiCad 9.0 and will be removed in a future version"; "The
  current plan is to remove the SWIG bindings in KiCad 11.0"
  (https://dev-docs.kicad.org/en/apis-and-binding/pcbnew/). On 2026-03-29 Jon Evans wrote
  "Support for SWIG was removed last week" from nightlies and unported plugins "will stop
  working in KiCad 11" (https://mid.mail-archive.com/devlist@kicad.org/msg00846.html).
  SWIG runs in-process with no GUI: kipy's page contrasts "Unlike the SWIG-based Python
  bindings, the IPC API requires communication with a running instance of KiCad"
  (https://pypi.org/project/kicad-python/).
- **IPC API headless, KiCad 10: no [V].** "The IPC API in KiCad 9 and 10 only supports
  communication with a running instance of the KiCad GUI"; "KiCad 9 and 10 only support
  IPC API plugins in the PCB Editor"; "has no support for plotting or exporting files";
  "Support for running in headless mode through `kicad-cli` was added for KiCad 11"
  (https://dev-docs.kicad.org/en/apis-and-binding/ipc-api/for-addon-developers/). kipy 0.8.0:
  "It is not possible to use `kicad-python` to manipulate KiCad design files without KiCad
  running" (https://pypi.org/project/kicad-python/). KiCad 10.0.8 CLI manual lists top-level
  subcommands `fp, jobset, pcb, sch, sym, version`, no `api-server`
  (https://docs.kicad.org/10.0/en/cli/cli.html). The known KiCad 9/10 CI workaround is
  launching the `pcbnew` GUI under Xvfb and connecting kipy to it
  (https://adamws.github.io/using-the-new-kicad-ipc-api-in-a-ci-environment, 2025-03-22,
  KiCad 9).
- **KiCad 11 [V, nightly docs + developer posts; not released]:** `kicad-cli api-server
  [--socket SOCKET_PATH] PROJECT_OR_FILE` "runs the KiCad IPC API server in headless mode"
  (https://docs.kicad.org/master/en/cli/cli.html, manual "based on KiCad 10.99"). Nightly
  IPC adds design rules incl. custom rules, plotting/export, headless mode (devlist post
  above); "all the kinds of output generation possible with `kicad-cli` are now also
  possible through the API" (forum, 2026-03-21,
  https://forum.kicad.info/t/post-v10-new-features-and-development-news/66611). Schematic
  editor plugins added (addon-developers page). Release expected around February 2027
  [unverified: forum estimate; KiCad's policy targets 31 January,
  https://dev-docs.kicad.org/en/rules-guidelines/release-policy/index.html].
- Layout reuse in KiCad itself [V]: 9.0 multichannel "Repeat Layout" between rule areas;
  "a large copper zone that intersects a reference channel will not be copied"
  (https://docs.kicad.org/9.0/en/pcbnew/pcbnew.html); 10.0 extends Design Blocks to the
  PCB editor, libraries of layout fragments applied to matching footprints
  (https://www.kicad.org/blog/2026/03/Version-10.0.0-Released/).
- KiCad DRC has no current-to-width rule [unverified as a negative: KiCad custom-rule
  docs show `track_width` min/max by condition; no current-derived constraint found in a
  search of kicad.org and forum results].
- For pkidl: writing `.kicad_pcb` text directly plus `kicad-cli` (DRC, fill via
  `--refill-zones`, fab) needs neither binding and works on 10 and 11. SWIG is a dead end
  after 10. IPC is only a headless option from 11, and then only through a long-running
  server process.

### Freerouting
- What [V]: GPL-3.0, Java, v2.5.0 (2026-10-05); maintainer announces ~4 h/week, PRs over
  issues, releases every 2-3 months; "332,000 active users … 4 financial supporters"
  (README, https://github.com/freerouting/freerouting).
- As a library/API [V] (https://github.com/freerouting/freerouting/blob/master/docs/API/API_v1.md):
  - REST, self-hostable (`--gui.enabled=false --api_server.enabled=true
    --api_server.authentication.enabled=false`), session → job → input DSN (base64) →
    optional `.rules` → start → output SES; partial output while running (HTTP 202); SSE
    log and output streams; per-job DRC as KiCad DRC v1 JSON plus a `drc/summary` "designed
    for AI agents".
  - `POST /v1/autoroute`: one synchronous call taking DSN (+rules, +initial SES), returns
    SES/`KICAD_JSON`/DRC summary with `unrouted_connections`, `clearance_violations`,
    `normalized_score`, `optimizer_score`.
  - Python client `freerouting-client` on PyPI; MCP server; Docker image on GHCR.
  - Every protected call **requires** `Freerouting-Profile-ID` (a UUID) and
    `Freerouting-Environment-Host` headers; the public API needs a registered key. pkidl
    should self-host with auth off and a random, non-identifying profile UUID.
- Intent: whatever DSN/rules carry (classes, widths, clearances, via types). No current,
  impedance or length constraints in the API doc.
- Weakness [unverified, secondary: kicad-tools README]: DSN is a lossy translated view;
  fastroute (GPL Rust port) documents patching KiCad's Specctra export for DRU clearances,
  keepouts and planes.
- Borrow: the `/v1/autoroute` result shape (routed / unrouted / violations / score) fits
  pkidl's "Results, not booleans"; partial output on timeout.

### Others that generate or constrain layout from code
- **KiCadRoutingTools** (drandyhaas) [V, README and `docs/power-nets.md`,
  `docs/route-plane.md`]: MIT, Rust A* router, CLI + KiCad 9/10 plugin. Records the widths
  it was asked for inside the board (`tool_records.py`: "Records later steps must honour
  (matched groups, routed pairs, impedance, pour promises), kept on the board and in the
  `.kicad_pro`") and `board_score.py` measures copper against them; `--net-min-widths` is
  graded with a pad-neck allowance. Plane analysis reports `resistance_ohms`,
  `max_current_a` (IPC-2221) and `max_current_ipc2152_a`, but from **average width along an
  MST path or bounding-box diagonal**, not the narrowest neck. "Floorplan intent, graded"
  and a "design brief" file declare where parts belong. Uses KiCad's own DRC/fill as
  oracle.
- **kicad-tools** (rjwalters) [V, README]: MIT; "All tools output machine-readable JSON and
  require no running KiCad instance"; own router, CMA-ES placement, pure-Python DRC,
  `kct creepage` (IEC 60664-1/62368-1) and `kct creepage-export-rules` into KiCad DRC,
  `kct impedance`. Its README is the best index of the 2026 agent/KiCad ecosystem (routers
  TraceMaker, OrthoRoute, fastroute, Topola; MCP servers).
- **circuit-synth** [V, README]: Python `@circuit` → KiCad project; layout stays manual
  ("Use Python for hierarchical structure and repeated blocks, KiCad for custom layout").
- **padne** [V, README]: KiCad-native 2.5D FEM DC solver; intent written as directives in
  the schematic (`!padne CURRENT i=3A f=… t=…`, `VOLTAGE`, `REGULATOR`); headless
  `padne solve`; uses system KiCad Python bindings (SWIG), so KiCad 11 status unknown.
  KiPI (GPL-3.0, 104 stars) is a similar DC power-integrity tool as a KiCad 9/10 IPC plugin
  [unverified beyond `gh repo view` description].
- **OrthoRoute** (MIT, 431 stars, GPU router) and **KiKit** (MIT, 2,065 stars,
  panelisation/fab automation over `pcbnew`) exist; not surveyed further (metadata only).

## AI-driven layout products (closed services, not libraries)

| Product | What [source] | Intent handled | Interface |
|---|---|---|---|
| **Quilter** | physics-driven AI placement + routing, returns several candidates; "Anything inside the board outline is treated as locked" [V, https://www.quilter.ai/product] | reads diff pairs, impedance nets, DDR, bypass caps, converters from schematic; stackup + DRC; "shows every physics check it ran"; good fit "under 10A" [V, same] | upload KiCad/Altium/Allegro/Xpedition, native files back; no API mentioned; free tier may train on uploads |
| **DeepPCB** (InstaDeep, BioNTech-owned [unverified, search summary]) | cloud placement + routing, multiple options with metrics [V, https://deeppcb.ai/deeppcb-api-your-pcb-design-ai-agent/, 2025-05-12] | constraints "your design constraints and needs", unspecified [V, same] | API, KiCad PCM plugin; 0.50 credit/min |
| **Flux** | in-browser EDA; "AI Auto-Layout" preview since 2024-12, RL router [unverified: Flux blog via search, https://www.flux.ai/p/blog/introducing-ai-auto-layout] | net classes, diff pairs claimed [unverified] | Flux's own editor only |

None exposes a code-level intent language; all take a finished schematic and a
constraint set, and return geometry.

## What pkidl should borrow

1. **Constraints come back as a report with measured values** (JITX `issues()`:
   met/NOT MET with numbers; Freerouting `/v1/autoroute` counts and scores;
   KiCadRoutingTools `requested_under`). pkidl's layer 4 is the same pattern applied to
   current, pours and return paths.
2. **Intent recorded in the output** (KiCadRoutingTools keeps "pour promises" and widths on
   the board and in `.kicad_pro`; atopile's `atopile_address` on every footprint). Lets a
   verifier and a re-run read what was asked without the source.
3. **Parent-relative frames for blocks** (JITX kinematic tree): a block's layout is written
   once in local coordinates and placed per instance, rotation included, which atopile's
   pull-group lacks (`# TODO rotation?`).
4. **Relative placement over parts, pads and board edges** (tscircuit `calc(R1.pin1.minX -
   2mm)`, `pcbLeftEdgeX`); turtle routing from a pad (pcbflow) as the hand-route escape
   hatch.
5. **Router-gated solver changes** (KiCad-Autoplace: a placement term merges only if
   routed-% does not regress), matching pkidl's scorecard rule.
6. **KiCad as oracle, not as library**: atopile, kicad-tools and KiCadRoutingTools all
   write the file and judge with `kicad-cli`. Given SWIG's removal and IPC's GUI
   requirement on 10, this is the only route that works on KiCad 10 and 11 headless.
7. **Freerouting through self-hosted REST** with auth off and a random profile UUID: gives
   partial results, DRC JSON and scores without CLI scraping. GPL means process boundary
   only.

## Gaps nobody fills

- **Current intent verified on the finished copper, as a pass/fail tied to the
  statement.** JITX: no current constraint found (SI constraints and pours pages).
  tscircuit: no current prop (trace, copperpour, drccheck pages). atopile: 0 `trace_width`
  hits. KiCad DRC: no current-derived rule found. KiCadRoutingTools comes nearest: it
  grades track widths it was asked for and estimates plane current from **average** width,
  not the narrowest neck (`docs/route-plane.md`). padne/KiPI solve real current density
  but are analysis tools, not checks against a stated "this path carries 6 A". pkidl's
  "+12V pour's narrowest neck is 1.4 mm at U1; 6 A needs 4.2 mm" is not produced by any
  tool surveyed.
- **Return-path continuity as intent.** Not found in JITX SI docs, tscircuit,
  atopile, or KiCad DRC. KiCadRoutingTools places GND return vias at layer changes, an
  action, not a verified claim.
- **Layout blocks written in code.** atopile and KiCad 10 design blocks reuse a
  **hand-drawn** KiCad fragment; JITX reuses code placement but is closed. No open tool
  writes a subcircuit's layout in code and instantiates it per SKiDL subcircuit with
  rotation/mirroring.
- **Copper intent from an open, code-first library feeding KiCad.** tscircuit is the only
  open code-first tool that emits routed `.kicad_pcb`, and it has no impedance, current or
  return-path model.
- **Headless live KiCad on 10.** Not available; only Xvfb plus GUI, or file writing.

## Method notes

- One `curl` to docs.kicad.org was refused by the sandbox network allowlist; the same
  pages were read with WebFetch. No impact on findings.
- `kicad-cli` is not on PATH in this sandbox; nothing here depended on running it.
