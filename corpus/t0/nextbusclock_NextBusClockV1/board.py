"""Next-bus clock: two seven-segment digits, each driven by a shift register, an
ATmega328 that fills them, an ESP-01 that fetches the time, and 5 V and 3.3 V supplies
from a barrel jack. All through-hole."""

from pkidl import Board, Edge, mm, place

board = Board.from_inputs(__file__)  # the circuit, outline and footprints beside it
board.rails("VCC", "/5V_PWR", "/33V_PWR")
board.ground("GND")


def digit(display, register, limit_a, limit_b):
    """A display with the shift register that drives it below it, and the resistor on
    each of its two common pins."""
    return [
        place(register, near=display, toward=Edge.BOTTOM, within=15 * mm),
        place(limit_a, near=display.pin(8), within=12 * mm),
        place(limit_b, near=display.pin(3), within=12 * mm),
    ]


# The two digits are read left to right, along the top edge.
digits = board.parts("DIG1", "DIG2")
board.row(digits, along=Edge.TOP)
for display in digits:
    board.annotate(display, oriented=True)  # a display is read one way up
    board.place(display, facing=Edge.TOP)
board.add(*digit(digits[0], board["SR1"], board["R3"], board["R4"]))
board.add(*digit(digits[1], board["SR2"], board["R5"], board["R6"]))

# The processor along the bottom edge, with its crystal and load capacitors on its
# pins, its decoupling capacitor, and the reset pull-up and button.
ic1, y1 = board["IC1"], board["Y1"]
board.place(ic1, against=Edge.BOTTOM, facing=Edge.RIGHT)
board.decouple(ic1, [board["C3"]], within=6 * mm)
board.place(y1, near=ic1.pin(9), within=8 * mm)
board.place(board["C5"], near=y1.pin(2), within=6 * mm)
board.place(board["C6"], near=y1.pin(1), within=8 * mm)
board.place(board["R2"], near=ic1.pin(1), within=8 * mm)
board.place(board["SW1"], near=board["R2"], within=15 * mm)

# Power comes in at the left edge and the supply keeps to the left third of the board:
# the jack, the 5 V regulator by it, then the 3.3 V regulator. The 7805 runs hot, so
# its two capacitors and the power LED's resistor stand off from it; the LED is on
# the 5 V output, away from the jack.
jack, reg5, reg33 = board["BJ1"], board["5V_REG1"], board["33V_REG1"]
supply = board.area(Edge.LEFT, share=1 / 3)
board.inside(supply, [jack, reg5, reg33, *board.parts("C1", "C2", "C4", "D1", "R1")])
board.annotate(jack, sides={"socket": Edge.LEFT})
board.place(jack, against=Edge.LEFT, outward="socket")  # it opens off the board
board.place(reg5, near=jack, within=15 * mm, at_least=6 * mm)  # clear of all its pads
board.place(board["C1"], near=reg5.pin(1), within=12 * mm, at_least=7 * mm)
board.place(board["C2"], near=reg5.pin(3), within=12 * mm, at_least=7 * mm)
board.place(reg33, near=reg5.pin(3), within=20 * mm, at_least=8 * mm)
board.place(board["C4"], near=reg33.pin(2), within=10 * mm)
board.place(board["R1"], near=reg5.pin(3), toward=Edge.BOTTOM, within=12 * mm, at_least=5 * mm)
board.place(board["D1"], near=board["R1"].pin(1), within=8 * mm)

# The radio module in the bottom right corner, clear of the rest, with its two
# pull-ups.
esp = board["ESP1"]
board.annotate(esp, sides={"antenna": Edge.RIGHT})
board.place(esp, against=Edge.RIGHT, outward="antenna")
board.place(esp, against=Edge.BOTTOM)
board.place(board["R7"], near=esp.pin(6), within=12 * mm)
board.place(board["R8"], near=esp.pin(5), within=12 * mm)

board.rules(track=0.25 * mm, clearance=0.2 * mm)
board.pour("GND", layer="B.Cu")
board.route()
