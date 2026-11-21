# Where each board comes from, and what it is evidence of

Read 2026-11-21 from each source repository through GitHub's API, and from the files
here. A quote is the author's own words, with the file it is in. What is reasoned and
not read is marked *inferred*.

## What a reference is, and is not

A reference is one author's layout of the circuit, compared against and never copied
from. It is a bar for what `README.md` says the scorecard counts: that a board file can
say the board, that every connection is made, and KiCad's findings on the result beside
KiCad's findings on the original.

It is **not** a bar for anything the author did not state and nobody measured: how much
current a path may carry, how warm copper may run, how much a rail may drop, how far
apart anything has to be. None of the fifteen states a copper weight or carries a
stackup, and three state any electrical rating at all. A figure of that kind in a board
file or in `docs/` is pkidl's own unless it is quoted here from the author.

Most of these boards are one person's project of 2014 to 2017 with a handful of stars:
there is nobody to have reported a fault. Four have no sign of ever having been made.

## The chain

1. **The author's repository.** Named below, with the commit its default branch was at
   when read.
2. **PCBench** (`PCBench/PCBench`) took the board file as `raw.kicad_pcb`. Its
   `metadata.json` has the source's address, the author, a licence and
   `retrieved at`, 2023-08-17 for all fifteen. **It records no commit.**
3. **Freerouting** (`freerouting/freerouting` at `842ad83`,
   `scripts/benchmark/fixtures/PCBench/<board>/raw.kicad_pcb`) carries PCBench's file.
   Its `metadata.normalized.json` records no commit either.
4. **`reference.kicad_pcb` here** is that file upgraded to KiCad 10.

Since no step records a commit, each fixture file was compared with the file at the
head of its author's repository, by git blob hash. **Twelve are the same bytes.** Every
one of the fifteen was last changed by its author before PCBench's retrieval, so for
those twelve the head is what was taken. The other three (the bench supply, icehat,
rxadc_14) were saved again by KiCad 5.1.12 before they reached PCBench, by whom is not
recorded; they have the same counts of parts, tracks and zones as their authors' files.

Freerouting's own notes call each `raw.kicad_pcb` a "professionally routed original".
Nothing in PCBench or in the sources supports "professionally".

## The fifteen

How far each was made, by what its author shows or says:

- **Built**: the author shows the board or says it was made and worked.
- **Likely built**: fabrication files or firmware for it, and no word that it was made.
- **No evidence**: neither.

| Tier | Board | Author's repository, head | Board file last changed | Made? | Ratings the author states |
|---|---|---|---|---|---|
| t0 | esp12-breakout | `itmarshall/esp12-breakout` `63384467`, 3 commits | 2017-02-22 | Built | none |
| t0 | nextbusclock | `chrisgillis/nextbusclock` `9c772284`, 8 commits | 2016-08-22 | Likely built | none |
| t0 | qrp_swr_meter | `4x1md/qrp_swr_meter` `b8eaf264`, 26 commits | 2017-12-12 | Built, then edited | 16 W; a 250 µA meter |
| t1 | DualLM317BenchSupply | `cellularmitosis/DualLM317BenchSupply` `83275d42`, 67 commits | 2014-04-21, tag v2.0 | Built | 24 V in; 1.25 to 20 V out; 13 to 500 mA limited; 1.5 A |
| t1 | OpenMPPT | `Ralim/OpenMPPT` `6738da1e`, 5 commits, archived | 2017-07-08 | No evidence | none for the board |
| t1 | free-of-charge BMS | `hosier/free-of-charge` `32134ce9`, 13 commits | 2015-04-08 | Likely built, with faults its owner lists | none |
| t2 | UProgrammer | `MackPI/UProgrammer-Hardware` `002ca03e`, 17 commits | 2016-11-04 | Likely built in earlier spins; this one, no evidence | none for the board |
| t2 | bldc-gimbal-1d | `swedishhat/bldc-gimbal-1d` `78122fec`, 3 commits | 2016-02-23 | Likely built | none |
| t2 | fan_controller | `slightlynybbled/fan_controller` `27579e00`, 45 commits | 2017-06-08 | v1.1 built and tested; this file is v1.2, no evidence | none for the board |
| t3 | NRC2016 usb_sio | `alangarf/NRC2016` `ff2788cc`, 77 commits | 2016-09-17 | No evidence | none |
| t3 | pcb-usb-ft245r-parallel-adapter | `yeokm1/pcb-usb-ft245r-parallel-adapter` `883a52c8`, 11 commits | 2016-07-24 | Likely built | none |
| t3 | usb2serial-CH340G | `okooo5km/usb2serial-CH340G` `e543808b`, 12 commits | 2016-08-21 | An earlier revision built; this one likely | none for the board |
| t4 | a123 BCM | `MITEVT/a123-battery-integration` `384b1126`, 151 commits | 2015-07-21 | Likely built | none |
| t4 | icehat | `emeb/icehat` `8c9ed855`, 10 commits | 2016-10-11 | Built | none |
| t4 | rxadc_14 | `emeb/rxadc_14` `aa23c433`, 2 commits | 2017-03-04 | No evidence | none |

Two of these repositories have moved since `manifest.json` was written:
`pepaslabs/DualLM317BenchSupply` is now `cellularmitosis/DualLM317BenchSupply`, and
`smslit/usb2serial-CH340G` is now `okooo5km/usb2serial-CH340G`. The old addresses still
lead there.

Each `LICENSE` here is the same bytes as its source's licence file.

## Each board

### esp12-breakout (t0)

- `kicad/ESP12Breakout.kicad_pcb`, one commit, `2ec5626d`. Silk: "ESP-12 Breakout v1.0".
- **Built.** Gerbers are in the repository. The post the README links says ten boards
  were made and one tested in a breadboard, and that "it's not perfect": the edge is a
  tight fit and the unused pads on the bottom edge should go. (That post was read
  through a tool that summarises; its words are not checked letter for letter.)
- The author states no rating.

### nextbusclock (t0)

- `pcb/NextBusClockV1/NextBusClockV1.kicad_pcb`, one commit, `769a0f04`. The board's
  title block says rev 1, the schematic's Rev "0".
- **Likely built.** Gerbers and firmware are there; nothing says it was made. Router
  files (`.dsn`, `.ses`, `.rules`) sit beside the board, so the layout was autorouted
  (*inferred*).
- The author states no rating. "The 7805 runs hot" in `board.py` is the board file's own.

### qrp_swr_meter (t0)

- `pcb/swr_meter_rev_a/swr_meter_rev_a.kicad_pcb`, last changed `8662a7b2`, rev A.
- **Built, then edited.** README: "I ordered a small quantity from ITEAD Studio"; "As of
  December 1, 2016, I have 8 boards". The file was changed twice in December 2017
  ("Corrected URLs on the PCB.", "Silkprint corrections and new gerbers."), and its
  text is on copper: the file is not exactly the boards that were made. Whether other
  copper changed is not known.
- README: "it can handle up to 16W of transmitting power"; the meter's "full deflection
  current is 250uA".

### DualLM317BenchSupply (t1)

- `DualLM317BenchSupply/DualLM317BenchSupply.kicad_pcb`, last changed `6302cbcb`, which
  is the tag v2.0. Silk: "(v2)".
- **Built.** README: "Revision 2 of the boards are being beta tested amongst some
  friends"; no result is given. Of v1: "suffered from a manufacturing defect which
  shorted a pad to ground".
- The author's figures: silk and schematic "Vin: 24V DC"; silk "1.25 - 20V DC" (the
  schematic says 20.2 V, and "19V max" beside its divider); "Current is limited in 6
  steps (13mA, 25mA, 63mA, 125mA, 250mA, 500mA)"; "A current-limit bypass switch allows
  for more than 500mA. Be careful not to exceed 1.5A." The 1.5 A is in the README and
  not on the board.
- The author's commits say why some copper is as it is: "using fills instead of traces
  for high current areas", "thinning out traces for solderability".
- In `board.py`, the 24 V, 500 mA and 1.5 A are the author's. "About 10 W at the worst",
  the heatsink's seat, the clearances from it, the screws' keepouts and
  `rules(track=0.5 mm, clearance=0.3 mm)` are the board file's own.

### OpenMPPT (t1)

- `PCB/OpenMPPT.kicad_pcb`, three commits ending `4e59da49` "Finish Routing". The
  repository is five commits over 2017-05-27 and 2017-07-08, then archived.
- **No evidence it was made.** No gerbers, no photograph, no BOM, no firmware, no issue.
- **The author states no current for the board.** The README is one line. The schematic
  has one note that bears on it: "Inductor must be rated >9A". Its two sense resistors
  are 10 mΩ side by side, 5 mΩ, and the BQ24650 regulates 40 mV across them
  (`I_CHARGE = 40 mV / R_SR`, TI SLUSA75B): **8.0 A** of charge current.
- "About 10 A" in `docs/design/board-files.md` was pkidl's, from the ratings of its
  diode and connectors, and was then held to as the board's. It is not.
- Every track is 0.25 mm and the power is in pours. The connectors' value is "XT60" and
  their footprint an XT30's.

### free-of-charge BMS (t1)

- `Hardware/BMS.kicad_pcb`, last changed `eb71ef70` "version 1 board completed",
  2015-04-08.
- **Likely built, with faults.** Gerbers are there. The owner's own issues, all later
  than the board file: USB D+ and D- "are swapped. Next board revision will be correct",
  then "schematic updated, pcb layout not updated"; "Jumper pads are too small"; "Holes
  are too small for JST battery connector". The reference has those faults.
- `design specifications.txt`: "Voltage range: ?", "Current range: ?".

### UProgrammer (t2)

- `Programmer.kicad_pcb`, last changed `8c366922`, 2016-11-04: the layout the README
  calls version J.
- The two commits after it ("Hardware V00K", "Multiple Level shifters instead of one")
  rewrote the schematic and left the board: **the reference is not a layout of the
  author's latest circuit.**
- **Likely built in earlier spins** (*inferred* from "another spin of the PCB"); nothing
  shows this one was. A schematic note: "25 Volts Maximum".

### bldc-gimbal-1d (t2)

- `kicad/gimbal-board.kicad_pcb`, last changed `78122fec` "Remade Rev 01 layout and sent
  to fab". Silk: "Rev. 01".
- **Likely built.** Gerbers are there; nothing says it came back or worked.
- The layout it replaced, `kicad/r1_gimbal-board.kicad_pcb`, is in the repository with
  wider tracks (221 of 0.5 mm and 24 of 1 mm, where this has 329 of 0.25 mm).

### fan_controller (t2)

- `kicad/fan_controller.kicad_pcb`, last changed `27579e00`, 2017-06-08. Silk "v1.2";
  the board's title block still says v1.1.
- README: "Firmware for v1.1 is complete! Testing has been completely successful!" and
  "Firmware for v1.2 (optional thermistor control) is under development." **v1.1 was
  built and tested; this file is v1.2**, with LEDs and a thermistor added on the
  repository's last day, and nothing shows it was made.
- The author states no current for a fan.

### NRC2016 usb_sio (t3)

- `kicad/usb_sio/usb_sio.kicad_pcb`, last changed `ff2788cc`. The repository has two
  other boards, not revisions of this one.
- **No evidence it was made.** No README, gerbers or photograph. The one word on its
  state is a commit, "Update to the SIO board, layout complete!", and the commit after
  it changed about 1,100 lines of this file.

### pcb-usb-ft245r-parallel-adapter (t3)

- `pcb-usb-ft245r-parallel-adapter.kicad_pcb`, last changed `82b4b86b`. Rev 1.
- **Likely built**, on a gerber archive alone; it was committed twelve minutes before
  the board's last change and not made again. README: "Images Not available yet",
  "Parts required Not available yet".

### usb2serial-CH340G (t3)

- `USB2TTL-CH340G.kicad_pcb`, last changed `e543808b`. The title block says v0.2 of
  2016-06-03 and was not kept up: the board was laid out again on 2016-07-31 and its
  regulator changed on 2016-08-21.
- **An earlier revision was built**: the README's caution about the 3.3 V being off
  "after the circuit is soldered" is of a zener regulator this revision no longer has.
  This one is **likely built**; its gerbers are of a panel.
- A commit says the regulator that replaced it gives 500 mA at the most.

### a123 BCM (t4)

- `schematic/BCM.kicad_pcb`, last changed `94606bf2` "Final change before fab",
  2015-07-21. Four copper layers.
- **Likely built.** Firmware for it went on to 2017. No gerbers, and no word that the
  board came back.

### icehat (t4)

- `kicad/icehat.kicad_pcb`, one commit, `ca31a002`. Silk "icehat v0.1". Four copper
  layers.
- **Built**: the author's commit "Updated for icehat hardware testing".
- A later commit, "Fix some component values", changed the schematic and not the board.
- Its third layer has one zone, +3V3. The sketch of it in `docs/design/board-files.md`
  splits that plane with +1V2, which the reference does not.

### rxadc_14 (t4)

- `rxadc_14.kicad_pcb`, one commit, `aa23c433`. Silk "v0.2". Four copper layers are
  declared; the tracks are on the outer two and the inner two carry zones alone.
- **No evidence it was made.** Two commits, a one-line README and a BOM.

## Not known

- Which commit of each source PCBench took; and who saved three of the files again.
- The copper weight and stackup of every board.
- For the SWR meter, whether copper other than its text changed after the boards made.
- No photograph was looked at: a file named as one is taken as one.

## The vendor boards

`vendors/olimex.json`, `vendors/sparkfun.json` and `vendors/adafruit.json` pin the board
files in the three vendors' GitHub organisations (`OLIMEX`, `sparkfun`, `adafruit`).
There is no chain here: each file is the vendor's own, at a commit of the vendor's own
repository. None of them is kept in this repository.

### How they were read

On 2026-11-21, through GitHub's API: the tree of each repository's default branch, and
the commit at its head. A row's `blob` and `size` are what that tree lists, and its
repository's `commit` is that head. No board was downloaded to make the manifests.

- **Olimex**: all 158 repositories.
- **SparkFun and Adafruit**: every repository that is not a fork and whose name does not
  look like a software library's, and every repository a code search for board files
  returned: 1,097 and 1,002. Left unread: 336 and 900 with software-like names, 63 and
  151 forks. A board in one of those is not in the manifest unless the search found it,
  and the search is not complete.

Every `.kicad_pcb` and `.brd` found is a row, whatever it is: `README.md` lists the
kinds.

### What is the vendor's, and what is not

- **The vendor's**: the file, its path, its commit, and the README sentences in
  `ratings`.
- **Read from the path by rule**: `product`, `revision`, `current` and `kind`. No vendor
  states them in a form that was read. A product's current revision is the highest
  revision named in its paths, among the files not in a folder of older or previous
  revisions, and within a folder named the latest where there is one. Olimex name
  revisions in nearly every path; SparkFun and Adafruit mostly keep one file per board
  and name none.
- **`ratings`** are sentences of the repository's root README that have a number with a
  V, A or W: copied, not checked and not interpreted, and of the repository, not of one
  board in it. `readme_read` says whether the README was read at all: it was for 113 of
  Olimex's 114 repositories with boards, and for 130 of SparkFun's 859 and 72 of
  Adafruit's 682, so an empty `ratings` there mostly means nobody looked. As for the
  fifteen, a figure the vendor does not state is not the board's.
- **`licence_file`** is the name of the licence file at the repository's root, and
  `licence_spdx` what GitHub takes it to be; `NOASSERTION` is a file GitHub could not
  name. No licence text was read. 25 of Olimex's repositories, 296 of SparkFun's and 18
  of Adafruit's have no licence file at their root. A board is not left out for any of
  this: a question of licence is the owner's.

These are boards their vendors sell, which the fifteen mostly are not. That says the
product was made; it does not say that the file at this commit is the layout that
shipped, and nothing read here settles it.

### Not known

- Which revision a vendor now sells. `current` is the highest the paths name.
- Whether a `.brd` marked `brd` is EAGLE XML, EAGLE binary or an old KiCad board: 66 of
  Olimex's and all of SparkFun's and Adafruit's.
- Anything on a branch other than the default, or in a tag or a release.
- Ratings in a README below the root, which Olimex keep per product.
- For SparkFun's `Production` folders, which files are panels of many boards and which
  are single boards saved for production: all are `panel`.
