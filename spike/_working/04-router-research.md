# Router Research Pass (P5)

Status: completed 2026-10-23.

Decides which autorouter runs inside the physical layer's **proven DSN/SES loop**
(`00-context-and-architecture.md` §3.6): `pcbnew.ExportSpecctraDSN` → router →
`pcbnew.ImportSpecctraSES`, round-tripped into KiCad and judged by `kicad-cli pcb drc`.
The loop is already verified mechanically possible; this pass picks the router. Freerouting
was the incumbent going in, not the decision.

Scoring criteria (from the plan): **headless operation · licence · 2-layer quality ·
determinism · CI viability** — with **long-term reliability** added, because the maintainer
is willing to adopt or even help maintain a project *if it is provably a good long-term
bet*. So "young and solo today" is not an automatic reject; an unverifiable determinism
claim or a dead project is.

This is a documented research pass from primary sources, **not a bench test**. No router was
run here: the sandbox cannot run `kicad-cli`/`pcbnew` (nested-bubblewrap
`open(O_TMPFILE): Read-only file system`), so it cannot produce the `.dsn` a route needs.
Routing Loaf_x004 and diffing SES is a later phase and a hand step on a machine where KiCad
runs. Evidence below is from each project's repo, releases, issues and design docs as of
2026-10-23; what could not be verified is listed at the end.

## The biggest finding is not the router — it is the DSN input

Reproducibility is gated by the **byte-stability of the DSN we feed the router**, not by the
router alone. Freerouting issue **#1016** (filed 2026-10-23) shows that regenerating a KiCad
board assigns fresh UUIDs, which reshuffle the exported DSN placement order, which changes
the routed result **even with a fixed seed** — while re-routing one byte-identical DSN was
reproducible. The variation lives in the generate→export step, not the router.

Consequence for this project: **pkidl must emit canonical, byte-stable DSN** (stable UUIDs /
deterministic placement order) for any build to reproduce. That is a requirement a
deterministic compiler should meet anyway, and it de-risks *every* router choice — we own
determinism at the boundary rather than trusting the router's internals. An upstream fix
(Freerouting PR #1022, "stabilize DSN placement allocation for seeded routing") is in flight,
but we should not depend on it; DSN canonicalization belongs in our generator.

## The DSN/SES + open-licence constraint filters the field

A candidate only qualifies if it consumes `.dsn`, emits `.ses`, is open-licensed, and can
run headless. The field sweep (2026-10-23):

| Candidate | Licence | Fits DSN/SES loop? | Determinism | Maturity | In/Out |
| --- | --- | --- | --- | --- | --- |
| **Freerouting** | GPL-3.0 | Yes — native, the de-facto baseline | Deterministic single-threaded (v2.5.0) | Mature, active | **IN** |
| **fastroute** (Rust) | GPL-3.0-or-later | Yes — same `.dsn`→`.ses` CLI, no Java | Deterministic by design; `--parity` = byte-identical to Freerouting | <1 month old, solo | **IN (watch)** |
| **CoppeRoute** (Rust) | GPL-3.0-only | Yes — DSN/SES *and* direct `.kicad_pcb` | Byte-for-byte gate (roadmap invariant) | ~5 weeks dormant, solo | **IN (watch)** |
| freeroute (pure-Python) | GPL-3.0-or-later | Yes — stdlib-only port, pip-installable | Claimed, **unverified** | Alpha, leaves nets unrouted | Watch |
| TopoR Lite | Proprietary | Imports DSN/exports SES | — | Commercial, Windows-only | OUT (licence, no CI) |
| pcb-rnd toporouter | GPL | No — its own autoroute path shells out to Freerouting | — | Stagnant | OUT |
| tscircuit autorouter | MIT | No — operates on circuit-json, not Specctra | — | Active, funded | OUT (wrong interface) |
| Topola | MIT | Unconfirmed DSN; no SES evidence | — | Pre-alpha (v0.1.0) | OUT (too early) |
| KiCadRoutingTools | MIT | No — grid A* on `.kicad_pcb`, no DSN/SES | — | 3★, no releases | OUT (not DSN/SES) |

Only Freerouting and its two Rust descendants clear the bar. Notably, **only CoppeRoute (and
freeroute, unverified) explicitly asserts byte-for-byte determinism**; Freerouting is
deterministic for fixed input + single-threaded settings; everyone else is silent. The MIT
options (tscircuit, Topola, KiCadRoutingTools) are the only permissive-licence routers, but
none does a deterministic DSN→SES round-trip today — worth remembering only if a non-GPL
licence ever becomes a hard requirement.

## The three viable routers

| | **Freerouting 2.5.0** | **fastroute** | **CoppeRoute** |
| --- | --- | --- | --- |
| Licence | GPL-3.0 | GPL-3.0-or-later | GPL-3.0-only |
| Headless | JVM jar (Java 25); native CLI exists but buggy | Rust CLI, no Java | Rust CLI, no Java |
| DSN/SES | Native | Native (same flags) | Native + direct `.kicad_pcb` |
| Determinism | Single-threaded, deterministic (v2.5.0); input-byte sensitive (#1016) | By design (`fr-jcompat` Java-bit-exact, no-FMA → arch-independent); `--parity` byte-identical to Freerouting | Byte-for-byte gate by construction (index-order commits, stable seeded RNG, no threaded maze) |
| Determinism **verifiable by us?** | Yes (release + issues + PCBench) | **No** — 20-board parity claim needs the author's private reference checkout; skipped tests report as *passed* | Partly — stated in roadmap doc, not README; no public release to pin |
| Maintenance | Bus factor 1 (andrasfuchs), donation-funded, **monthly releases**, responsive, 1157-board regression harness | Bus factor 1 (pseudonymous), **no CI**, 10-day silence, 10 tagged releases in 2 weeks | Bus factor 1 (solo + heavy AI assist), **dormant ~5 weeks**, 0 releases |
| 2-layer evidence | PCBench Tier B (2–4 layer) clean-completion 3.4%→**61.6%** in v2.5.0 | None quantitative | None quantitative |

### Freerouting 2.5.0 — the only option that clears the long-term bar today

GPL-3.0, actively maintained with a real 1157-board regression harness ("PCBench") gating
changes, releasing roughly monthly, same-day issue response. v2.5.0 makes the optimizer a
deterministic engine ("Results are consistent and repeatable across runs"; it also *removed*
the old `RANDOM`/`GREEDY`/`HYBRID` strategies, confirming earlier versions were not
deterministic). Bus factor is 1, but that is heavily mitigated: it is *the* autorouter the
KiCad ecosystem depends on, GPL-3.0 with 346 forks, so it would be forked if abandoned.

Two operational constraints: **use the JVM jar, not the native CLI** — the brand-new GraalVM
native binary crashes on some KiCad exports (#1019, `EnumMap` serialization), and the jar is
the battle-tested path our loop already uses. And **pin a version in CI** rather than
tracking latest, because 2.5.0 was a breaking release and more are coming (dropping legacy
SWIG, the Java-25 requirement).

### fastroute — the primary challenger, and a zero-cost swap

A Rust port whose determinism engineering is genuinely first-class: a `fr-jcompat` crate
emulates Java's `Random`/`TreeMap`/`StrictMath` bit-for-bit and avoids fused-multiply-add, so
output is designed to be identical across thread counts *and architectures* — exactly what a
reproducible build artifact wants. `--parity` mode is byte-identical to a pinned Freerouting
commit, which makes it a **zero-switching-cost swap** with Freerouting in either direction.

It is not the primary today because its reliability is unproven, not because it is young:
<1 month old, single pseudonymous maintainer with no track record, **no CI**, silent for 10
days, and — decisively — the headline "20 boards byte-identical" claim **cannot be reproduced
from a public clone**: the parity tests silently skip (and report as passed) when the
git-ignored Freerouting reference checkout is absent. So that number is the author's, not a
committed gate we can re-run. This is the one to adopt *and contribute to*: standing up CI
and a self-contained parity fixture set would be a high-value first PR that directly
de-risks it, and contribution is set up and welcomed (external PRs merged within days).

### CoppeRoute — strongest determinism design, best KiCad fit, least sustainable

Technically the best fit: native DSN/SES **and** direct `.kicad_pcb`, plus built-in DRC that
emits KiCad's own report schema (diffable against `kicad-cli pcb drc`). Its determinism
posture is the strongest *stated* of the field — the roadmap treats byte-for-byte identity as
an in-force invariant, rejects non-deterministic threading, commits speculative results in
index order ("byte-identical to the sequential golden by construction"), and plans a stable
named seeded RNG "identical on 1 thread or 64, on arm64 or x86-64." But it is the least
sustainable: created 2026-09-01, **dormant ~5 weeks**, 0 stars, 0 releases, solo and heavily
AI-assisted — "a serious personal R&D spike, not a sustainable project yet." Its DRC is also
incomplete (optimises against 2 rules, graded against 23; gaps in zones/keepouts). Watch;
reconsider if it revives and cuts a release.

## Decision recorded

| Decision | Rationale |
| --- | --- |
| **Route backend: Freerouting 2.5.0, JVM jar (Java 25).** Pin the version in CI. | Only option that clears the long-term-reliability bar: mature, active, regression-gated, GPL-3.0, deterministic single-threaded. Avoid the native CLI until #1019 is fixed. |
| **pkidl emits canonical, byte-stable DSN.** | Reproducibility is gated by DSN input bytes, not the router (#1016). Owning canonicalization de-risks every router choice; do not depend on upstream #1022. |
| **Validate determinism on our own boards**, via the existing DRC loop. | No router's self-reported determinism is trusted; our DRC-judged round-trip is the oracle. |
| **Contribute-and-watch: fastroute (primary), CoppeRoute (second).** | Both GPL-3.0, Java-free, determinism-by-design. fastroute's `--parity` makes it a zero-cost Freerouting swap; its missing CI is an obvious, de-risking first contribution. |
| **Router output is never source of truth.** | Round-tripped via `ImportSpecctraSES`, judged by `kicad-cli pcb drc`. Unchanged by this pass. |

## To verify on a hardware-capable machine (not this sandbox)

- Route Loaf_x004's `.dsn` through Freerouting 2.5.0 (JVM jar); confirm a clean 2-layer
  result and `kicad-cli pcb drc` pass.
- Confirm **run-to-run byte-identical SES** from a byte-identical DSN on our board — and
  confirm that a regenerated board produces a byte-identical DSN once pkidl canonicalises it
  (the #1016 failure mode, closed on our side).
- Spot-check fastroute `--parity` against the same board to confirm the byte-identical claim
  holds for Loaf before relying on the reserve.

## Could not verify

- That fastroute's 20-board byte-identical parity claim holds (needs the author's private
  reference checkout + a Java parity jar; not runnable from the public repo, and its tests
  skip-as-pass without it).
- CoppeRoute's determinism in practice (stated in a roadmap doc, not the README; no release
  to pin and no public benchmark run).
- freeroute's determinism invariant (its live repo failed to load; only a cached third-party
  quote and a silent PyPI page).
- Any isolated *simple-2-layer* benchmark for any candidate — Freerouting's PCBench Tier B
  mixes 2–4 layers and is the maintainer's own harness. Our DRC-judged loop is the right
  oracle.
- Nothing was run in this sandbox (no `kicad-cli`/`pcbnew`).

## Sources

- Freerouting:
  [v2.5.0 release](https://github.com/freerouting/freerouting/releases/tag/v2.5.0) ·
  [repo](https://github.com/freerouting/freerouting) ·
  [#1016 seeded output changes on UUID reshuffle](https://github.com/freerouting/freerouting/issues/1016) ·
  [#1022 DSN placement stabilisation](https://github.com/freerouting/freerouting/pull/1022) ·
  [#1019 native-CLI EnumMap crash](https://github.com/freerouting/freerouting/issues/1019) ·
  [#878 deterministic BatchOptimizer](https://github.com/freerouting/freerouting/pull/878) ·
  [PCBench](https://freerouting.org/benchmarks)
- fastroute: [repo](https://github.com/parisxmas/fastroute) ·
  [PORTING.md](https://raw.githubusercontent.com/parisxmas/fastroute/main/docs/PORTING.md) ·
  [site](https://fastroute.baltavista.com/)
- CoppeRoute: [repo](https://github.com/emshotton/copperroute) ·
  [roadmap-draft](https://raw.githubusercontent.com/emshotton/copperroute/main/docs/plan-10-prep/roadmap-draft.md)
- Field sweep: [freeroute (PyPI)](https://pypi.org/project/freeroute/) ·
  [TopoR](https://en.wikipedia.org/wiki/TopoR) ·
  [tscircuit autorouter](https://github.com/tscircuit/tscircuit-autorouter) ·
  [Topola](https://docs.rs/crate/topola/0.1.0) ·
  [KiCadRoutingTools](https://github.com/atomic14/KiCadRoutingTools)
