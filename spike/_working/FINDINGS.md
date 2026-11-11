# Findings Log

Running record of defects and discoveries, with evidence. Newest first.

**Purpose:** these are things that were *not obvious* and cost real effort to find. Most
are invisible from inside KiCad and silently pass CI. Each entry records what's wrong, the
evidence, the blast radius, and the status — so nothing gets rediscovered from scratch.

Status: `OPEN` · `FIXED` · `WONTFIX` · `INVESTIGATING`

| ID | Finding | Blast radius | Status |
| --- | --- | --- | --- |
| [F-022](#f-022) | SKiDL writes every symbol `on_board yes` and `in_bom yes`; off-board and non-BOM parts cannot be expressed | upstream | OPEN (worked around) |
| [F-021](#f-021) | **`Slice_RLHT`'s `HV Relay` netclass matches no net; applied, the board has 93 clearance violations** | **Slice_RLHT** | **OPEN** (Slice_RLHT#89) |
| [F-020](#f-020) | SKiDL's two-pin snap drops net labels, so KiCad renames user-named nets `Net-(...)` | upstream | OPEN (worked around) |
| [F-019](#f-019) | A pinless part (mounting hole) crashes SKiDL's schematic placer | upstream | OPEN (worked around) |
| [F-018](#f-018) | SKiDL draws hierarchy cosmetically: a file per instance, global labels, no sheet pins | upstream | OPEN (accepted) |
| [F-017](#f-017) | `netlist_to_skidl` corrupts what it converts: shorts colliding nets, renames fields | upstream | collision FIXED on master (skidl#332, unreleased); rest OPEN |
| [F-016](#f-016) | Generated schematic placement is not byte-stable (netlist and board are) | spike | OPEN |
| [F-015](#f-015) | SKiDL 2.2.3 emits power-symbol instances with no `lib_symbols` definition | upstream | FIXED (SKiDL 2.3.0) |
| [F-014](#f-014) | ~~SKiDL cannot read KiCad 10's sharded `.kicad_symdir` symbol libraries~~ — RETRACTED for installed KiCad (packed single files); true of the source repo, which CI now packs | spike | CLOSED |
| [F-013](#f-013) | 38 of 40 `slice.yaml` manifests are never schema-validated | fleet | OPEN |
| [F-012](#f-012) | **No PR gate anywhere — ERC/DRC only run *after* merge** | **fleet** | **OPEN** |
| [F-011](#f-011) | **Fleet library rot: 39/42 boards have unresolvable parts; 60 exist nowhere** | **fleet** | **OPEN** |
| [F-010](#f-010) | Self-inflicted: `Thermal_Pad` rename broke 15 previously-working boards | fleet | OPEN |
| [F-009](#f-009) | D1 is DNP on the PCB but not in the schematic | Slice_DCMT | OPEN |
| [F-008](#f-008) | CI container is `kicad9_auto`, projects are KiCad 10 | fleet | OPEN |
| [F-007](#f-007) | KiCad-Master-Lib absent from CI → ~102 spurious warnings | fleet | OPEN |
| [F-006](#f-006) | `Makefile` ERC and DRC targets are swapped | Slice_DCMT (+?) | OPEN |
| [F-005](#f-005) | **DRC schematic-parity gate is fake — mismatches never fail CI** | **fleet** | **OPEN** |
| [F-004](#f-004) | `Slice_RLHT` manifest declares the wrong primary IC | Slice_RLHT | OPEN |
| [F-003](#f-003) | SKiDL: `generate_schematic` never calls an `empty_footprint_handler` passed to it | upstream | FIXED on master (skidl#331, unreleased), with a regression |
| [F-002](#f-002) | First-party parts filed under third-party library nicknames | fleet | FIXED |
| [F-001](#f-001) | Library resolution lived only in a global KiCad config | fleet | FIXED |

---

## F-022 — SKiDL writes every symbol on_board and in_bom

SKiDL 2.3.0's kicad10 schematic writer hardcodes `(in_bom yes)` and `(on_board yes)` for
every part symbol (`tools/kicad10/sexp_schematic.py`, lines 351-352, 512-513 and
900-901). A part the original marks off-board or out of the BOM cannot be written as such:

- Slice_RLHT's SW1/SW2 (E-stop switches) and Slice_DCMT's M1/M2 (motors) are off-board
  in the originals. The generators leave them out; the tests drop their pins from the
  comparison.
- Slice_DCMT's NT1 (the GND-GNDPWR net tie) is out of the BOM in the original, and its
  footprint carries `exclude_from_bom`. Parity fails on the difference
  (`footprint_symbol_mismatch`), so `slice.place_board` places every symbol-linked
  footprint `in_bom` to match the symbol, and NT1 lands in the BOM.

Not checked on 3.0.0, where schematic writing moved to schematizer. Nothing filed.

**Status:** OPEN, worked around in the generators.

---

## F-021 — `Slice_RLHT`'s `HV Relay` netclass matches no net

`Slice_RLHT@a7308f3`'s `BREAD_Slice.kicad_pro` assigns `HV Relay` (3.0 mm track, 1.25 mm
clearance) by 13 exact-name patterns: `NC1`, `NO1`, `IN1`, `ESTOP1`, `FUSE1`, the same with
`2`, `ESTOPA2`, `ESTOPB2` and `HV Line`. None of them is a net on the board: KiCad's netlist
export names the relay-switched nets `/Relay/IN`, `/Relay/NC`, `/Relay/NO`, `/Relay1/...`,
`Net-(J4-Pin_1)`, `Net-(J4-Pin_2)` and the `J5` pair. So the class applies to nothing, and
DRC checks those lines at the Default 0.2 mm clearance.

Those 10 nets are the ones the board draws in 3 mm track (95 segments). On a copy of the
original with the 10 real names added as `HV Relay` patterns, `kicad-cli pcb drc
--severity-all` reports **93 `clearance` violations** (none before), down to 0.50 mm. Among
them: `/Relay1/NC` 0.68 mm from `/Relay1/NO`, `Net-(J5-Pin_2)` 0.50 mm from the B.Cu GND
pour, and `Net-(J5-Pin_1)` 0.71 mm from R5's logic pad.

The generated board (phase 3) assigns `HV Relay` to the same 10 nets
(`test_hv_relay_netclass_covers_the_original_3mm_nets`) and passes DRC with it.

**Status:** OPEN, filed as feastorg/Slice_RLHT#89 (2026-11-07). Still true on
`bfc0b82` (2026-11-04): the board and sheets are byte-identical, the patterns unchanged.

---

## F-020 — SKiDL's two-pin snap drops net labels

SKiDL 2.3.0's kicad10 backend runs `snap_two_pin_parts` after placement whenever
`auto_stub=True`, and always in the labels-only fallback. It moves resistors, capacitors and
similar parts so a pin lands on the pin it connects to, then suppresses the labels it
considers redundant. A net joined only by touching pins then carries no label, and KiCad
names it itself: generating Slice_RLHT, `CH1_LED`, `CH1_LINE` and `TC1_IN+` (and their
channel-2 twins) came back from KiCad as `Net-(R5-Pad2)`, `Net-(J4-Pin_1)` and
`Net-(U2-T+)`. The board's pads carry the names given in Python, so DRC reported 16
`net_conflict` parity errors. Marking every net `stub` does not prevent it.

The topology is right; only names are lost. `rlht.build` replaces `_snap_two_pin_parts`
with a no-op for its `generate_schematic` call; with it off, KiCad's export of the
generated schematic has no auto-named net and DRC parity is clean. Nothing filed:
SKiDL 3.0.0 (2026-10-16) moved schematic drawing into the separate `schematizer`
package, so this code is no longer in SKiDL; not re-tested on 3.0.0 + schematizer.

**Status:** OPEN, worked around in `boards/rlht.py`.

---

## F-019 — A pinless part crashes SKiDL's schematic placer

On SKiDL 2.3.0, `generate_schematic(auto_stub=True)` raises `AttributeError: 'NoneType'
object has no attribute 'tx'` (`schematics/place.py`, `similarity_force`) as soon as the
circuit holds one part with no pins, such as `Mechanical:MountingHole`. Reproduced with one
resistor plus 1, 2 or 4 holes; one resistor alone, or plus two unconnected resistors, works.

Slice_RLHT's mounting holes are therefore not symbols in the generated circuit: the layout
places them as board-only footprints (`(attr board_only)`), which schematic parity skips.
Nothing filed: sKiDL 3.0.0 (2026-10-16) moved schematic drawing into the separate `schematizer`
package, so this code is no longer in SKiDL; not re-tested on 3.0.0 + schematizer.

**Status:** OPEN, worked around in `boards/rlht_layout.py`.

---

## F-018 — SKiDL draws hierarchy cosmetically

On SKiDL 2.3.0 (kicad10 backend), `generate_schematic(auto_stub=True)` for two
`@subcircuit`s instantiated twice each (RLHT's relay and MAX31855K) writes one sheet file
per instance (`exp_relay1.kicad_sch`, `exp_relay2.kicad_sch`, ...). The root's four sheet
symbols carry **0 sheet pins**, and each sub-sheet connects through 6 **global** labels named
after the root nets (`IN1`, `SW1`, ...), with 0 hierarchical labels. The original
`relay.kicad_sch` is one file shared by two instances, connected by 6 hierarchical labels.
Without `auto_stub`, routing fails (`GlobalRoutingFailure` on `TC_CLK`) and no schematic is
written.

The netlist is right: KiCad's export of the generated hierarchy is topology-equivalent to
the original's four sheet instances (20 parts, 29 nets). Consequence: a generated sub-sheet
cannot be published as a reusable design block without rewriting its port labels.

**Status:** OPEN, accepted for phase 3 (hierarchy is proven at source and netlist level).

---

## F-017 — `netlist_to_skidl` corrupts what it converts

SKiDL 2.3.0's `netlist_to_skidl`, run on KiCad's export of Slice_RLHT, produces runnable
code that differs from the netlist it came from:

- **Colliding net names short nets together.** `Net-(U2-T+)` and `Net-(U2-T-)` both become
  the identifier `Net__U2_T__`; the second assignment wins, so running the generated
  `MAX31855K` puts `C5.1 C5.2 FB1.1 FB2.1 U2.2 U2.3` on one net — the thermocouple inputs
  shorted, and the filter capacitor shorted across itself.
- **Field names are rewritten.** Every `Datasheet` field comes out as `TC_DATAsheet`.
- **Reuse is lost.** Each sheet *instance* becomes its own function (`Relay`, `Relay1`), not
  one subcircuit called twice.

Usable as a starting point only behind a netlist-equivalence check. The collision is filed
as devbisme/skidl#332; `netlist_to_skidl.py` is unchanged in 3.0.0.

**Status:** the collision is fixed on SKiDL master in `efff5d7` (2026-11-07), not yet
released: each net gets a unique identifier, suffixed on a clash with another net, a part
reference, a sheet name, a name `from skidl import *` exports, or a Python keyword. The
field rename and the one-function-per-instance output were not reported and are OPEN.

---

## F-016 — Generated schematic placement is not byte-stable at the pinned SKiDL

`boards/loaf.py` generates the same netlist on every run, but not the same `.kicad_sch`.
SKiDL's placer and router seed `random` from `options.get("seed")`, which defaults to
`None`; passing `seed=0` removes that source but not all of the variation.

Evidence (`uv run python -m kidl_spike.boards.loaf`, `sha256sum build/loaf/loaf.kicad_sch`,
`seed=0`): `PYTHONHASHSEED` 0 produced `b6b057e7…` on one run and `aeff5e1b…` on the next;
`PYTHONHASHSEED` 7 did the same. Three distinct schematics were seen in total; the diffs are
part positions (e.g. `(at 143.51 90.17 0)` vs `(at 142.24 90.17 0)`). `loaf.net` was
byte-identical across three runs with different hash seeds, and a generated schematic
re-exported through KiCad matches the original on all 7 nets; the other placement variants
were not re-exported.

The remaining source was not isolated. The same hash seed giving different output rules out
string-hash order; ordering by object identity in the placer is the likeliest candidate,
unconfirmed.

**Why it matters:** "KiCad files are build artifacts" wants byte-stable artifacts, and
Freerouting #1016 shows routers are sensitive to input byte order. The schematic is not the
router's input (pkidl's DSN is), so this does not block phase ①.

**Re-checked on SKiDL 2.3.0 (kicad10 backend), 2026-10-23: still present.** Five processes
(`PYTHONHASHSEED` 0, 0, 1, 7, 7) gave five different `loaf.kicad_sch` hashes. The generated
board (`loaf.kicad_pcb`) was byte-identical in all five: it takes only the schematic's
symbol UUIDs and values, which are stable.

**Status:** OPEN.

---

## F-015 — Pinned SKiDL emits power-symbol instances with no `lib_symbols` definition

At the then-pinned commit (`e19d9a6a`, SKiDL 2.2.3), `generate_schematic(auto_stub=True)` placed one
`power:+12V` / `power:GND` instance per power pin (13 and 19 for the Loaf) but wrote **no**
definition for them into `(lib_symbols)`. KiCad then has no power pin to name the net, so
re-exporting the generated schematic's netlist fragmented `+12V` and `GND` into single-pin
`Net-(…)` nets. The five signal nets, emitted as `global_label`s, matched the original
exactly.

Root cause (`skidl/src/skidl/tools/kicad9/sexp_schematic.py` at the pin): whether to emit a
power symbol and how to define it come from two different sources.

- `_get_power_symbol_names()` decides to emit a power symbol. When `power.kicad_sym` is not
  found it falls back to a **hardcoded** name set that includes `+12V` and `GND`.
- `_extract_power_lib_symbol_raw()` produces the definition. It has **no** fallback, and
  returns `None` when the file is not found.
- `_get_power_lib_text()` looks only in `$KICAD9_SYMBOL_DIR`, `/usr/share/kicad/symbols`,
  `/usr/local/share/kicad/symbols` and `~/.local/share/kicad/9.0/symbols`. On the flatpak,
  with the variable unset, it finds none of them.

**Workaround (in-repo while on 2.2.3; removed with the bump):** `libs.configure_skidl()` set
`KICAD<ver>_SYMBOL_DIR` to the stock symbol directory it already resolves. With it, both
definitions are embedded and the re-exported netlist matches `Loaf_x004` on all 7 nets.

**Upstream:** fixed after our pin; nothing to file. `devbisme/skidl#308` ("emit
power-symbol lib_symbols from placed instances", merged 2026-06-09, `d7d03848`, not an
ancestor of `e19d9a6a`) derives the definitions from the instances placed on each sheet.
Upstream master also loads names and definitions from one library through SKiDL's normal
search path (`SchLib("power")`), so a missing library fails loudly instead of emitting
dangling instances. Verified by reading upstream master's source, not by running it; that
happens at the deferred pin bump, gated by `tests/test_loaf.py`.

**Status:** FIXED by the bump to SKiDL 2.3.0 (`b94f04d4`), and the workaround is removed.
With no `KICAD*_SYMBOL_DIR` set, the generated schematic embeds the `power:+12V`, `power:GND`
and `power:PWR_FLAG` definitions, its KiCad netlist export matches the original on all 7
nets, and the ERC and DRC gates pass.

---

## F-014 — RETRACTED: SKiDL reads KiCad 10 stock symbols; the CI failure was a missing stock library

**This finding was a misdiagnosis.** It is kept, not deleted, so the wrong turn is on
record. The original claim — that SKiDL's `lib_suffix = [".kicad_sym"]`
(`skidl/src/skidl/tools/kicad9/lib.py:31`) cannot read KiCad 10 stock symbols because
KiCad 10 "ships them as sharded `.kicad_symdir` directories" — is false. It was inferred
from a CI error, never reproduced.

What is actually on disk (KiCad **10.0.6** flatpak, this machine):

- Stock symbols are **single-file** `.kicad_sym`, exactly what the backend reads —
  `Device.kicad_sym` is one 2.4 MB file. `find` over the whole flatpak symbol library
  returns **no** `.kicad_symdir` entries; the format does not exist here.
- Pointed at that directory, SKiDL resolves `Device:R` and `Device:C` cleanly.
- `just doctor` with the real `$KICAD_MASTER_LIB` wired in resolves all three sources —
  `Device:R` (stock), `AP63205WU-7_Buck_Regulator` (first-party), `WS2812B_5050`
  (vendored). The only failing check is `kicad-cli`, for an unrelated sandbox reason.

**Where the CI `FileNotFoundError: Can't open file: Device.` really came from:** the CI
`test` job installs no KiCad, so `libs.stock_dirs()` finds no stock symbol directory and
`Device` is on no search path — "not found anywhere", not "found but unparseable". This
overlaps F-007 (Master-Lib/stock libs absent from CI) and F-008 (CI runs a KiCad-9
container). The stock-part test now skips where no stock library is present
(`tests/test_libs.py`), which is correct for CI on its own terms.

**No SKiDL patch and no stock-part vendoring are needed for this.** Phase ① generation is
not blocked by symbol format.

**Residual, genuine, and tracked elsewhere:** CI cannot exercise stock-part resolution
because it provisions no KiCad symbol libraries (F-007/F-008). Separately, running SKiDL
inside the sandbox needs `XDG_DATA_HOME` pointed at a writable dir, or its library pickle
cache write to `~/.local/share/skidl/` fails with a read-only-filesystem error — an
environment note, not a defect.

**Update (2026-10-23) — the original claim was half right.** It is false for *installed*
KiCad and true for the *source* repo. `kicad-symbols` at tag `10.0.6` (`7800d914`) holds 223
`.kicad_symdir` directories and no single-file libraries (`Device.kicad_symdir` is 536
one-symbol files), and the pinned SKiDL cannot read that layout: pointed at it, CI failed
with `Can't open file: Device.` / `Connector.` KiCad's install packs each directory into a
single file with the tag's own `tools/kicad_lib_pack.py` (`CMakeLists.txt`,
`KICAD_PACK_SYM_LIBRARIES ON`). Packing `Connector`, `Device` and `power` that way gives
files byte-identical to the installed 10.0.6 flatpak's. kidl-spike's CI now runs that
packing step at the `WANT_KICAD` tag, so stock-part resolution runs in CI instead of
skipping. F-007/F-008 remain open for the fleet.

**Status:** CLOSED (retracted).

---

## F-013 — 38 of 40 `slice.yaml` manifests are never schema-validated

Only `Slice_DCMT` and `Slice_RLHT` have a `ci.yml` calling `bread-infra`'s
`validate-manifest.yml`. The other 38 Slices carry a `slice.yaml` that **nothing checks.**

The schema exists, the validator exists, the workflow exists — they are simply not wired up
in 38 repos. Compounds [F-004] (RLHT's manifest names the wrong IC): manifests can be both
unvalidated *and* untrue.

---

## F-012 — No PR gate anywhere ⚠️

**`docs-pipeline.yml` triggers only on `push: branches: [main]`.** There is no
`pull_request` trigger in **any** of the 42 boards.

ERC and DRC therefore run **only after a change has already merged.** Even once [F-005] is
fixed and the gate is real, **it still cannot block a bad PR** — it can only tell you that
`main` is already broken.

This is arguably more important than F-005: fixing the DRC severity makes the check *honest*,
but without a PR trigger it remains *advisory*.

---

## F-011 — Fleet library rot ⚠️⚠️

**The biggest finding in the project.** Surveyed all 42 boards with hardware in
`~/repos_feast` (40 `Slice_*`, 2 `Loaf_*`; `Loaf_CANPB` is an empty stub), resolving every
non-stock reference against the committed KiCad-Master-Lib tables. All repos verified current
with origin first.

```
39 of 42 boards have unresolvable library references
97 distinct broken references

  38  auto-remappable   — the part exists in kmlib/vendor under a different nickname
  60  GENUINELY MISSING — the part exists nowhere in any library
```

Only **3 boards are clean**: `Loaf_x004`, `Slice_DCMT`, `Slice_RLHT` — the three we just
fixed. Every other board is broken.

**The 59 are the crisis.** These parts survive *only* as embedded geometry inside
`.kicad_pcb` / `.kicad_sch` files. They are not in KiCad-Master-Lib, not in any vendored
upstream, not on disk anywhere. Worst offenders:

| Boards | Broken reference |
| --- | --- |
| **27** | `SparkFun-DiscreteSemi:AP63205` — **the buck regulator, on >half the fleet** |
| 9 | `SparkFun-Connector:I2C_01x04` |
| 7 | `kml-custom:AP63205WU-7` — *the same buck*, under a second dead nickname |
| 5 | `LOGO` |
| 4 | `kml-custom:TPS7A4901DGNR`, `kml-custom:031-5431-1010` |
| 3 | `BREAD_Slice-rescue:GND-power` |

**This is [F-002] at fleet scale.** The BREAD slice-bus connector was not an isolated
mis-filing — it is the *pattern*. First-party parts are scattered across dead nicknames
(`SparkFun-*` libraries that do not contain them, `kml-custom`, `KML-Custom`, and KiCad
`*-rescue` libraries never cleaned up after a symbol rescue).

**The buck regulator is the headline:** more than half the fleet depends on a footprint that
exists in no library, under two different dead nicknames on different boards.

**Why nobody noticed:** KiCad embeds footprint geometry in the `.kicad_pcb`. Boards open,
render, and fabricate perfectly. The rot is invisible until you update-from-library — or
until a generator tries to resolve a nickname. The DRC warnings that *would* have said so
were drowned in ~102 lines of noise ([F-007]) that nobody could act on, in a job that never
failed ([F-005]).

**Recoverable.** Exactly as with the BREAD connector, the geometry is embedded and can be
extracted back into the library. It is a large but mechanical, scriptable job.

**Also note:** `kml-custom` and `KML-Custom` are case-variant nicknames for the same dead
library — any migration must handle both.

**KiCad 10 ≠ remediated.** `Slice_AOEM` is on KiCad 10 (`20260206`) and still carries **5
broken refs** and a swapped Makefile. Someone opened it in KiCad 10 and saved. The file
version is not a proxy for health — resolve the references, don't trust the version stamp.

**10 boards are `status: released`** (all 4 `PRTO_*`, all 6 `TEMP_*`) and every one is on
KiCad 9 with broken refs and a fake gate. The `TEMP_*` repos are the **templates new Slices
are cloned from** — so every future Slice inherits the rot at birth. Fix these first.

---

## F-010 — Self-inflicted: the `Thermal_Pad` rename broke 15 boards

Renaming `KMLib_Mounting:Thermal Pad` → `Thermal_Pad` (for scriptability) **broke 15 boards
that previously resolved correctly.** They were surveyed and approved against a 3-board
sample; the fleet was 43.

**Root cause of my error:** I reasoned about a 43-board fleet from a 3-board sample. Twice —
the same mistake produced the submodule-deletion misjudgement earlier.

**Lesson (adopted):** before any change to KiCad-Master-Lib, run the resolver across
**`~/repos_feast`**, not against the spike's three boards. The library serves the fleet.

**Fix:** fold `KMLib_Mounting:Thermal Pad` → `Thermal_Pad` into the fleet migration map
(below). It is one more entry in a rename pass that has to happen anyway — but it should
not have been introduced blind.

---

## F-009 — D1 is DNP on the PCB but not in the schematic

`Slice_DCMT` D1 carries `(attr dnp)` in the `.kicad_pcb`, but the schematic symbol is not
marked DNP. KiCad reports this as a separate schematic-parity warning
(*"'Do not populate' settings differ"*) — invisible for the same reason as [F-005].

**Blast radius:** Slice_DCMT. Unknown elsewhere until the fleet survey lands.
**Why it matters:** DNP drives BOM and pick-and-place. If the two disagree, the fab
artifacts are wrong, and *which* one wins depends on which tool generated them.

---

## F-008 — CI container is `kicad9_auto`, projects are KiCad 10

`bread-infra`'s `kibot-ci.yml` runs `ghcr.io/inti-cmnb/kicad9_auto:latest`. All boards are
now KiCad 10 (`version 20260206`). KiCad 9 opening a v10 file is not a supported direction.

**Blast radius:** every repo using `bread-infra` CI.
**Fix:** bump to a KiCad 10 image and **pin it by digest**, not `:latest` — an unpinned CI
image is the same class of silent drift this project exists to eliminate. Folds into P4.

---

## F-007 — KiCad-Master-Lib absent from CI → ~102 spurious warnings

CI never checks out KiCad-Master-Lib, so `KMLib_*` libraries don't resolve in the container.
Most of DCMT's ~102 DRC warnings are `lib_footprint_issues` from this, not real defects.

**Consequence:** the warning stream is pure noise, which is *why nobody noticed the real
mismatch buried in it* ([F-005]). It also means `warnings_as_errors` cannot be turned on
until this is fixed — CI would go permanently red.

**Now fixable.** The lib tables are committed and the sparse-checkout recipe (269MB → 68MB,
no 3D models) is proven. See `kidl-spike/.github/workflows/check.yml` for a working example.

---

## F-006 — `Makefile` ERC and DRC targets are swapped

`Slice_DCMT/hardware/Makefile`: KiBot's `-s`/`--skip-pre` **skips** the named preflight. So:

```make
drc:
	$(KIBOT) ... -s drc -i     # skips DRC — this target actually runs ERC
erc:
	$(KIBOT) ... -s erc -i     # skips ERC — this target actually runs DRC
```

Introduced in `422068f` ("fix: use space-separated KiBot stages", 2025-09-06); `0000f8a` had
it right. Confirmed from CI logs: the job named **DRC** prints *"Running the ERC"*.

Both checks still execute (each target skips one and runs the rest), so nothing is missed —
but **violations are reported under the wrong job name**, which is precisely what made
"DRC passed" look trustworthy.

---

## F-005 — DRC schematic-parity gate is fake ⚠️

**The most important finding so far.**

`Slice_DCMT` D1 had a schematic/PCB footprint mismatch that CI never flagged, despite
`config.kibot.yaml` setting `drc: schematic_parity: true`.

**Root cause — two facts that compose into a silent failure:**

1. KiCad's **stock default** severity for `footprint_symbol_mismatch` is `warning`, not
   `error` — `pcbnew/board_design_settings.cpp:189`:
   `m_DRCSeverities[DRCE_SCHEMATIC_PARITY] = RPT_SEVERITY_WARNING`
2. KiBot's DRC preflight **fails only on errors**; `warnings_as_errors` defaults to `false`.

So the violation was printed on every CI run for months, as one of ~102 warnings, and every
run went green.

**Evidence** (pre-fix board, `b32e3b2~1`):

```
kicad-cli pcb drc --schematic-parity --severity-error  → "Found 0 violations"          exit 0
kicad-cli pcb drc --schematic-parity --severity-all    → footprint_symbol_mismatch D1   exit 5
```

And from an actual **green** CI run (29178987903):

```
WARNING:(W145) (footprint_symbol_mismatch) SparkFun-LED:WS2812-5050-4PIN doesn't match
    footprint given by symbol (KMLib_IC_SMD:WS2812-5050-4PIN). ... Footprint D1
```

**This is not a misconfiguration — it is KiCad's default.** Verified: all three boards carry
`footprint_symbol_mismatch: warning`. **Every `Slice_*` repo has the same hole.** This class
of defect has never been gated anywhere in BREAD.

> Two agents diagnosed this independently and **disagreed on provenance**: one claimed the
> `warning` was a local downgrade from a KiCad default of `error`, misreading the report's
> *"Local override"* label (which names the violation's *rule source*, `drc_item.cpp:524`,
> not the severity's origin). The KiCad source settles it: `warning` is the default. The
> distinction matters — otherwise you go hunting for who "broke" DCMT.

**Fix:** set `rule_severities.footprint_symbol_mismatch: "error"` in each `.kicad_pro`.
Verified safe: red on the broken board, green at current HEAD. Also review the neighbouring
demoted rules — `missing_footprint`, `extra_footprint`, `lib_footprint_mismatch` are also
`warning`.

**Design input for pkidl:** generated `.kicad_pro` files **must set DRC severities
explicitly**. A generated board that inherits KiCad's defaults inherits this blind spot —
and the whole verification story rests on `kicad-cli pcb drc` actually being strict.

---

## F-004 — `Slice_RLHT` manifest declares the wrong primary IC

`slice.yaml` says `primary_ic.part_number: MAX6675`. The schematic uses
`Sensor_Temperature:MAX31855KASA`. Different part.

**Why it matters:** `slice.yaml` is CI-validated against a schema, but the schema checks
*shape*, not *truth*. Nothing cross-checks the manifest against the actual design — so the
manifest can drift from the board indefinitely.

**Bigger question:** should manifest↔schematic agreement be a CI check? If `slice.yaml` is
ever to become the compiler's input (kidl-spike Phase 5), it *must* be true.

---

## F-003 — SKiDL: `generate_schematic` never calls an `empty_footprint_handler` passed to it

`skidl/src/skidl/circuit.py:1307`:

```python
if kwargs.get("empty_footprint_handler]")   # ← stray ']'
```

*Corrected 2026-11-07:* the typo is not the whole cause. On 2.3.0, a handler passed to
`generate_schematic(empty_footprint_handler=...)` for a part with no footprint gets no
calls; passing the misspelled key as well, so the handler is installed, still gets none.
Nothing on the schematic path calls `skidl.empty_footprint_handler`: only
`check_for_empty_footprints()` does, and only the netlist generators call it. The same
check is at `circuit.py:1018` in 3.0.0 (read, not run).

**Status:** fixed on SKiDL master in `7e39ff5` (2026-11-07), not yet released: both
`generate_schematic` and `generate_svg` call the handler. The fix brings a regression,
reproduced and reported on skidl#331: the default drawing handler leaves the placeholder
footprint `":"` on the part, so a later `generate_netlist()` neither calls the handler
nor logs the missing footprint, and writes `(footprint ":")`. Same script, a part with
no footprint: on 2.3.0 the netlist handler is called for R1 and the netlist has
`(footprint "")`; on master `efff5d7` it is not called and the netlist has
`(footprint ":")`. For this repo, after a bump past 3.0.0: pass `generate_schematic`
a handler that skips the power flags, as the netlist step already does. Also: SKiDL's README still
claims schematic generation is "V5 only" — stale; it supports 6/7/8/9.

---

## F-002 — First-party parts filed under third-party library nicknames

**FIXED.** Two BREAD parts were stored under `SparkFun-*` nicknames, in libraries SparkFun
does not actually contain:

- `SparkFun-Connector:BREAD 10-Pin Connector` — **the BREADS slice-bus connector**, the
  physical embodiment of the standard. Verified absent from SparkFun upstream at the pinned
  SHA, and absent from disk anywhere. It survived *only* as embedded geometry inside
  `BREAD_Loaf.kicad_pcb`.
- `SparkFun-LED:WS2812-5050-4PIN` — likewise absent from SparkFun's real library.

Recovered into `KMLib_Connectors:BREAD_Slice_Bus_10Pin` and `KMLib_IC_SMD:WS2812-5050-4PIN`.

**Lesson:** a footprint nickname is not evidence of provenance. Because KiCad embeds
footprint geometry in the `.kicad_pcb`, a board keeps rendering perfectly long after its
library reference has rotted — the failure only surfaces on update-from-library, or when a
generator tries to resolve it.

---

## F-001 — Library resolution lived only in a global KiCad config

**FIXED.** `sym-lib-table` / `fp-lib-table` were gitignored in every board repo, and
`KMLib_*` was not vendored. Nickname resolution existed *only* in one developer's global
KiCad configuration — and was already broken.

Nothing was reproducible from a clean checkout. This was the blocker for the entire
"KiCad as a generated artifact" claim.

Fixed by committing `kmlib.{fp,sym,design-block}-lib-table` to KiCad-Master-Lib, resolved
via `${KICAD_MASTER_LIB}`. All 15 non-stock references across the three boards now resolve
from a clean checkout. See `_planning/01-kidl-spike.md` (R1).
