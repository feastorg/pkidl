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

The boards come from PCBench, through Freerouting's fixtures at `842ad83`; each keeps
its `LICENSE`. `manifest.json` records each board's tier, licence, source and the sha256
of its files.

**`PROVENANCE.md` says where each board comes from and what it is evidence of**: its
author's repository and commit, whether it was ever made, and the ratings its author
states, which for most is none. A reference is a bar for what the scorecard counts and
for nothing its author did not state: read it before holding a board file to one.

Which boards are here is the owner's to say, and none is left out for its licence.
Boards that Olimex, SparkFun and Adafruit make and sell are being added beside these:
so far they are pinned and can be fetched, and none has a tier or inputs yet
([Vendor boards](#vendor-boards)).

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
    board.py              the pkidl board file, where the board has one
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
reference's parts carry versions of one footprint name that differ in their pads, the
version most of them carry keeps the name and each other is written under the name with
`_2`, `_3` and on, its parts pointing at it; where versions differ in no more than their
drawings, `footprints/` holds the version most of them carry, and `manifest.json` lists
the parts that carry another (`other_footprint_versions`). Parts that share a reference
are told apart the same way, by where they are. `extract` prints each name it gives,
each part whose footprint draws the board's outline, and each footprint name of drilled
pads on no net that is not taken for holes.

## The scorecard

`just corpus` copies each reference to `build/corpus/`, has KiCad refill and check it,
builds each `board.py` beside it (`python scripts/corpus.py build`), has KiCad refill
and check what was built, and prints one row per board with a second row under it for
the board built from its `board.py`; `build/corpus/scorecard.json` holds the full rows.
The Corpus workflow runs it on demand and weekly.

A reference's row is the bar its board file has to reach. Its DRC counts are under
KiCad 10's rules, which most of these older boards don't fully meet; findings about
footprint libraries, which aren't available here, are left out. A built board is
scored the same way, and its row also says how many parts its board file placed and
whether its netlist is `circuit.json`'s. A board file that does not build is said in
its row, and `just corpus` fails once the scorecard is printed.

KiCad 10's refill of three references (OpenMPPT, bldc-gimbal-1d, a123 BCM) ran past an
hour on 2026-11-11, alone or in parallel. The recipe gives each refill ten minutes;
past that, the board is checked on its pours as saved, and the scorecard marks it.
Why those boards stall is open.

## Vendor boards

Olimex, SparkFun and Adafruit publish the boards they sell in their GitHub
organisations: a few thousand board files, some of them megabytes each. They are not
kept here. `vendors/<vendor>.json` pins every board file found, and
`python scripts/corpus.py fetch` downloads the ones asked for into
`build/vendors/<owner>/<repository>/<path>`, which is not tracked.

```sh
python scripts/corpus.py fetch --vendor olimex --current --kicad   # current KiCad boards
python scripts/corpus.py fetch --product ESP32-PoE                 # every revision of one
python scripts/corpus.py fetch --vendor sparkfun --list            # say what, fetch nothing
```

A board is downloaded from `raw.githubusercontent.com` at its repository's pinned commit,
kept only if its bytes have the git blob hash the manifest pins, and not downloaded again
while the copy in `build/vendors/` still has it. One that fails is said, and the rest are
still fetched.

A manifest has two parts. `repositories` says, for each repository, the `commit` its
files are pinned at, the licence file it carries and what GitHub takes that licence to
be, and the sentences of its README that state a rating. `boards` has one row per board
file:

| Field | What it is |
|---|---|
| `repository`, `path`, `blob`, `size` | what to fetch and what its bytes must be |
| `product`, `revision` | read from the path by rule, not stated by the vendor |
| `current` | whether it is the product's current revision, by the same rules |
| `format` | `kicad_pcb`; `eagle_brd_xml` or `eagle_brd_binary` where the file's first bytes were read; `brd` where they were not |
| `kind` | what the file is; only a `board` is fetched unless `--all` is given |
| `product_page` | the vendor's page for it, where the README or the repository gives one |

Every board file is in the manifest, with the ones that are not product boards marked
by their `kind`:

| `kind` | What it is |
|---|---|
| `board` | a product board, of any revision |
| `panel` | a production copy: a file under a `Production` or `Panel` folder, or named a panel |
| `backup` | an autosave, a file in a backup folder, or one named old |
| `duplicate` | the same bytes as the board `same_as` names |
| `stub` | a file under 2 kB, too small to be a board |
| `drawing` | a dimension drawing |
| `template` | a template for boards that fit a product |
| `example` | an example, or a test of a footprint |
| `jig` | a jig for testing or soldering a product |
| `mechanical` | a plate, spacer, bracket or enclosure panel made as a PCB |
| `vendored` | a board of somebody else's tool, kept among the software |
| `copy` | a copy of a product's board kept in a repository of 3D models |
| `guide` | a board of a project in a repository of guides, not a product |

`PROVENANCE.md` says how the manifests were made and what is not known of them.
`tests/test_corpus_vendors.py` checks the manifests and the fetching, from a directory
and not the network.

A fetched board is not yet a corpus board. To be read as one it is upgraded to KiCad 10
(`kicad-cli pcb upgrade`) and then read by `pkidl.importer`, as the fifteen were. The
EAGLE boards are a further step: of three tried on 2026-11-21, KiCad 10's import read
the one that is XML and refused the two in EAGLE's older binary format.
