# pkidl

Design the physical layer of a circuit board in Python: where the parts go, what the
copper has to do, and why. A board file says what the designer means; pkidl works out
the geometry and writes KiCad files; KiCad judges the result.

It is the counterpart to [SKiDL](https://github.com/devbisme/skidl), which says what
connects to what. [`docs/charter.md`](docs/charter.md) says what pkidl is for, and
[`docs/roadmap.md`](docs/roadmap.md) where it stands.

**Status:** early, and changing. Nothing is released, the API moves between commits,
and one corpus board builds end to end so far.

## A board file

An ESP-12E breakout, written from its circuit and its outline. There are no coordinates
in it but two insets:

```python
"""ESP-12E breakout: the module, its boot straps, and two headers that sit in a
breadboard."""

from pkidl import Board, Edge, inch, mm

board = Board.from_inputs(__file__)  # the circuit, outline, holes and footprints beside it
board.rails("VCC", "GND")

u1, p1, p2 = board.parts("U1", "P1", "P2")
straps = board.parts("R1..R5")

# The headers plug into a breadboard: one down each long edge, their rows 0.9 inch
# apart on the 1.05 inch board, an exact number of 0.1-inch grid steps.
board.place(p1, against=Edge.LEFT, inset=0.075 * inch)
board.place(p2, against=Edge.RIGHT, inset=0.075 * inch)
board.align(p1, p2, grid=0.1 * inch)

# The module between them, its antenna end on the top edge with no copper under it.
board.place(u1, between=(p1, p2), against=Edge.TOP, facing=Edge.TOP)
board.keepout(u1.area("antenna"), copper=True, both_sides=True)

# Each strap sits by the module pin it biases, on the back: the module and the headers
# fill the front.
for r in straps:
    board.place(r, near=u1.pin_on(r.signal_net), within=3 * mm, side="back")

board.rules(track=0.25 * mm, clearance=0.2 * mm)
board.pour("GND", layer="B.Cu")
board.route()
```

It is [`corpus/t0/esp12-breakout_ESP12Breakout/board.py`](corpus/t0/esp12-breakout_ESP12Breakout/board.py).
Built, it is a routed board with the circuit's netlist and nothing left unconnected.
Statements are values and their order does not matter: they are solved together, and
two that contradict each other are reported with the line each was written on.

## Try it

pkidl needs Python 3.13, [uv](https://docs.astral.sh/uv/) and
[just](https://just.systems/). Routing runs
[Freerouting](https://github.com/freerouting/freerouting), which needs Java: either a
`freerouting` command on the path, or its command line in `$FREEROUTING`.

```sh
just setup                                    # install dependencies
just test                                     # pkidl's tests
uv run python scripts/corpus.py build out     # build the board file above into out/
```

The last writes `out/esp12-breakout_ESP12Breakout/built.kicad_pcb`, which opens in
KiCad 10. `just corpus` goes further and has KiCad refill and check every corpus board
and score what was built against its reference; that needs KiCad 10 as well.

## What is here

```
src/pkidl/    the library
tests/        its tests
corpus/       public boards pkidl has to be able to express, and their scorecard
docs/         the charter, the roadmap, the board files written first, the prior-art survey
spike/        a separate project: boards of ours written with pkidl
```

[`docs/design/board-files.md`](docs/design/board-files.md) is the language as it is
meant to read, with what is built so far. [`corpus/README.md`](corpus/README.md) says
how a change to pkidl is judged. [`CONTRIBUTING.md`](CONTRIBUTING.md) says how to work
on it.

## Licence

- pkidl: [Apache-2.0](LICENSE).
- `spike/`, the BREAD boards written with pkidl: [GPL-3.0-or-later](spike/LICENSE). It
  carries data derived from the GPL-3.0 BREAD board designs.
- Corpus and test boards from other projects keep their own licences, in a `LICENSE`
  beside each one.
