# 00 — Prereq Work

**The plan.** Everything that must land before any board code gets written.
Status is maintained here; this doc progresses.

Analysis and evidence behind these decisions live in `_working/` — this doc is the
to-do list, not the reasoning.

Last updated: 2026-10-23

---

## Status

| # | Task | Owner | Status |
| --- | --- | --- | --- |
| P1 | KiCad-Master-Lib: lib tables, vendoring, drift tracking | Claude | ✅ **Done** — [PR #1](https://github.com/feastorg/KiCad-Master-Lib/pull/1) merged (`89cd0b1`) |
| P2 | Boards: KiCad 10 migration + re-point nicknames | Cam | ✅ **Done** — all three on KiCad 10 (`20260206`) |
| P3 | Re-run library audit; confirm zero dead nicknames | Claude | ✅ **GREEN** |
| P4 | Pin the KiCad version (flatpak local, container digest CI) | Claude | ✅ **Done** locally ([PR #7](https://github.com/feastorg/kidl-spike/pull/7)); container digest is fleet (F-008) |
| P5 | Router research pass | Claude | ✅ **Done** — Freerouting 2.5.0 (JVM jar). See `_working/04-router-research.md` |
| P6 | Scaffold `kidl-spike` to dev-toolbox standards | Claude | ✅ **Done** (`f9871ce`) |
| P7 | **Fix the DRC parity gate across BREAD** (see below) | — | **New — not started** |

## ✅ R1 RETIRED — 2026-07-12

**All 15 non-stock references across all three boards resolve from a clean checkout**,
with zero dependence on any developer's global KiCad configuration.

This was the blocker for the whole thesis claim: KiCad cannot be a *generated artifact*
until library resolution is reproducible from source. It now is.

Re-verify at any time with the harness in `_working/01-library-audit.md`.

> **The last straggler, worth remembering.** `Slice_DCMT` D1 (WS2812) had a fully migrated
> *schematic* but a stale *PCB* footprint association, still pointing at
> `SparkFun-LED:WS2812-5050-4PIN` — which does not exist in SparkFun's real library. That
> footprint was always first-party, mis-filed under a SparkFun nickname (the same pattern
> as the BREAD slice-bus connector). Fixed by re-linking footprints from the schematic.
>
> **DCMT's KiBot config sets `drc: schematic_parity: true`, so CI should have caught this
> and didn't.** Worth a look — a parity check that doesn't fire is worse than none.

---

## P1 — KiCad-Master-Lib

Closes risk **R1** (library reproducibility), the Phase 0 blocker. Without it,
"regenerate KiCad from Python" is impossible: nickname resolution currently lives only in
a hand-edited global KiCad config, and is already broken.

Repo: `~/eda/kicad/KiCad-Master-Lib` (via `$KICAD_MASTER_LIB`).
Rationale + evidence: `_working/03-library-analysis.md`, `_working/01-library-audit.md`.

✅ **Complete.** [PR #1](https://github.com/feastorg/KiCad-Master-Lib/pull/1) on branch
`chore/library-reproducibility` (`e0dfc9b` → `4d582ac` → `ac0a860`). Awaiting merge.

> **Workflow note:** this was done directly in `~/eda/kicad/KiCad-Master-Lib`, which
> collided with Cam working in the same checkout (a mid-run branch switch orphaned a
> commit; recovered, no loss). **Future org-repo work: use a scratch clone and let Cam
> pull, rather than operating in his working checkout.**

- [x] **1.1 Recover the missing parts.** `KMLib_Connectors:BREAD_Slice_Bus_10Pin` (12 pads)
      recovered from `BREAD_Loaf.kicad_pcb`. *`PPPC101LGBN-RC` and the 1x10 RA header were
      solved differently and better — Cam re-pointed the Loaf at stock KiCad symbols, so
      they never needed absorbing.*
- [x] **1.2 Rename for scriptability.** `Thermal Pad` → `Thermal_Pad` (file + internal
      `(footprint "...")` name). Spaces poison string refs in skidl/pkidl/CLI/shell.
- [x] **1.3 Replace submodules with vendored copies + upstream drift tracking.**
      Vendored at the exact SHAs the submodules already pinned, so zero library content
      changed. `vendor.yaml` manifest (upstream, ref, pinned commit, licence);
      `scripts/check_drift.py`; `scripts/vendor_sync.py` (three-way merge — local edits
      survive an upstream sync, conflicts block the pin); daily `upstream-drift` workflow
      opening one issue per drifted library. **Nothing ever auto-syncs.**

  > ⚠️ **Correction.** An earlier revision *deleted* the submodules, reasoning they were
  > unused by the three spike boards. Wrong denominator — this is Cam's **master** library
  > for all designs, not a spike dependency. It also carried a `PROVENANCE.md` asserting
  > two kmlib parts were absorbed from SparkFun under CC BY 4.0; that was **fabricated and
  > is disproven** — SparkFun's upstream `SparkFun-LED.pretty` does not contain
  > `WS2812-5050-4PIN` at all. Both retracted.
- [x] **1.4 Commit lib tables.** `kmlib.fp-lib-table` (**51**), `kmlib.sym-lib-table`
      (**46**), `kmlib.design-block-lib-table` (10) — covering **both** `kmlib-local` and
      the vendored upstreams, all via `${KICAD_MASTER_LIB}`. Regenerable with
      `scripts/gen_lib_tables.py`. **This is the step that closes R1.**
- [x] **1.5 Decide LFS: no.** LFS wouldn't reduce checkout cost (only history), its
      bandwidth quota is billed to the repo owner on every public clone including CI, and
      it adds a hard dependency that's awkward to reverse. 81 MB packed is not a large git
      repo. Instead: **sparse-checkout excluding 3D models by extension → 269 MB drops to
      68 MB** with all libraries intact. Recipe documented in the Master-Lib README; adopt
      it in `kidl-spike` CI (P6).

- [x] **1.6 Naming-hygiene pass.** Keystone test points and the EZO STEP renamed (+ the
      footprint referencing that STEP updated). **No filename in the library contains a
      space.** Also repaired a pre-existing dangling 3D model path on `LMD18200TNOPB` (the
      DCMT motor driver) that missed the `.3dshapes` reorg. All 55 `${KMLIB_LOCAL}` model
      references now resolve.

### Known latent issue (not blocking, worth a follow-up)

Some library footprints reference 3D models via **`${KICAD9_3DMODEL_DIR}`** and
**`${KIPRJMOD}`**. The former is hardcoded to KiCad 9 (we're moving to 10); the latter
resolves to the *consuming project's* directory, which is wrong for a shared library.
Both will silently fail to render. Same class of bug as R1 — worth sweeping.

---

## P2 — Boards (Cam)

- [x] Fix Loaf_x004 footprints → now KiCad 10 (`20260206`) and **fully resolving**
- [ ] Migrate `Slice_DCMT` + `Slice_RLHT` to KiCad 10 (both still on `20241229` = v9)
      — *2026-10-23: both root sheets, RLHT's relay/MAX31855K sheets and DCMT's
      motor-driver sheet read `20260306` (KiCad 10); other DCMT files and the boards were not
      checked. `Slice_RLHT`'s `thermistor.kicad_sch` is still KiCad 8, but no sheet references
      it: an orphan file.*
- [ ] Re-point their stale nicknames using the map below

### Nickname migration map — exactly 7 refs left

All targets **already exist** in `kmlib-local`. This is pure re-pointing; nothing to author.

```
Slice_DCMT
  kml-custom:SOIC_05WU-7_DIO             → KMLib_IC_SMD:SOIC_05WU-7_DIO
  kml-custom:SW_Slide-CK-1101M2S3CQE2    → KMLib_Switches:SW_Slide-CK-1101M2S3CQE2
  kml-custom:Thermal Pad                 → KMLib_Mounting:Thermal_Pad          [renamed in P1.2]
  SparkFun-LED:WS2812-5050-4PIN    (fp)  → KMLib_IC_SMD:WS2812-5050-4PIN
  SparkFun-LED:WS2812B_5050        (sym) → KMLib_IC_Digital:WS2812B_5050

Slice_RLHT
  KMLib_Mounting:Thermal Pad             → KMLib_Mounting:Thermal_Pad          [renamed in P1.2]
  SparkFun-LED:WS2812B_5050        (sym) → KMLib_IC_Digital:WS2812B_5050_RGB_LED
```

*2026-10-24: both `WS2812B_5050` targets above were written without the `_RGB_LED` suffix;
the KMLib symbol is `WS2812B_5050_RGB_LED` (same four pins as SparkFun's, default footprint
`KMLib_IC_SMD:WS2812-5050-4PIN`). The generated Slice_RLHT uses it. The DCMT line is left
as written until DCMT is checked.*

---

## P3 — Re-audit

- [ ] Re-run `_working/01-library-audit.md` (it carries its own commands) against the
      post-P1/P2 boards.

**Exit criterion for P1–P3 — and for the R1 risk:**

> From a clean checkout of `kidl-spike` + a pinned `KiCad-Master-Lib` + a pinned KiCad
> version, **every** symbol and footprint referenced by all three boards resolves, with
> zero reliance on any global KiCad config.

---

## P4 — Pin the KiCad version ✅ (local pin + policy)

- [x] Pin flatpak KiCad version locally — `doctor.py` `WANT_KICAD = "10.0.6"` is the single
      source of truth; `just doctor` fails on any other version. AGENTS.md / README.md point
      at it rather than restating the number.
- [~] Pin container digest in CI — **belongs to `bread-infra` (F-008), not here.**
      kidl-spike's own CI runs no KiCad container, so there is nothing to pin in this repo
      yet; when KiCad enters this CI (for gen/verify/DRC) its image must be digest-pinned.
      CI does pack the stock symbol libraries it needs from `kicad-symbols` at the tag read
      from `WANT_KICAD` (see F-014).
      Handed to the fleet track; ask before touching bread-infra.
- [x] Document that a KiCad upgrade is a **reviewed event** — stated at the pin in
      `doctor.py` and in AGENTS.md / README.md.

The only drift control worth building. Stock KiCad libraries (~25 of them, carrying the
overwhelming majority of parts) are the sole real upstream, and they *do* change across
releases. Pinning is free. See `_working/03-library-analysis.md` for why we are
deliberately **not** building a drift-detection workflow.

---

## P5 — Router research pass ✅

- [x] Score candidates against the proven DSN/SES loop

The loop is already verified as mechanically possible (`pcbnew.ExportSpecctraDSN` /
`ImportSpecctraSES` — see `_working/00-context-and-architecture.md` §3.6).

**Decided: Freerouting 2.5.0 (JVM jar), version-pinned in CI.** It is the only candidate
that clears a long-term-reliability bar (mature, active, regression-gated, GPL-3.0,
deterministic single-threaded). `fastroute` (Rust, `--parity` = byte-identical to
Freerouting, zero-cost swap) and `CoppeRoute` (strongest determinism design, best KiCad fit)
are contribute-and-watch alternatives. Full scorecard, field sweep and evidence in
`_working/04-router-research.md`.

**Key finding beyond the router:** reproducibility is gated by the byte-stability of the DSN
*input*, not the router (Freerouting #1016). **pkidl must emit canonical, byte-stable DSN** —
a requirement on our generator that de-risks every router choice.

---

## P6 — Scaffold `kidl-spike` ✅

Done in `f9871ce`. dev-toolbox `python-uv` profile: justfile, pre-commit (ruff + gitleaks),
CI, AGENTS.md. `just check` + `just test` green; 8 tests.

The substantive part is `src/kidl_spike/libs.py` — **the reproducibility boundary.** It
resolves symbols and footprints from the tables committed in KiCad-Master-Lib, never from a
developer's global KiCad config. Note SKiDL looks for a file named exactly `fp-lib-table`,
so we materialise one into `build/` from our `kmlib.fp-lib-table`.

`just doctor` (13 checks) **pulls a real part through SKiDL from each of the three library
sources** — stock KiCad, first-party KMLib, vendored SparkFun. Counting table entries proves
nothing; resolving a part proves the toolchain works. This is the check that would have
caught R1.

---

## P7 — Fix the DRC parity gate across BREAD

**Diagnosed 2026-07-12 by two independent agents; root cause confirmed against KiCad source.**

`Slice_DCMT` D1 had a schematic/PCB footprint mismatch that CI never flagged, despite
`drc: schematic_parity: true`. Root cause:

> **KiCad's stock default severity for `footprint_symbol_mismatch` is `warning`, not
> `error`** (`pcbnew/board_design_settings.cpp:189` —
> `m_DRCSeverities[DRCE_SCHEMATIC_PARITY] = RPT_SEVERITY_WARNING`). **KiBot's DRC preflight
> fails only on errors**, and `warnings_as_errors` defaults false. So the mismatch was
> printed on every CI run for months, as one of ~102 warnings, and every run went green.

Proven empirically on the pre-fix board:

```
kicad-cli pcb drc --schematic-parity --severity-error  → "Found 0 violations"        exit 0
kicad-cli pcb drc --schematic-parity --severity-all    → footprint_symbol_mismatch D1 exit 5
```

**This is not a Slice_DCMT misconfiguration — it is KiCad's default.** Verified: all three
boards carry `footprint_symbol_mismatch: warning`. By extension **every one of the ~40
`Slice_*` repos has the same hole.** This class of defect has never been gated anywhere.

### Actions

- [ ] Set `board.design_settings.rule_severities.footprint_symbol_mismatch: "error"` in each
      board's `.kicad_pro`. Verified safe: red on the broken board, green at current HEAD.
      Review the neighbouring demoted rules too — `missing_footprint`, `extra_footprint`,
      `lib_footprint_mismatch` are also `warning`.
- [ ] **`Slice_DCMT/hardware/Makefile` has the ERC and DRC targets swapped.** `-s`/`--skip-pre`
      *skips* the named preflight, so `drc: kibot -s drc` skips DRC. Introduced in `422068f`.
      Both checks still run, but violations are reported under the wrong job name — which is
      exactly what made "DRC passed" look trustworthy.
- [ ] **CI container drift**: `bread-infra` runs `ghcr.io/inti-cmnb/kicad9_auto:latest`
      against KiCad **10** projects. Bump it. (Folds into P4.)
- [ ] Make KiCad-Master-Lib available in `bread-infra` CI — now possible via the committed
      lib tables + sparse checkout. Most of the ~102 warnings are `lib_footprint_issues`
      caused by KMLib simply not being present in the container. **Do not enable
      `warnings_as_errors` until this is fixed**, or CI goes permanently red.
- [ ] Investigate: D1 is `(attr dnp)` on the PCB but not marked DNP in the schematic — a
      second, separate parity warning that was equally invisible.

### Design input for pkidl

Generated `.kicad_pro` files **must set DRC severities explicitly.** A generated board that
relies on KiCad's defaults inherits this same blind spot, and our whole verification story
rests on `kicad-cli pcb drc` actually being strict.

---

## Roadmap (post-prereq)

Not yet planned in detail. Each gets its own `_planning/NN-*.md` when it comes up.

| Phase | Board | Proves |
| --- | --- | --- |
| 1 ✅ | Loaf_x004 — electrical | skidl → netlist-equivalent `.kicad_sch`, passes KiCad 10 ERC |
| 2 ✅ | Loaf_x004 — physical (pkidl v0) | **The crux.** First fully generated, fabbable board. Outline, placement, `BREAD` netclass, GND zone, autoroute, DRC pass. |
| 3 ✅ | Slice_RLHT | Hierarchy (2 sub-sheets × 2 instances, as SKiDL subcircuits), `HV Relay` netclass, the 70×100 Slice form-factor contract |
| 4 ✅ | Slice_DCMT | The hard zone case (17 zones, hierarchical net names) |
| 5 | Generalize | Drive boards from `slice.yaml`/`loaf.yaml`; gitignore KiCad; regenerate in CI; show a *new* Slice variant falling out near-free |

**Success criterion (all phases):** generated netlist matches the original's,
`kicad-cli pcb drc` passes, layout is genuinely manufacturable. Layout need **not**
resemble the original.

### Phase 1 — done

`src/kidl_spike/boards/loaf.py` (`just gen loaf`). Against `Loaf_x004@ebf47df`, with KiCad
10.0.6 as the oracle:

- **Netlist:** all 7 nets match. `tests/test_loaf.py` checks the generated circuit against
  KiCad's export of the original (`tests/fixtures/loaf_x004_nets.json`) and runs in CI.
- **ERC:** 0 errors. The generator adds a `PWR_FLAG` on `+12V` and `GND`; the original has
  none and fails ERC with two `power_pin_not_driven` errors. The remaining warnings are all
  `lib_symbol_issues` / `footprint_link_issues`, which come from running ERC on a bare
  `.kicad_sch` with no project lib-table. Phase 2 removed them by generating the project
  and its lib tables (see below).
- **ERC "passes" means errors-only.** Since phase 2, `just erc` gates with
  `--severity-error` and writes the full report alongside.
- Carried: F-015 (worked around in `libs.configure_skidl`), F-016 (schematic placement not
  byte-stable; the netlist is).

### Phase 2 — done

`just gen loaf` now writes the board too: `loaf.kicad_pcb`, a `loaf.kicad_pro` with explicit
rules and severities, and project `sym-lib-table` / `fp-lib-table`. pkidl lives in
`src/pkidl/` (s-expression reader/writer, footprint placement, board assembly, project
file); the Loaf's layout is `src/kidl_spike/boards/loaf_layout.py`.

- **Interface fixed, layout generated.** Outline and the seven connector positions and sides
  are taken from the original as a committed spec (`test_interface_matches_original` pins
  them to it). The five bus signals are straight tracks from J2 to J7; GND is a pour over
  B.Cu, +12V a pour over F.Cu that joins around the ends of the bus. No autorouter: the bus
  is collinear by design. Freerouting comes in with the Slices.
- **DRC** (`--refill-zones --schematic-parity`): 0 errors, 0 unconnected, 0 parity issues.
  The 52 warnings are all `silk_edge_clearance`: the J1/J2/J7 bodies overhang the edge, as
  on the original (55 there).
- **The parity gate has teeth.** Three broken copies of the board, a wrong footprint, a
  wrong pad net and a missing footprint, each fail the errors-only gate as
  `footprint_symbol_mismatch` + `lib_footprint_mismatch`, `net_conflict` and
  `missing_footprint`; the intact board passes.
- **ERC** with the project lib tables: 0 errors, 9 warnings, all `lib_symbol_mismatch`
  (SKiDL's embedded symbols differ from the KiCad 10 library's). Unchanged after the bump to
  SKiDL 2.3.0 and its kicad10 backend.
- **Board pads match the original netlist**, and the board, project and lib tables are
  byte-identical across builds (`tests/test_loaf.py`).
- **Footprint placement matches KiCad's own**, pad for pad, on all eight footprints of the
  original (`tests/test_pkidl_footprint.py`). Rotations of 90/270 degrees are not covered.
- **Fab outputs:** `just fab loaf` writes Gerbers, drill files and a PDF render. CI's
  KiCad job (digest-pinned `kicad/kicad:10.0.6`) runs doctor, gen, ERC, DRC and fab, and
  uploads the outputs as an artifact.

### SKiDL pin bump — done

`e19d9a6a` (2.2.3, 2026-04-21) → release **2.3.0** (`b94f04d4`, 2026-07-28), with the
generators on its `kicad10` backend. The sibling `../skidl` checkout is detached at the tag.
Against the phase 2 results, nothing moved: the netlist matches the original (circuit and
schematic re-export), ERC 0 errors with the same 9 warnings, DRC 0 errors / 0 unconnected / 0
parity with the same 52 silk warnings, and the board stays byte-stable. F-015 is fixed by
2.3.0, so its workaround is gone. F-016 persists. F-003's typo is still in 2.3.0.

### Phase 3 — done

`src/kidl_spike/boards/rlht.py` + `rlht_layout.py` (`just gen rlht`). Against
`Slice_RLHT@a7308f3`, with KiCad 10.0.6 and Freerouting 2.5.0:

- **Hierarchy:** the relay and MAX31855K circuits are one `@subcircuit` each, called twice.
  `tests/test_rlht.py` checks the generated circuit against KiCad's export of the original
  (`tests/fixtures/slice_rlht_nets.json`): the same pin sets on all nets, the same
  no-connect pins, the same parts, and each original sheet instance's parts in one
  subcircuit call. KiCad's own export of the generated schematic has the original's 57
  nets, pin for pin, and no auto-named net.
- **Deliberate differences:** SW1/SW2 (off-board E-stop switches, on_board no) are left out,
  since SKiDL writes every symbol on_board; the holes H1–H4 are board-only footprints
  (F-019); D1 uses `KMLib_IC_Digital:WS2812B_5050_RGB_LED`; U1's value is its part number.
- **Form factor:** format S from the fleet's format table (bread-mechanical
  `formats.yaml`): 70 × 100 mm, R5 corners, four 5 mm holes 5 mm in, J1's pin row 3.6 mm
  from the bus edge and 50 mm up from the bottom (`common.SLICE_S`, pinned in the test).
  bread-infra's design constraints say M3 holes; the fleet's boards and the case use 5 mm.
  The Nano stays where the original puts it: its USB overhangs the bottom edge, and the case
  takes its USB port position from the board.
- **Block placement:** each subcircuit's parts are one relative layout, instanced per
  channel at a fixed pitch (relay channels 31.89 mm apart, thermocouple 7 mm); the test
  checks the second instance is a pure translation of the first. Root parts keep the
  original's positions.
- **`HV Relay`** (3.0 mm / 1.25 mm) covers the 10 nets the original routes in 3 mm track.
  The original's own patterns match no net (F-021).
- **Routing:** pkidl writes a Specctra DSN from the placed board (`pkidl/dsn.py`), runs
  Freerouting 2.5.0 single-threaded (`pkidl/route.py`) and writes the SES routes back into
  the board. 0 unrouted, 0 violations, in about 8 s. The DSN, SES and board are
  byte-identical across builds and processes. Freerouting necks 0.5 mm tracks to 0.375 mm
  where they leave the 1.27 mm-pitch SOIC/SOP pads; accepted as a known deviation from the
  Slice constraints' 0.5 mm minimum trace (decided 2026-10-24).
- **ERC:** 0 errors; 38 warnings, all `lib_symbol_mismatch`. **DRC** (`--refill-zones
  --schematic-parity`): 0 errors, 0 unconnected, 0 parity; 76 silkscreen warnings.
- **Schematic names:** every net is drawn as labels, and SKiDL's two-pin snap is switched
  off for the generation call (F-020); otherwise KiCad renames some nets and parity fails.
- **CI:** the Test job packs the extra stock symbol libraries and sparse-checks-out the
  extra footprint libraries, installs Java 25 and the Freerouting jar (version from
  `doctor.py`'s `WANT_FREEROUTING`, sha256 checked), and runs the board tests. The KiCad job
  runs `verify rlht` and `fab rlht` and uploads the `rlht` artifact.

### Phase 4 — done

`src/kidl_spike/boards/dcmt.py` + `dcmt_layout.py` (`just gen dcmt`). Against
`Slice_DCMT@b32e3b2` (its board and sheets are unchanged through `main` as of
2026-11-07), with KiCad 10.0.6 and Freerouting 2.5.0:

- **Hierarchy:** the LMD18200 H-bridge sheet is one `@subcircuit`, called twice.
  `tests/test_dcmt.py` checks the circuit against KiCad's export of the original
  (`tests/fixtures/slice_dcmt_nets.json`): pin sets on all 46 nets, the 8 no-connect pins,
  the parts, and each sheet instance's parts in one call. KiCad's export of the generated
  schematic has the original's 46 nets, pin for pin, and no auto-named net.
- **Deliberate differences:** M1/M2 (off-board motors) are left out; H1–H4 are board-only
  footprints (F-019); NT1, the GND–GNDPWR net tie, is in the BOM, because SKiDL writes
  every symbol in the BOM (F-022). The original project's `HV Relay` netclass, copied from
  Slice_RLHT, matches no net on this board and is not carried over.
- **Shared with RLHT:** the 12 V → 5 V buck and status LED (`common.buck_5v`,
  `common.status_led`), the build step (`common.generate`), and the Slice placement and
  routing (`boards/slice.py`). Slice_RLHT's and the Loaf's outputs are byte-identical to
  `main`'s after the move.
- **Placement:** each bridge is one block, the original's first channel, instanced at the
  original's channel pitch (32.05 mm); the test checks the second is a pure translation.
  Its output and supply terminals are moved into the right-edge column, so the second
  channel's clear the top-right hole. Root parts keep the original's positions.
- **Current (decided 2026-11-07: 3 A per channel, the LMD18200's rating):** `Motor`
  (VS, external supply, both outputs, per channel) is sized by IPC-2221 for 3 A on 1 oz
  copper at a 10 °C rise: 1.4 mm. Clearance 0.6 mm, IPC-2221 B2 for up to 150 V, since VS
  can be an external supply up to the LMD18200's 55 V. `Power` (+12V, GNDPWR) uses the
  same width; both channels' current shares those nets, and the pours carry the rest.
  Nothing checks a pour's current capacity.
- **Pours (decided 2026-11-07: route every net, pours on top):** Freerouting connects
  every net with tracks, so connectivity never depends on a fill. Each channel's VS and
  external-supply pours (F.Cu) and output pours (B.Cu) are the outline around their pads
  (`slice.pour_outline`), so they move with the block; the test checks the second
  channel's are the first's, translated. Logic GND is poured on B.Cu around its pads,
  GNDPWR fills both layers beneath. Power pours join pads solid; J1's pads too, where a
  thermal relief between the edge and the bus tracks was starved of spokes.
- **Routing:** 0 unrouted, 0 violations, about 14 s per build. DSN, SES and board are
  byte-identical across processes.
- **ERC:** 0 errors; 38 warnings, all `lib_symbol_mismatch`. **DRC** (`--refill-zones
  --schematic-parity`): 0 errors, 0 unconnected, 0 parity; 64 silkscreen warnings (the
  original: 53, plus 38 `lib_footprint_issues` and 1 `via_dangling`). The supply terminals' labels are on
  B.SilkS: on top, the bulk capacitor's outline leaves 0.7 mm beside them.

### Open questions to resolve before their phase

- ~~**Design Blocks vs skidl subcircuits**~~ — **decided 2026-10-23: SKiDL subcircuits.**
  Design blocks are not an input for now; publishing blocks from subcircuits is revisited in
  Phase 5. Evidence, from experiments on Slice_RLHT:
  - RLHT's reused sheets are relay ×2 and MAX31855K ×2. KiCad-Master-Lib has no relay block,
    and its one MAX31855 block is a different circuit (3V3, two caps vs RLHT's 5V with
    ferrites, a 10n cap and pull-ups). Consuming blocks would mean drawing new ones in KiCad
    first.
  - Two parametric `@subcircuit`s, each instantiated twice, are topology-equivalent to the
    original's four sheet instances (20 parts, 29 nets), checked through KiCad's netlist
    export of the generated schematic.
  - Consuming a block works through a `kicad-cli` netlist export plus a small loader (block
    ports carry markup like `~{CS}`; no-connects survive the export), but makes generation
    depend on KiCad.
  - SKiDL 2.3.0 draws the hierarchy cosmetically (F-018), so a generated sheet is not a
    reusable block as-is.
- **Phase 3's hierarchy criterion — decided 2026-10-23: source and netlist level.** One
  subcircuit, two instances in Python, verified in the netlist. The generated schematic's
  cosmetic hierarchy (F-018) is accepted because the schematic is a build artifact.
- **Does `slice.yaml` become the compiler's input, or stay a hand-maintained sidecar?**
  Shapes the pkidl API. Decide before Phase 5.
- **Where does pkidl live long-term?** Recommend: develop inside `kidl-spike`, extract to
  the `pkidl` repo once the primitives stop churning.
