# Scripted KiCad spike — working-tree overview

A spike to explore scripted PCB + schematic generation using `skidl` + `pkidl`, against
three real boards from the BREAD thesis platform (currently authored in vanilla KiCad).

End state: **KiCad files become build artifacts, not source** — `.kicad_sch` / `.kicad_pcb`
get gitignored, Python is committed, boards are regenerated in CI or on demand.

> This overview and the planning/analysis below used to live loose in the container
> directory one level up, tracked by nothing. They now live inside `kidl-spike`, so a
> single clone carries the code and the reasoning together.

## Start here

**[`01-kidl-spike.md`](01-kidl-spike.md) — the plan.** What to do, in what order, and
what's done. Start here.

Everything else is the reasoning and evidence behind it:

| Doc | What it is |
| --- | --- |
| [`../_working/00-context-and-architecture.md`](../_working/00-context-and-architecture.md) | Vision, scope, established facts, proposed architecture, risks |
| [`../_working/01-library-audit.md`](../_working/01-library-audit.md) | Raw evidence behind risk **R1**. Re-runnable. |
| [`../_working/02-tool-landscape.md`](../_working/02-tool-landscape.md) | Alternatives considered and rejected — why `skidl` + `pkidl` and not atopile / tscircuit / PCBFlow |
| [`../_working/03-library-analysis.md`](../_working/03-library-analysis.md) | Why we delete the submodules and build no drift workflow |
| [`../_working/06-verdict.md`](../_working/06-verdict.md) | **The spike's verdict (2026-11-10):** what works, what doesn't and why, and the options from here |
| [`../_working/FINDINGS.md`](../_working/FINDINGS.md) | Running findings log (F-001 … F-014), newest first |
| [`../_working/LIBRARY-REVIEW.md`](../_working/LIBRARY-REVIEW.md) | Fleet library re-point review |
| [`../_working/WORKLIST.md`](../_working/WORKLIST.md) | Fleet remediation worklist (42 boards) |

## The working tree

This repo is one checkout in a multi-repo working tree. Paths below are relative to this
repo's root; siblings sit one level up (`../`).

| Path | Purpose |
| --- | --- |
| `_planning` | **The plan.** Actionable, progresses, tracks status. (This directory.) |
| `_working` | Analysis, evidence, findings — the raw material the plan rests on |
| `../_reference` | Cloned upstream repos / fetched assets for deep factual reference — read-only, re-clonable |
| `.` (`kidl-spike`) | **This spike.** Python that regenerates the three boards below. |
| `../pkidl` | Scripted description language for **PCBs** (new; under dev) |
| `../skidl` | Scripted description language for **schematics** (mature, upstream; pinned to a local clone) |
| `../Loaf_x004` | Testbed 1 of 3 — backplane for power + I²C. **First spike target** (8 footprints). |
| `../Slice_RLHT` | Testbed 2 — 2-channel relay + thermocouple function card |
| `../Slice_DCMT` | Testbed 3 — 2-channel motor driver function card |

The three testbed projects are **read-only reference**. They are never modified by the
spike; generated output is compared against them.

## Related repos (not checked out here)

- **`KiCad-Master-Lib`** — symbols/footprints (`KMLib_*`) used by all three boards.
  Referenced via the `KICAD_MASTER_LIB` environment variable; keep a working checkout
  outside this tree and point the variable at it.
- **`bread-infra`** — BREADS specs, JSON schemas, and reusable CI workflows (KiBot, DRC,
  manifest validation) that the Slices call into.
