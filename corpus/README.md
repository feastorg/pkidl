# Corpus

Public boards pkidl must be able to express, in tiers of difficulty, and the scorecard
every change to pkidl is judged by (`docs/charter.md`, "How success is measured").

| Tier | What it forces pkidl to have |
|---|---|
| `t0`: simple two-layer | the whole path, end to end |
| `t1`: two-layer power boards with pours | intent pours, current sizing, heatsinking |
| `t2`: two-layer MCU boards | blocks, decoupling placement, ground strategy |
| `t3`: USB | differential pairs, impedance, length matching |
| `t4`: four layers | stackup, inner planes, fanout, via types |

The boards come from PCBench, through Freerouting's fixtures at `842ad83`. Only boards
whose source repository carries a permissive licence are here; each keeps its `LICENSE`.
`manifest.json` records each board's tier, licence, source and the sha256 of its files.

## Each board

```
<tier>/<board_id>/
    reference.kicad_pcb   the original, upgraded to KiCad 10: compared against only
    circuit.json          parts, values, footprints and pad -> net: the circuit
    mechanical.json       outline and mounting holes, each hole footprint with its
                          position, rotation and side; fixed connectors are added per
                          board, with a reason, when its board file is written
    footprints/           the library footprint behind each footprint name, laid out as
                          KiCad libraries: <library>.pretty/<footprint>.kicad_mod
    board.py              the pkidl board file (step 4 of the charter)
    LICENSE               the source project's
```

**A board file reads `circuit.json`, `mechanical.json` and `footprints/`, and nothing
else of the reference.** No positions, tracks, vias or pours come from it: the layout is
designed. `python scripts/corpus.py extract` rewrites all three from the references
(`pkidl.importer`), and `tests/test_corpus.py` fails when a committed copy is not what
the importer reads.

These boards name footprints from KiCad 5 libraries and their own projects' libraries,
which KiCad 10 doesn't ship, so each footprint is read back out of the reference, where
every placed part carries a copy. It is the part's package, as a library would hold it:
pads, courtyard and drawings at the origin, unrotated, on the front, with no nets, no
link to a schematic and no label positions (`pkidl.footprint.library_form`). Where a
reference's parts carry different versions of one footprint name, `footprints/` holds
the version most of them carry, and `manifest.json` lists the parts that carry another
(`other_footprint_versions`).

## The scorecard

`just corpus` copies each reference to `build/corpus/`, has KiCad refill and check it,
and prints one row per board; `build/corpus/scorecard.json` holds the full rows. The
Corpus workflow runs it on demand and weekly.

Today it scores the references only: the bar each board file has to reach. Their DRC
counts are under KiCad 10's rules, which most of these older boards don't fully meet;
findings about footprint libraries, which aren't available here, are left out. Built
boards are scored the same way once they have a `board.py`.

KiCad 10's refill of three references (OpenMPPT, bldc-gimbal-1d, a123 BCM) ran past an
hour on 2026-11-11, alone or in parallel. The recipe gives each refill ten minutes;
past that, the board is checked on its pours as saved, and the scorecard marks it.
Why those boards stall is open.
