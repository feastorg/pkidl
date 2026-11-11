# Prior-art survey: what it changes for pkidl

Step 2 of the charter, done 2026-11-11, in two halves:

- [`pcb-tools.md`](pcb-tools.md): tools for PCB design from code (tscircuit, JITX,
  atopile, pcbflow, KiCad's scripting and IPC API, Freerouting, KiCad-Autoplace,
  KiCadRoutingTools, kicad-tools, padne, and the closed AI layout services).
- [`design-languages.md`](design-languages.md): lessons from CadQuery and build123d,
  OpenSCAD, SKiDL, Amaranth and Chisel, atopile's own language, UI constraint layout,
  Terraform and Pulumi, and evidence on APIs for LLM agents.

Every claim in them carries its source; claims not confirmed from a primary source are
marked unverified. Two were re-checked against the primary source for this summary:
KiCad's IPC API needs a running GUI in KiCad 9 and 10, with headless `kicad-cli`
support "added for KiCad 11" (KiCad developer docs); and CodeAct's "up to 20% higher
success rate" for code actions over the alternatives, across 17 LLMs
(arXiv 2402.01030).

## The architecture holds

- **Write `.kicad_pcb` files and judge them with `kicad-cli`.** It is the only route
  that runs headless on KiCad 10 and 11. The IPC API needs the GUI until KiCad 11
  (unreleased); the SWIG `pcbnew` bindings were removed from nightlies in March 2026 and
  go in KiCad 11, taking tools built on them (KiCad-Autoplace, atopile's plugin) with
  them. Revisit the IPC API when KiCad 11 ships, for checks `kicad-cli` cannot run.
- **Keep the router behind an interface.** Freerouting is the only open router worth
  driving, and its maintainer is down to about four hours a week. Its self-hosted REST
  API returns the session plus unrouted count, violations and partial results on
  timeout: better than the CLI pkidl uses now.

## The bet is open: nobody does it

- **No tool checks copper intent on the finished board.** None of JITX, tscircuit,
  atopile or KiCad's DRC states a current requirement and checks the copper against it.
  The nearest, KiCadRoutingTools, grades requested track widths and estimates plane
  current from average width, not the narrowest neck. padne computes real current
  density, but against no stated requirement.
- **No open tool writes a block's layout in code.** atopile's layout reuse and KiCad
  10's design blocks both copy a hand-drawn KiCad fragment (atopile's cannot rotate it).
- **Verified intent exists only for signal integrity, and only closed.** JITX states
  impedance, timing, skew and loss as constraints and reports each met or not with the
  measured value. It is the model for pkidl's layer 4, extended to power, current,
  return paths and heat.

## What to borrow

| From | What |
|---|---|
| tscircuit | Positions relative to parts, pads and the edge (`calc(R1.pin1.minX - 2mm)`) |
| JITX | Placement as a tree of parent-relative frames (block reuse); constraints reported met or not, with measured values |
| KiCadRoutingTools, kicad-tools | Intent stored with the board and the result graded against it; creepage exported as KiCad DRC rules |
| padne | Current density on real copper, as an independent check (GPL: run as a separate process) |
| KiCad-Autoplace | A placement change is kept only if routability does not drop |
| Freerouting REST API | Structured routing results, partial output, DRC as JSON |
| Terraform | Plan as data before apply (`plan -out`, `-json`, `-detailed-exitcode`) |
| Amaranth | Every object records its source line; errors and "created but never used" warnings point at it |
| build123d (algebra mode) | Explicit objects combined by functions and operators; no builder context |

## How the language should be built

- **Author in Python.** No new syntax to learn or parser to maintain (atopile still runs
  on ANTLR), and the whole language comes with it. Code-generating tools, LLMs included,
  also write code more reliably than JSON and worse in languages with little training
  data.
- **Declarative in effect.** Python calls register intent in one typed model; solving
  and writing KiCad come after (Pulumi's model, Amaranth's elaborate-then-emit).
- **The model serialises to canonical data,** for the plan a reviewer reads, for
  machine-generated intent, and for diagnostics. People do not author it.
- **No ambient state,** not even a `with Board():` block: build123d's builder mode and
  SKiDL's default circuit both show the traps.
- **Typed selectors,** with strings as sugar over them, selecting by reference, net and
  pin rather than geometry.
- **Identity comes from the netlist and the intent, never from execution order.**
- **Every solver reports what it could not decide:** under- and over-constrained
  placement names the free parts and the conflicting intents, with a deterministic
  tie-break.
- **Numbers before pictures.** In a test of CAD-as-code tools, renders caught only coarse
  mistakes; numeric checks caught the defects that mattered. Renders stay, but a build is
  judged by layer-4 measures.

## Left open

- **Whether tools that generate or revise boards should edit the data form or the
  Python.** The evidence splits: CodeAct says code; HCL's JSON form says data for
  generated parts. Step 4 settles it cheaply: write two or three corpus boards in Python,
  dump the model, and make the same revision both ways. Until then the model stays
  round-trippable.

## Changes to the charter

Made alongside this survey: the design principles now say algebra-style explicit
objects (no builder context), typed selectors with string sugar, identity from the
netlist, every solver reporting under- and over-constraint, numbers before renders, and Python
authoring over a serialisable model; the KiCad and router
findings go under "Don't rebuild what exists".
