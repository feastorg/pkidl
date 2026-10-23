# 00 — Prereq Work

**The plan.** Everything that must land before any board code gets written.
Status is maintained here; this doc progresses.

Analysis and evidence behind these decisions live in `_working/` — this doc is the
to-do list, not the reasoning.

Last updated: 2026-07-12

---

## Status

| # | Task | Owner | Status |
| --- | --- | --- | --- |
| P1 | KiCad-Master-Lib: lib tables, vendoring, drift tracking | Claude | ✅ **Done** — [PR #1](https://github.com/feastorg/KiCad-Master-Lib/pull/1) merged (`89cd0b1`) |
| P2 | Boards: KiCad 10 migration + re-point nicknames | Cam | ✅ **Done** — all three on KiCad 10 (`20260206`) |
| P3 | Re-run library audit; confirm zero dead nicknames | Claude | ✅ **GREEN** |
| P4 | Pin the KiCad version (flatpak local, container digest CI) | — | Not started |
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
  SparkFun-LED:WS2812B_5050        (sym) → KMLib_IC_Digital:WS2812B_5050
```

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
| 1 | Loaf_x004 — electrical | skidl → netlist-equivalent `.kicad_sch`, passes KiCad 10 ERC |
| 2 | Loaf_x004 — physical (pkidl v0) | **The crux.** First fully generated, fabbable board. Outline, placement, `BREAD` netclass, GND zone, autoroute, DRC pass. |
| 3 | Slice_RLHT | Hierarchy (2 sub-sheets × 2 instances), `HV Relay` netclass, the 70×100 Slice form-factor contract |
| 4 | Slice_DCMT | The hard zone case (17 zones, hierarchical net names) |
| 5 | Generalize | Drive boards from `slice.yaml`/`loaf.yaml`; gitignore KiCad; regenerate in CI; show a *new* Slice variant falling out near-free |

**Success criterion (all phases):** generated netlist matches the original's,
`kicad-cli pcb drc` passes, layout is genuinely manufacturable. Layout need **not**
resemble the original.

### Open questions to resolve before their phase

- **Design Blocks vs skidl subcircuits** — decide before Phase 3. KiCad 10
  `.kicad_blocks` is a native schematic-reuse mechanism that overlaps with `@subcircuit`,
  and `KiCad-Master-Lib` already uses it. Consume, ignore, or generate?
- **Does `slice.yaml` become the compiler's input, or stay a hand-maintained sidecar?**
  Shapes the pkidl API. Decide before Phase 5.
- **Where does pkidl live long-term?** Recommend: develop inside `kidl-spike`, extract to
  the `pkidl` repo once the primitives stop churning.
