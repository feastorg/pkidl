# kidl-spike — Vision, Scope, and Established Facts

Status: draft, 2026-07-11
Supersedes the rough notes in `_working/CHAT_DUMP_ROUGH.md` and `_working/further-context.md`.

---

## 1. Vision

Make the **electrical** layer of the BREAD stack scripted and composable, so that the
full mech–elec–fw–sw stack is generated from version-controlled declarations.

The end state: **KiCad files are build artifacts, not source.** `hardware/*.kicad_sch`
and `hardware/*.kicad_pcb` get gitignored; Python is committed; boards are regenerated
in CI or on demand.

### Why this is worth doing (the real argument)

This is not "script three boards". `feastorg` contains ~40 `Slice_*` repos plus Loaf
backplanes, all conforming to **BREADS**. The existing repo templates are already
parameterized on exactly the axes a compiler would want:

    Slice_TEMP_{NANO | NUCL | PICO}_{S2L | L4L | S4L}
                controller           size × layer-count

Every Slice shares a form-factor contract (70×100 mm, 2-layer, 1.6 mm, M3 @ 5 mm inset,
10-pin slice-bus carrying power + I²C). Both testbed Slices contain a **2× replicated
sub-sheet** (DCMT instances `motor_driver_lmd18500.kicad_sch` twice; RLHT instances
`relay.kicad_sch` and `max31855k.kicad_sch` twice each). That replication is a Python
function called twice. **This is the single strongest argument for the approach**, and
it is already visibly true in the existing designs.

A board-family compiler pays for itself across 40 boards. A general-purpose EDA tool
does not, and is not the thesis.

---

## 2. Scope

### In scope

- Regenerate three existing boards from Python in the `kidl-spike` repo.
- `pkidl`: a new library for the **physical** layer (what skidl lacks).
- Autorouting, by **leveraging existing open-source routers** — not writing one.

### Out of scope

- Touching `Slice_DCMT` / `Slice_RLHT` / `Loaf_x004`. They are read-only reference.
  Generated output is compared against them; the originals are never modified.
- Writing a new HDL/DSL. Python is the source language.
- A general-purpose autorouter, footprint system, or EDA platform.

### Decisions taken (2026-07-11)

| Question | Decision |
| --- | --- |
| Fidelity bar | **Netlist + DRC + manufacturable layout.** Same connectivity, passes DRC, genuinely fabbable. Need *not* resemble the original's layout. |
| pkidl physical scope | **Full autoroute, leveraging existing OSS** for the fundamentals/math. A dedicated research pass will pick the router. |
| KiCad target | **KiCad 10.** All boards being migrated to 10 by end of week. |
| First board | **Loaf_x004** (simplest: 8 footprints, 1 zone, flat schematic). |

---

## 3. Established facts

Everything below was verified directly against the repos, the KiCad 10.0.4 source, and
the installed toolchain — not assumed.

### 3.1 The testbed boards

| | Loaf_x004 | Slice_DCMT | Slice_RLHT |
| --- | --- | --- | --- |
| KiCad format | 20231120 (v8) | 20250114 (v9) | 20250114 (v9) |
| Board size | 121.2 × 50.0 mm | 70 × 100 mm | 70 × 100 mm |
| Copper layers | 2 | 2 | 2 |
| Sheet files | 1 (flat) | 2 (1 reused ×2) | 4 (2 files, each ×2) + 1 orphan |
| Footprints | 8 | 38 | 41 |
| Nets | 70 | 176 | 205 |
| Zones | 1 | **17** | 2 |
| Vias / segments | 0 / 65 | 354 / 248 | 49 / 300 |
| Net classes | Default, **BREAD** | Default, HV Relay | Default, **HV Relay** |
| Diff pairs | none | none | none |
| CI / KiBot | none | yes (shared) | yes (shared) |
| `slice.yaml` | **no** | yes | yes |

- Boards are **small**. This is very tractable for a spike.
- `BREAD` netclass on the Loaf (`+12V`, `/E_STOP`, `/INT`, `/SYNC`, `GND`, 0.4 mm track)
  **is the bus contract** — it is the physical expression of the BREADS standard.
- `HV Relay` netclass (1.25 mm clearance / 3.0 mm track) is load-bearing on RLHT (mains
  switching) and **vestigial on DCMT** (copy-pasted).
- DCMT's **17 zones use hierarchical-path net names** (`/Motor Driver LMD1850001/VS`).
  This is the hardest physical feature to regenerate.

### 3.2 The IR mostly already exists

`slice.yaml` (schema v1.0, validated in CI by `feastorg/bread-infra`) already declares
pcb layers, thickness, dimensions, copper weight, connectors, mounting pattern, MCU form
factor, I²C address, interfaces, and capabilities.

The advice to "define a small serializable design model" is **already done**. Extend
`slice.yaml` — do not invent a parallel IR. Loaf has no manifest yet; `bread-infra` has a
`spec/loaf/` directory awaiting one.

### 3.3 skidl (electrical) — adequate, use upstream

- v2.2.3, last commit 2026-04-21. Backends `kicad5`…`kicad9`. **No `kicad10`.**
- Native `.kicad_sch` generation is **real**, not a stub: `sexp_schematic.py` (1404 L)
  + `gen_schematic.py` (710 L). Reads `.kicad_sym`. Runs KiCad's own ERC via `kicad-cli`.
- Hierarchy: `@subcircuit` / `Group` / `Node`, with `Interface` for named subcircuit I/O.
  Maps cleanly onto the replicated sub-sheets in DCMT/RLHT.
- **`kicad6/7/8/9` schematic backends are byte-identical copies**, all hardcoding file
  version `20230409`. So a `kicad10` backend is likely a copy + a `gen_netlist` tweak —
  cheap, *if* it turns out to be needed. (See 3.5: it is not needed to start.)
- **PCB support is a hole.** `generate_pcb()` just delegates to `kinet2pcb`, which drops
  footprints in from a netlist. No placement, no routing, no zones, no outline.
  **This hole is exactly pkidl's shape.**

### 3.4 KiCad 10 toolchain

- KiCad **10.0.4** installed via flatpak. `kicad-cli` and `pcbnew` both work.
- KiCad 10 file formats: schematic `20260306`, board `20260206`.
  skidl writes schematic `20230409`.
- **`pcbnew` exists only inside the flatpak sandbox.** Host Python cannot import it.
  (It *is* available in KiBot's Docker images, which is how CI already runs.)
- Symbol/footprint libraries are host-readable at
  `/var/lib/flatpak/runtime/org.kicad.KiCad.Library.{Symbols,Footprints}/…/files/{symbols,footprints}`.

### 3.5 VERIFIED: skidl's KiCad 9 output loads in KiCad 10

Generated a divider with skidl (`set_default_tool(KICAD9)`), then ran
`kicad-cli sch erc` from KiCad 10.0.4 against it. **KiCad 10 parsed it and ran ERC
successfully** — no format error. The only violations were expected unconnected pins in
the trivial test circuit.

> **Consequence: a skidl KiCad 10 backend is NOT a prerequisite.** This retires the
> biggest schedule risk. Defer the `kicad10` backend until something concrete demands it.

### 3.6 VERIFIED: a headless autoroute loop is possible

`kicad-cli` has **no** Specctra DSN export. But `pcbnew` Python (inside the flatpak)
**does** expose `ExportSpecctraDSN` and `ImportSpecctraSES`. Therefore:

```
pkidl → .kicad_pcb → ExportSpecctraDSN → .dsn
                                          ↓
                                    Freerouting (headless)
                                          ↓
routed .kicad_pcb ← ImportSpecctraSES ← .ses
        ↓
  kicad-cli DRC → KiBot → gerbers/drill/BOM/PnP/STEP
```

This delivers "full autoroute leveraging existing OSS" **without writing a router**.
Freerouting is the chosen router (v2.5.0, JVM jar; P5 research pass, `04-router-research.md`).
This section only proves the *loop* is mechanically possible. **Reproducibility is gated by
the byte-stability of the DSN we export, not the router** (Freerouting #1016): pkidl must
emit canonical, byte-stable DSN — stable UUIDs / deterministic placement order.

### 3.7 The surrounding ecosystem

- **BREADS** = the standard. **BREAD** = a deployed device. **Slice** = capability module.
  **Loaf** = backplane. **Grain** = adjacent support hardware.
- `bread-infra` holds the JSON schemas, specs, and reusable CI workflows (KiBot ERC+DRC,
  manifest validation, Pages deploy). Slices call into it; Loaf does not (yet).
- `KiCad-Master-Lib` supplies the `KMLib_*` / `kml-custom` symbols and footprints — and
  is built on **KiCad 10 Design Blocks** (`.kicad_blocks`), a *native* schematic-reuse
  mechanism that overlaps with skidl subcircuits. Choose deliberately; do not collide.
- `CRUMBS` is the I²C protocol (fixed 27-byte message); `bread-crumbs-contracts` carries
  per-slice op/capability definitions. Both are firmware-layer, pinned in `slice.yaml`.

---

## 4. Proposed architecture

```
slice.yaml / loaf.yaml          ← declarative intent (EXISTS; extend, don't replace)
        │
        ├── electrical ──→ skidl (upstream, pinned, behind a thin adapter)
        │                    └─→ native .kicad_sch  +  netlist
        │
        └── physical ────→ pkidl (NEW)
                             ├─ board outline, mounting pattern, keepouts
                             ├─ placement (domain primitives, see below)
                             ├─ zones / pours / stitching
                             ├─ netclasses (BREAD bus, HV Relay)
                             └─→ native .kicad_pcb  (direct S-expression emission)
                                        │
                                  DSN → autorouter → SES
                                        │
                              KiCad = manufacturing authority
                              kicad-cli DRC/ERC → KiBot → fab artifacts
```

### Key architectural call: pkidl writes S-expressions directly, NOT via pcbnew

Rationale:

- `pcbnew` only exists inside the flatpak → poisons host dev and constrains CI.
- `pcbnew` is a version-locked SWIG binding that KiCad is moving away from (in favour of
  the IPC API, which drives a *running* KiCad — wrong shape for a compiler).
- Direct emission is deterministic, diffable, and needs no KiCad process.
- **skidl already depends on `simp_sexp`** — pkidl can reuse it. Pleasing symmetry, and
  no new dependency.

`pcbnew` is then used for exactly one thing: the DSN/SES bridge in the routing loop.
That is available in the flatpak locally and in KiBot's Docker image in CI.

### Domain primitives (the thesis-sized contribution)

Not a general PCB tool — a **board-family compiler** for the recurring BREAD structures:

    place_slice_bus_connector()   place_nano_socket()      place_mounting_pattern()
    place_decoupling_cluster()    route_power_bus()        add_ground_zone()
    stitch_zone()                 add_isolation_keepout()  set_netclass()

---

## 5. Risks

| # | Risk | Severity | Mitigation |
| --- | --- | --- | --- |
| R1 | **Library reproducibility.** Lib tables are gitignored in all three repos; nickname resolution lives only in a hand-edited global KiCad config — **and is already broken.** A library migration into `kmlib-local` stalled ~85% through, leaving dead nicknames (`kml-custom`, `SparkFun-*`, `PPPC101LGBN-RC`). The `BREAD 10-Pin Connector` — the slice-bus connector, the physical embodiment of BREADS — has been **lost** from the library and survives only as embedded geometry inside `BREAD_Loaf.kicad_pcb`. | **High** — blocks "regenerate from source" outright | **Audited and planned: see `_working/03-library-analysis.md`.** Recover the 3 missing parts from the board files, finish the migration, delete the 4 (zero-usage) submodules, commit lib tables. Do this **first**. |
| R2 | **skidl schematic place & route is the weak spot.** `PlacementFailure`/`RoutingFailure` are routine; `place.py`/`route.py` carry several `HACK:`/`FIXME:` comments. Generated schematics may be ugly or fail outright. | Medium | Fidelity bar is netlist+DRC, not schematic beauty. Use `flatness`, `auto_stub`, and the labels-only fallback. Schematic aesthetics are explicitly **not** a success criterion. |
| R3 | **DCMT's 17 zones with hierarchical-path net names.** | Medium | Deferred — DCMT is board 3. Loaf (1 zone) proves the pipeline first. |
| R4 | Loaf is KiCad 8 format, has no manifest, no CI, no KiBot — it sits outside the `bread-infra` tooling despite being the first target. | Low | User is migrating all boards to KiCad 10 by EOW. Author a `loaf.yaml` against `bread-infra/spec/loaf/`. |
| R5 | ~~Router choice unresolved.~~ **Resolved.** | Low | P5 research pass chose Freerouting 2.5.0 (`04-router-research.md`). Residual: reproducibility needs byte-stable DSN from pkidl (§3.6), not the router. |

### Known upstream bugs found (worth reporting)

- **skidl** `circuit.py:1307` — `kwargs.get("empty_footprint_handler]")` has a stray `]`,
  so a user-supplied handler is silently never honoured. Good first upstream PR.
- **skidl** README still claims schematic generation is "V5 only"; it is not (stale docs).
- **Slice_RLHT** `slice.yaml` declares `primary_ic: MAX6675`, but the schematic uses
  `MAX31855KASA`. Live manifest bug in your repo — worth filing.

---

## 6. The plan lives elsewhere

Phased plan, prereq to-do list, and success criteria are in
**`_planning/01-kidl-spike.md`**. This doc is context, facts, and architecture.

## 7. Open questions

- **Design Blocks vs skidl subcircuits.** `KiCad-Master-Lib` is built on KiCad 10
  `.kicad_blocks`. Do we consume them, ignore them, or generate them? They overlap
  with skidl's `@subcircuit`. Decide before Phase 3 (the first hierarchical board).
- **Does `slice.yaml` become the compiler's input, or stay a hand-maintained sidecar?**
  Cleanest end state is that it is the input and the boards are derived. Not urgent
  until Phase 5, but it shapes the pkidl API.
- **Where does pkidl live long-term?** Its own repo (as now), or vendored into the spike
  until the API settles? Recommend: develop inside `kidl-spike`, extract to `pkidl` once
  the primitives stop churning.
