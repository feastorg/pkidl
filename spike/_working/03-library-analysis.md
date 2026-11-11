# KiCad-Master-Lib — Library Reproducibility Plan

Status: planned, not executed. 2026-07-11
Addresses **R1** from `_working/00-context-and-architecture.md` — the highest-severity risk in the spike.
Raw evidence: `_working/01-library-audit.md`.

---

## Why this is Phase 0, item 1

"KiCad files are generated artifacts" is impossible while symbol/footprint resolution
depends on a hand-edited global KiCad config. pkidl and skidl must resolve library
nicknames from a **committed, pinned** source or generation cannot be reproduced.

Today it cannot. Nickname resolution lives only in
`~/.var/app/org.kicad.KiCad/config/kicad/10.0/fp-lib-table`, and it is **already broken**
for the Loaf.

This is invisible from inside KiCad — the boards open fine because footprint geometry is
embedded in the `.kicad_pcb`. Dead nicknames only bite on update-from-library, or during
**generation**. It looks like cosmetic cleanup; it is a hard prerequisite.

---

## Question asked: submodules → vendored copies + a drift-detection workflow?

### Answer: neither. Delete the submodules. Build no drift workflow.

The premise was that vendoring buys the ability to patch upstream libs while still
receiving updates. The audit says there is nothing to receive updates *from*:

1. **`digikey-kicad-library`, `OPL_Kicad_Library`, `arduino-kicad-library`: zero usage.**
   Not one part across all three boards. Dead weight.
2. **SparkFun: three distinct items ever used.** Two are *already absorbed* into
   `kmlib-local` (`WS2812-5050-4PIN` footprint → `KMLib_IC_SMD`; `WS2812B_5050` symbol →
   `KMLib_IC_Digital`).
3. **The third was never SparkFun's.** `SparkFun-Connector:BREAD 10-Pin Connector` is a
   *first-party* part squatting in a third-party namespace. It does not exist upstream.

After finishing the migration already in flight, the third-party surface is **zero**.
A drift workflow would monitor four repos from which nothing is consumed.

### The deeper reason not to want one

**For PCB libraries, upstream drift is a hazard, not a feature.** A footprint silently
changing under a board that has already been fabbed is how parts stop fitting holes.
The correct model is *frozen + datasheet-verified + provenance-tracked*, not
auto-updated. `Slice_RLHT/TODO.md` already lists "footprint verification vs. datasheets"
as a Pass-2 gate — that instinct is right, and it is incompatible with tracking upstream.

### Where drift *does* matter (and was not asked about)

The ~25 **stock KiCad** libraries carrying the overwhelming majority of parts — `power`,
`Device`, `Connector`, `Capacitor_SMD`, `Resistor_SMD`, `TerminalBlock_*`,
`MountingHole`, … These *do* change across KiCad releases and are not owned.

Mitigation is free: **pin the KiCad version** — flatpak locally, container digest in CI —
and treat a KiCad upgrade as a reviewed event. That is the only drift control worth
having, and it costs nothing to build.

---

## What actually happened to this library

**A migration from third-party libs into a curated house library was started and stalled
at roughly 85%.**

The KiCad 10 `fp-lib-table` already declares the *destination*: it registers `KMLib_*`
and nothing else. The boards still reference the *origin*. Hence dead nicknames.

The half-migrated state is visible as duplication: `SOIC_05WU-7_DIO`, `Thermal Pad`, and
`WS2812-5050-4PIN` each exist under two nicknames. **DCMT points at the origin
(`kml-custom`); RLHT points at the destination (`KMLib_*`).**

---

## Decisions taken (2026-07-11)

| Decision | Choice |
| --- | --- |
| Submodules | **Delete all four.** No drift workflow. |
| Space-containing names | **Rename now**, in coordination with the in-flight board edits. |
| Absorbed SparkFun parts | **Record provenance + attribution.** CC-BY-SA / MIT requires it, and it matters under the CERN-OHL-S hardware licence. |
| Stock KiCad libs | **Do not vendor.** Pin the KiCad version instead. Revisit full vendoring only if hermeticity becomes an explicit thesis requirement. |

---

## The plan lives elsewhere

Actionable steps, the nickname migration map, sequencing, and the exit criterion are
in **`_planning/01-kidl-spike.md`** (P1–P3). This doc is the *why*.

## Open items

- **Loaf has no manifest.** No `loaf.yaml`; `bread-infra/spec/loaf/` awaits one.
  Not blocking, but the Loaf sits outside the BREADS tooling that governs the Slices.
- **KiCad 10 Design Blocks.** `kmlib-local/blocks/*.kicad_blocks` is a *native* schematic
  reuse mechanism that overlaps with skidl `@subcircuit`. Decide consume / ignore /
  generate before Phase 3 (the first hierarchical board). See `_working/00-context-and-architecture.md` §7.
- **Post-migration re-audit.** Everything here is measured against the boards as they
  stood on 2026-07-11, i.e. *pre*-v10 and pre-Loaf-fix. Re-run after those land.
