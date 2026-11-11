# Fleet Worklist

Measured with KiCad 10's own ERC and DRC at **error** severity, plus
`validate_board.py` (bread-infra v1.2.0), against each board on its branch.

> DRC counts **all three** categories kicad-cli reports separately — violations,
> unconnected items, and schematic parity issues. An earlier version of this file
> counted only the first, and therefore missed every parity error.

**14 of 42 boards are green.**

| | boards | items |
| --- | --- | --- |
| ✅ Green | **14** | — |
| Library references | 23 | 62 |
| ERC errors | 10 | 39 |
| DRC errors | 10 | 73 |
| Mechanical / config | **0** | **0** |

Mechanical remediation is complete: KiCad 10 format, DRC parity gate, Makefile
targets, `.gitignore`, symbol sub-units and KiBot layer coverage pass on all 42.
Everything left is a board defect.

Green: `Loaf_ESPT`, `Loaf_x004`, `Slice_DCMT`, `Slice_IOAC`, `Slice_PRTO_CONN_S2L`, `Slice_PRTO_THTA_S2L`, `Slice_PRTO_THT_S2L`, `Slice_RLAY`, `Slice_RLHT`, `Slice_RTDM`, `Slice_TEMP_NANO_S2L-r1`, `Slice_TEMP_NANO_S2L-r2`, `Slice_TEMP_NUCL_L4L-r1`, `Slice_TEMP_NUCL_S4L-r1`

---

# Critical path

Ordered by what it costs to get wrong, then by throughput.

## Tier 0 — real copper defects (6 boards)

**These are the only items here that can ruin a fabrication run.** Shorts, mask
bridges bridging pads, clearance violations, drills out of range. They have been
sitting in boards whose CI reported green for months.

| board | copper defects | total DRC |
| --- | --- | --- |
| **`Slice_SOLR`** | 14 | 17 |
| **`Slice_IOCT`** | 12 | 20 |
| **`Slice_FPSG`** | 4 | 4 |
| **`Slice_STPC`** | 3 | 3 |
| **`Slice_LEPD`** | 2 | 2 |
| **`Slice_PRTO_SMT_S2L`** | 1 | 1 |

Types across the fleet: `solder_mask_bridge` ×12, `clearance` ×11, `shorting_items` ×8,
`drill_out_of_range` ×4, `courtyards_overlap` ×1.

**Start with `Slice_SOLR` and `Slice_IOCT`.** They hold 26 of the 73 DRC errors
between them, and most of the copper defects.

## Tier 1 — schematic/PCB disagreements (11 parity errors)

Not fab-fatal, but they mean the BOM, pick-and-place or fab output disagrees with
the design. Each needs a decision about which side is right.

| count | issue | board | decision |
| --- | --- | --- | --- |
| 5 | `'Exclude from BOM' settings differ` | `Slice_STEP` | Should the part be in the BOM? |
| 4 | `KMLib_IC_SMD:RS_20_ADI-L` vs symbol | `Slice_AOEM` | Which footprint is correct? |
| 1 | `Package_TO_SOT_SMD:TSOT-23-6` vs symbol | | |
| 1 | `KMLib_Boards_Modules:Arduino_Nano_Headers` vs symbol | | |

Where the PCB is right, **Tools → Update PCB from Schematic** with *re-link
footprints* enabled resolves it.

## Tier 2 — ERC (39 errors, 10 boards)

| count | type | fix |
| --- | --- | --- |
| 14 | `power_pin_not_driven` | Add `PWR_FLAG` — mechanical |
| 10 | `pin_not_connected` | No-connect flag on intentionally unused pins — mechanical |
| 8 | **`pin_to_pin`** | **Two outputs driving each other — a real electrical conflict** |
| 4 | `pin_not_driven` | |
| 3 | `label_dangling` | |

| board | ERC |
| --- | --- |
| `Slice_STPC` | 12 |
| `Slice_VCDC` | 9 |
| `Slice_STEP` | 7 |
| `Slice_HEAT` | 2 |
| `Slice_IOCT` | 2 |
| `Slice_PHDO` | 2 |
| `Slice_SERV` | 2 |
| `Slice_GDHB` | 1 |
| `Slice_LOAD` | 1 |
| `Slice_THMX` | 1 |

`Slice_STPC` (12) and `Slice_VCDC` (9) are the bulk. **Look at the 8 `pin_to_pin`**
properly — outputs fighting each other is a design error, not a flag you can add.

## Tier 3 — library re-points (62 refs, quick throughput)

**12 boards need nothing but library re-points to go green.** That is the
cheapest way to move the count: 14 → 26.

| board | refs |
| --- | --- |
| `Slice_AQDO` | 1 |
| `Slice_AQEC` | 1 |
| `Slice_AQOR` | 1 |
| `Slice_TEMP_PICO_L4L-r1` | 1 |
| `Slice_TEMP_PICO_S2L-r1` | 1 |
| `Slice_THRM_31856` | 1 |
| `Slice_VCAC` | 1 |
| `Slice_BUCK` | 2 |
| `Slice_THRM_31855` | 2 |
| `Slice_IAQM` | 3 |
| `Slice_USBP` | 4 |
| `Slice_LVAI` | 5 |

Detail in [`LIBRARY-REVIEW.md`](LIBRARY-REVIEW.md). Best done in the KiCad UI, where
you can see the symbol and its value — fingerprint matching cannot distinguish a
2-pin resistor from a 2-pin capacitor.

## Tier 4 — the rest

| board | lib | ERC | DRC |
| --- | --- | --- | --- |
| `Slice_SOLR` | 11 | 0 | 17 |
| `Slice_IOCT` | 0 | 2 | 20 |
| `Slice_STEP` | 3 | 7 | 11 |
| `Slice_STPC` | 3 | 12 | 3 |
| `Slice_VCDC` | 2 | 9 | 0 |
| `Slice_GDHB` | 2 | 1 | 6 |
| `Slice_HEAT` | 7 | 2 | 0 |
| `Slice_SERV` | 6 | 2 | 0 |
| `Slice_AOEM` | 0 | 0 | 5 |
| `Slice_AQPH` | 1 | 0 | 4 |
| `Slice_FPSG` | 0 | 0 | 4 |
| `Slice_LEPD` | 1 | 0 | 2 |
| `Slice_PHDO` | 1 | 2 | 0 |
| `Slice_THMX` | 2 | 1 | 0 |
| `Slice_PRTO_SMT_S2L` | 0 | 0 | 1 |

---

## Suggested sequence

1. **`Slice_SOLR`, `Slice_IOCT`** — the copper defects. Highest cost of being wrong.
2. **The other 4 copper boards** — `FPSG`, `STPC`, `LEPD`, `PRTO_SMT_S2L`.
3. **The 12 library-only boards** — pure re-pointing, takes the green count to 26.
4. **ERC `pin_to_pin` (8)** — real electrical conflicts.
5. **`PWR_FLAG`s and no-connects (24)** — mechanical, fast.
6. **Tier 1 parity decisions** — BOM flags and footprint choices.

Re-check any board:

```sh
KICAD_CLI='flatpak run --command=kicad-cli org.kicad.KiCad' \
KICAD_MASTER_LIB=~/repos_feast/KiCad-Master-Lib \
  python3 ~/repos_feast/bread-infra/scripts/validate_board.py <repo>
```

DRC — note all three lines, not just the first:

```sh
flatpak run --command=kicad-cli org.kicad.KiCad \
  pcb drc --schematic-parity --severity-error -o /dev/null <board>.kicad_pcb
```
