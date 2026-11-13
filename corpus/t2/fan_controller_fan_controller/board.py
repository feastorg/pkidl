"""Fan controller: four PWM fan channels, the fan input from the host that they follow,
a processor, a 5 V regulator, a rotary encoder and a programming header."""

from pkidl import Board, Edge, mm, place

board = Board.from_inputs(__file__)  # the circuit, outline, holes and footprints beside it
board.rails("+12V", "+5V")
board.ground("GND")
for q in board.parts("Q1..Q5"):  # a SOT-23 does not say which pin is which
    board.annotate(q, pins={"B": 1, "E": 2, "C": 3})


def fan_channel(fan, driver, base_r, tach_r, led, led_r, cap):
    """A fan header with its driver, tach pull-up, supply capacitor and status LED."""
    return [
        place(driver, near=fan.pin(4), within=6 * mm),
        place(base_r, near=driver.pin("B"), within=4 * mm),
        place(tach_r, near=fan.pin(3), within=6 * mm),
        place(cap, near=fan.pin(2), within=5 * mm),
        place(led, near=fan, toward=Edge.TOP, within=7 * mm),
        place(led_r, near=led, within=3 * mm),
    ]


# The fans plug in along one edge, each with its channel behind it.
fans = board.parts("P3..P6")
board.row(fans, along=Edge.BOTTOM)
for parts in zip(fans, board.parts("Q2..Q5"), board.parts("R15..R18"), board.parts("R10..R13"),
                 board.parts("D1..D4"), board.parts("R7", "R8", "R9", "R19"),
                 board.parts("C3..C6"), strict=True):  # fmt: skip
    board.add(*fan_channel(*parts))

# The processor in the middle, with the capacitors that are its own and the parts on
# its pins.
u1, u2 = board.parts("U1", "U2")
board.place(u1, centre=True)
board.decouple(u1, board.parts("C2", "C8", "C12"), within=3 * mm)
board.place(board["R1"], near=u1.pin(1), within=3 * mm)
board.place(board["R5"], near=u1.pin(10), within=4 * mm)
board.place(board["R6"], near=board["R5"], within=3 * mm)
board.place(board["C11"], near=u1.pin(3), within=3 * mm)

# The regulator by the edge, its capacitors on its pins and the bulk capacitor by its
# input.
board.place(u2, against=Edge.LEFT)
board.decouple(u2, board.parts("C1", "C9"), within=3 * mm)
board.place(board["C7"], near=u2.pin(1), within=6 * mm)

# The fan input from the host and the programming header along the other long edge,
# and what conditions the input's two signals.
p1 = board["P1"]
board.row([p1, board["P2"]], along=Edge.TOP)
board.place(board["Q1"], near=p1.pin(3), within=4 * mm)
board.place(board["R14"], near=board["Q1"].pin("B"), within=2 * mm)
board.place(board["R2"], near=p1.pin(4), within=3 * mm)
board.place(board["R3"], near=board["R2"], within=3 * mm)
board.place(board["C10"], near=board["R3"], within=3 * mm)
board.place(board["R4"], near=board["C10"], within=3 * mm)

# The encoder where a hand reaches it.
board.place(board["SW1"], against=Edge.RIGHT)

board.rules(track=0.25 * mm, clearance=0.2 * mm)
board.pour("GND", layer="B.Cu")
board.route()
