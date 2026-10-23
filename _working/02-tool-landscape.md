# Tool Landscape & Alternatives Considered

Status: consolidated 2026-07-11.
Distilled from an exploratory ChatGPT session (`_working/CHAT_DUMP_ROUGH.md`, now deleted)
and **corrected against direct investigation** of the actual code and toolchain.

This is the "why skidl + pkidl and not something else" record. Read
`_working/00-context-and-architecture.md` for what we're building; read this for what we rejected.

---

## The original question

> If I want to turn my thesis electrical work fully scripted (to complete a composable
> mech–elec–fw–sw stack), are `devbisme/skidl` and `michaelgale/pcbflow` the best options?
> Initial instinct: fork PCBFlow, use SKiDL until something forces a fork, possibly fork
> and "align" both since development on both looks stalled.

**That instinct was wrong on both counts**, and the reasoning below is why.

---

## Lay of the field

| Option | What it covers | Assessment |
| --- | --- | --- |
| **SKiDL** | Electrical graph, parts, nets, hierarchy, ERC, netlists, **native `.kicad_sch`** | **Chosen** for the electrical layer. Use upstream, pin it, wrap it. Not dead — see below. |
| **PCBFlow / CuFlow** | Procedural geometry, footprint placement, turtle-style routing, direct Gerber output | **Rejected as foundation.** Alpha, ~70 commits, self-described as not fully documented. Its output model goes straight to Gerbers — it does *not* treat `.kicad_pcb` as the principal artifact. Useful as *design inspiration* only. |
| **Atopile** | Declarative electrical DSL, typed interfaces, units, constraints, assertions, part selection | The strongest serious alternative at the electrical layer. Rejected: its own documented workflow still says *place and route in KiCad*. It solves more of the electrical-intent problem, not the physical one — which is exactly the half we actually lack. Adopting it means taking on a rapidly-evolving DSL + compiler as a core dependency. |
| **tscircuit** | TS/React circuit description, schematic + PCB, Gerber/BOM/PnP, routing infra | The closest open-source end-to-end code-first PCB stack, and the most tempting. Rejected for now: component positions are still largely explicit, autolayout and autorouting are still evolving, and adopting it means TypeScript + React-like composition + a custom circuit-JSON ecosystem — abandoning Python, which is the substrate the rest of the BREAD stack (firmware tooling, CRUMBS, manifests) already lives in. |
| **KiUtils** | Python dataclass model over native KiCad sch/pcb/footprint/symbol files | Plausible substrate for pkidl. Not chosen: last release 2024. **We use `simp_sexp` instead** — it is already a SKiDL dependency, so it adds nothing new. |
| **kicad-skip** | Python manipulation of KiCad S-expression files | More exploratory/ergonomic than KiUtils, but its own docs admit PCB support is the weaker half. Reference, not foundation. |
| **KiCad native formats + IPC API** | Documented sch/board formats; protobuf control of a *running* KiCad | **The native format is our integration boundary.** The IPC API explicitly drives a running KiCad instance — wrong shape for a headless compiler. Not used as the compiler interface. |
| **Freerouting** | DSN/SES autorouting via GUI, CLI, or API | **Chosen route backend** (v2.5.0, JVM jar) — P5 research pass, `04-router-research.md`. Its output is imported and verified, never treated as source of truth. |
| **KiBot / KiKit** | Fab & doc automation; panelization | Belong at the downstream build layer regardless of authoring choice. **Already in use** by `bread-infra` CI. Keep. |
| **JITX** | Commercial: requirements, layout generation, routing solvers, verification | Useful as prior art and as the commercial ceiling of the idea. Proprietary dependence conflicts with an open, reproducible thesis platform. |

---

## Corrections to the original analysis

Direct investigation of the code changed several conclusions. Recorded so we don't
re-litigate from the stale version.

**"SKiDL is stalled / mostly superficial commits" — false.** v2.2.3, last commit
2026-04-21. Recent work is substantive: KiCad 9 support, modern schematic generation,
coordinate-transform fixes, cross-version tests. Its `.kicad_sch` generation is real, not
a stub (`sexp_schematic.py`, 1404 lines). See `_working/00-context-and-architecture.md` §3.3.

**"Fork PCBFlow as the physical backend" — rejected.** The problem isn't low activity,
it's architecture. PCBFlow makes *itself* responsible for geometry, layer behaviour,
zones, clearances and fabrication semantics, and emits Gerbers directly. That means
owning correctness that KiCad already owns, and it makes native inspection, DRC, and
round-tripping harder. We want:

```
Python intent → native KiCad board → KiCad verification → manufacturing artifacts
```

not

```
Python geometry → Gerbers
```

Extract PCBFlow's *ideas* (coordinate cursors, placement transforms, routing paths,
geometry helpers) around native KiCad board objects. Do not fork it.

**"Fork and align both projects" — rejected.** Doing this before encountering concrete
boundaries would turn the thesis into maintenance of two general-purpose EDA libraries.

**"Define a small serializable design model / IR" — already done, and not by us.**
The advice was to build one. `slice.yaml` (schema v1.0, CI-validated by `bread-infra`)
already declares layers, thickness, dimensions, connectors, mounting pattern, MCU form
factor, I²C address, interfaces, capabilities. **Extend it; do not invent a parallel IR.**
This is the single biggest correction to the original plan.

**"Use KiUtils or kicad-skip to write `.kicad_pcb`" — superseded.** Use `simp_sexp`,
already a SKiDL dependency. No new dependency, and the two halves of the compiler share a
serialization layer.

**"Do not initially build SKiDL-for-PCBs" — accepted, and it is precisely the plan.**
pkidl is a *board-family compiler* for BREAD's recurring structures, not a general PCB
language. See `_working/00-context-and-architecture.md` §4.

---

## Decisions recorded

| Decision | Rationale |
| --- | --- |
| **No new HDL/DSL.** Python is the source language. | A new language means parsing, validation, error reporting, schema evolution, tooling — all unrelated to the thesis. YAML/TOML stays for *parameters and variants* only. |
| **SKiDL upstream, pinned, behind a thin adapter.** | Keep a passive GitHub fork as continuity insurance. Submit fixes upstream first. Carry downstream patches only when a real board is blocked. Diverge only if upstream architecture prevents a required capability. **Do not begin with API cleanup or refactoring** — we don't yet know which roughness matters. |
| **pkidl emits native `.kicad_pcb` S-expressions directly.** | Not via `pcbnew` (flatpak-only, version-locked SWIG, being deprecated in favour of IPC). Deterministic, diffable, no KiCad process in the loop. |
| **KiCad is the manufacturing authority.** | `kicad-cli` for ERC/DRC; KiBot/KiKit for fab artifacts. We never own fabrication semantics. |
| **The four-way bakeoff is DROPPED.** | The original plan proposed implementing one board four ways (SKiDL+native / Atopile / tscircuit / SKiDL+PCBFlow) and scoring them. Superseded: the spike itself *is* the evaluation, and Loaf_x004 is small enough (8 footprints) that building it for real beats scoring it in the abstract. Revisit only if skidl+pkidl hits a wall. |

---

## The thesis-sized objective (restated)

> Demonstrate that a constrained family of composable modules can generate electrical
> connectivity, physical PCB realization, firmware mappings, software configuration, and
> manufacturing outputs from version-controlled declarations.

That proves the full stack **without** turning the thesis into development of a
general-purpose scripted EDA platform. A general autorouter, a general footprint system,
and a general EDA compiler are explicitly *not* the contribution.

---

## Still open

- ~~**Router choice.**~~ **Resolved** by the P5 research pass (`04-router-research.md`):
  Freerouting 2.5.0 (JVM jar), with `fastroute` and `CoppeRoute` as contribute-and-watch
  alternatives. The pass also found that reproducibility is gated by byte-stable DSN *input*,
  not the router — a requirement now on pkidl.
- **KiCad 10 Design Blocks.** A *native* schematic-reuse mechanism that overlaps with
  skidl `@subcircuit`, already used by `KiCad-Master-Lib`. Consume, ignore, or generate?
  Decide before Phase 3.
