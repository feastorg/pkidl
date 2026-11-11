# Router bake-off

Decided 2026-11-10, after phase 6's step 0 came back no-go (`../_working/05-board-review.md`, "Phase 6, step 0").

## The questions

1. **The crux: does any router keep a pour in one piece while routing signals across it?** Freerouting can't, either way round. With pours as obstacles, DCMT's signals have no way through (24 unrouted). Without them, the pours get cut into pieces.
2. **How do the candidates compare on ordinary work?** Our five boards, and external two-layer boards with power pours: completion, DRC, determinism, run time.
3. **What it decides:**
   - stay on Freerouting, and contribute there;
   - switch routers, or run two;
   - or accept that power layout stays a designer's job.

## The field, refreshed 2026-11-10

The 2026-10-23 survey (`../_working/04-router-research.md`), re-checked:

| Router | Status | In? |
|---|---|---|
| Freerouting 2.5.0 | Baseline. `plane_as_obstacle` makes pours obstacles. Latest release still 2.5.0. | Yes, run with the flag off and on |
| fastroute | Rust port of Freerouting; v0.1.14 (2026-10-13), last push 2026-11-03; 119 stars | Yes |
| copperline | C++20, headless, JSON-first; created 2026-09-14, active; v0.1.0, no release tag. Pours: foreign pours are obstacles at exact clearance. No licence file. | **Built, then dropped.** It reads none of our inputs: pkidl's DSN, KiCad's DSN (`(boundary (path ...))`), KiCad 5 boards (no pads read) and KiCad 10 boards (`(net "name")` on pads). Two candidate reports. |
| rpmroute (formerly freeroute) | Pure Python, DSN in, SES out; negotiated congestion | Yes, if it installs from a pinned commit |
| OpenRoute (openpcb) | MIT; Windows app plus CLI; one push (2026-10-25), 0 stars | Only if its CLI builds and runs on Linux |
| Open PCB & IC Engineer 0.2 beta | GPL; reads `.kicad_pcb`; fills pours itself and keeps tracks off plane layers; posted 2026-11-07 | **No:** its source is behind a sign-up form that needs contact details. Your call. |
| CoppeRoute | No push since 2026-09-16, no release | No |
| tscircuit autorouter | Works on circuit-json, not DSN | No |
| KiCadRoutingTools | `.kicad_pcb` only; no push since 2026-07-11 | No |

**What the projects claim on the crux:** none says it keeps a pour connected while crossing it. copperline and Freerouting both make pours obstacles, which is the failing half of the crux. Only measurement settles it.

## The boards

- **Ours (5):** the single-stage DSN of each board from `main` (every net, no fixed wiring), plus Freerouting's two-stage route as built today.
- **The crux case:** DCMT with its pours filled by KiCad before routing, given as planes (step 0's `p6b` DSN), plus that board's routed-pour check.
- **External (7):** two-layer PCBench boards (1142 in all), from the KiCad-exported DSNs in Freerouting's repository at `842ad83`. Motor drivers and supplies come first, chosen from its `catalog.json` by layer count and zones. Each board keeps its own licence; PCBench's MIT covers PCBench's code, not the designs. The fixtures are used locally and never committed.
  - **Their unrouted DSNs carry no pours** (0 planes in all 7, and no zones in the unrouted boards). So they test ordinary routing only.
  - **For the crux,** the three that have planes in `reference-routed.dsn` (the gimbal board 6, the BMS 4, OpenMPPT 9) also run with those planes restored.

## What gets measured

For each router and board:

- Connections left unrouted: the router's own count, and an independent one from the SES and DSN (step 0's checker, validated on `main`'s complete route).
- On our boards, imported through pkidl: KiCad DRC errors, unconnected items, and pour pieces per net.
  - **External boards are checked from the SES alone.** PCBench's notes say headless SES import into KiCad 10 isn't reliable, so KiCad doesn't see their routed result.
- Run time, and whether two runs give byte-identical SES.
- **Crux:** pieces per pour net after the fill, and DRC unconnected.

## How

- **Builds:** each candidate is built from a pinned commit in a scratch clone, with toolchains this machine already manages (rustup, cmake, g++, uv, node). Nothing is installed system-wide. If a router wins, it gets added through workstation-configs before anything depends on it.
- **Scripts:** the harness lives in the session scratchpad.
- **Results:** they go into `../_working/07-router-bakeoff.md`, with the command behind every figure.
- **Size, estimated:** 5 routers × about 14 boards × 2 runs is about 140 routes, at 30 s to 3 min each, so 2–4 hours. It runs in the background.

## Not in scope

- Tuning any router beyond its documented options.
- Changing pkidl's routing. That depends on the outcome.
- Filing upstream issues. Candidates are reproduced minimally and checked against the source first (decided 2026-11-10).
