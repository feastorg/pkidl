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
