# Library Audit — raw findings

Scratch record of the library dependency audit performed 2026-07-11.
Factual output only; the plan derived from this lives in
`_working/03-library-analysis.md`.

Audited against the boards **as committed on 2026-07-11**, i.e. *before* the
KiCad 10 migration and the Loaf footprint fix. Re-run after those land.

---

## Method

```bash
# symbols
grep -ho '(lib_id "[^"]*")' */hardware/*.kicad_sch | sed 's/.*"\(.*\)".*/\1/'
# footprints
grep -ho '^	(footprint "[^"]*"' */hardware/*.kicad_pcb | sed 's/.*"\(.*\)".*/\1/'
```

---

## Symbol library usage (by nickname)

| Library | Loaf_x004 | Slice_DCMT | Slice_RLHT | Source |
| --- | --- | --- | --- | --- |
| `power` | 14 | 24 | 26 | stock KiCad |
| `Device` | — | 12 | 15 | stock KiCad |
| `Connector` | 5 | 5 | 6 | stock KiCad |
| `Mechanical` | — | 5 | 5 | stock KiCad |
| `Switch` | — | — | 2 | stock KiCad |
| `Driver_Motor` | — | 1 | — | stock KiCad |
| `Motor` | — | 1 | — | stock KiCad |
| `MCU_Module` | — | 1 | 1 | stock KiCad |
| `Sensor_Temperature` | — | — | 1 | stock KiCad |
| `Relay` | — | — | 1 | stock KiCad |
| `Isolator` | — | — | 1 | stock KiCad |
| `Graphic` | — | — | 1 | stock KiCad |
| `KMLib_IC_Power` | — | 1 | 1 | **kmlib-local** |
| `KMLib_Switches` | — | 1 | — | **kmlib-local** |
| `SparkFun-LED` | — | 1 | 1 | **SparkFun submodule** |
| `PPPC101LGBN-RC` | 2 | — | — | **unknown / orphan lib** |

## Footprint library usage (by nickname)

| Library | Loaf | DCMT | RLHT | Source |
| --- | --- | --- | --- | --- |
| `Capacitor_SMD` | — | 12 | 6 | stock |
| `Resistor_SMD` | — | 2 | 10 | stock |
| `TerminalBlock_4Ucon` | — | 4 | — | stock |
| `TerminalBlock_TE-Connectivity` | — | 2 | — | stock |
| `TerminalBlock_Phoenix` | — | — | 4 | stock |
| `MountingHole` | — | 4 | 4 | stock |
| `Package_SO` | — | — | 4 | stock |
| `Package_TO_SOT_THT` | — | 2 | — | stock |
| `Capacitor_THT` | — | 2 | — | stock |
| `Relay_THT` | — | — | 2 | stock |
| `Diode_THT` | — | — | 2 | stock |
| `Fuse` | — | — | 2 | stock |
| `Inductor_SMD` | — | 1 | 1 | stock |
| `NetTie` | — | 1 | — | stock |
| `Connector_PinSocket_2.54mm` | 1 | 1 | 1 | stock |
| `Connector_BarrelJack` | 1 | — | — | stock |
| `Symbol` | 1 | 1 | 1 | stock |
| `Module` | — | — | 1 | stock |
| `kml-custom` | — | 4 | — | **DEAD nickname** |
| `KMLib_Boards_Modules` | — | 1 | — | kmlib-local |
| `KMLib_IC_SMD` | — | 1 | 2 | kmlib-local |
| `KMLib_Mounting` | — | — | 1 | kmlib-local |
| `SparkFun-LED` | — | 1 | — | **SparkFun submodule** |
| `SparkFun-Connector` | 5 | — | — | **SparkFun submodule** |

---

## Exact non-stock items (the complete surface — 14 refs, 12 distinct)

### Symbols
```
2  KMLib_IC_Power:AP63205WU-7_Buck_Regulator
1  KMLib_Switches:1101M2S3CQE2
2  SparkFun-LED:WS2812B_5050
2  PPPC101LGBN-RC:PPPC101LGBN-RC          (Loaf)
```

### Footprints
```
1  kml-custom:SOIC_05WU-7_DIO
2  kml-custom:SW_Slide-CK-1101M2S3CQE2
1  kml-custom:Thermal Pad
1  KMLib_Boards_Modules:Arduino_Nano_Headers
1  KMLib_IC_SMD:SOIC_05WU-7_DIO
1  KMLib_IC_SMD:WS2812-5050-4PIN
1  KMLib_Mounting:Thermal Pad
1  SparkFun-LED:WS2812-5050-4PIN
4  SparkFun-Connector:BREAD 10-Pin Connector          (Loaf)
1  SparkFun-Connector:1x10 RA Male Header 2.54mm Pitch (Loaf)
```

Note the duplication across nicknames (`SOIC_05WU-7_DIO`, `Thermal Pad`,
`WS2812-5050-4PIN` each appear under two nicknames) — evidence of a half-finished
library reorganisation. DCMT still points at the origin (`kml-custom`), RLHT at the
destination (`KMLib_*`).

---

## Zero-usage confirmation

```bash
grep -rhoiE '(digikey|OPL_|arduino-kicad)[A-Za-z_-]*:' */hardware/*.kicad_{sch,pcb}
# → no output
```

`digikey-kicad-library`, `OPL_Kicad_Library`, `arduino-kicad-library`: **not one part
used across any of the three boards.**

(`MCU_Module:Arduino_Nano_v3.x` is stock KiCad, not `arduino-kicad-library`.)

---

## KiCad-Master-Lib state

Submodules — all pinned to **pristine upstream**, no forks:

```
d3392376  OPL_Kicad_Library            github.com/Seeed-Studio/OPL_Kicad_Library
42e5152f  SparkFun-KiCad-Libraries     github.com/sparkfun/SparkFun-KiCad-Libraries
1075811e  arduino-kicad-library        github.com/Alarm-Siren/arduino-kicad-library
d4bd68f4  digikey-kicad-library        github.com/Digi-Key/digikey-kicad-library
```

Working checkout `/home/cam/eda/kicad/KiCad-Master-Lib`: **clean, no uncommitted work,
no dirty submodules.**

`kmlib-local/` contains 13 footprint libs and 13 symbol libs, already organised into a
taxonomy (Aesthetic, Boards_Modules, Connectors, IC_SMD, IC_THT, Mounting, Passives_SMD,
Passives_THT, Proto, Proto_Decorators, Relays, Switches, TestPoints).

---

## Key finding: `BREAD 10-Pin Connector` is missing

- Referenced **4×** by `Loaf_x004` as `SparkFun-Connector:BREAD 10-Pin Connector`.
- **Does not exist upstream** in SparkFun-KiCad-Libraries at the pinned SHA
  (`find SparkFun-KiCad-Libraries -iname "*BREAD*"` → nothing).
- **Does not exist anywhere** under `/home/cam` as a `.kicad_mod`.
- It is a **first-party part that was squatting in a third-party library namespace**, and
  it has been lost.

**It is recoverable.** KiCad embeds full footprint definitions in the board file. Verified:

```
'SparkFun-Connector:BREAD 10-Pin Connector': 11939 chars, 12 pads
  — embedded in Loaf_x004/hardware/BREAD_Loaf.kicad_pcb
```

Same applies to `1x10 RA Male Header 2.54mm Pitch` (footprint) and
`PPPC101LGBN-RC` (symbol — embedded in the schematic's `lib_symbols` block).

---

## Current lib-table state (the R1 blocker, concretely)

`~/.var/app/org.kicad.KiCad/config/kicad/10.0/fp-lib-table` registers **only** `KMLib_*`
libraries, all via `${KICAD_MASTER_LIB}/kmlib-local/footprints/…`.

There is **no** entry for `SparkFun-Connector`, `SparkFun-LED`, `kml-custom`, or
`PPPC101LGBN-RC`. So on the current KiCad 10 config, every one of the 12 non-stock refs
above that isn't `KMLib_*` is **unresolvable**.

The old host config at `~/.config/kicad/9.0/` has **no lib tables at all** and no env vars.

Consequence: nickname resolution exists only in a hand-edited global config, and is
already broken for the Loaf. Nothing about the current boards is reproducible from a
clean checkout.

### Why this is invisible today

The boards still open and render correctly, because the geometry is embedded in the
`.kicad_pcb`. Dead nicknames only bite on *update-footprints-from-library* — or when
**pkidl tries to resolve them during generation**. It looks cosmetic and is a hard
prerequisite for the spike.
