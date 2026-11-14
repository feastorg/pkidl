"""Bench supply: a barrel jack in, an LM317 that limits current by a resistor a rotary
switch picks, an LM317 that sets the voltage by a pot, a volt meter and an ammeter, and
banana posts out. A 7812 and a 7805 run the meters. All through-hole, and the board is
the back of its own front panel: the meters, the knobs, the switches and the posts are
where a hand and an eye want them."""

from pkidl import Board, Edge, inch, mm, place

board = Board.from_inputs(__file__)  # the circuit, outline, holes and footprints beside it
board.rails("12V", "5V")
board.ground("GND")
board.name_nets({"N-0000017": "JACK", "N-0000018": "RAW", "N-000006": "VOUT", "N-000007": "ADJ"})

# Power comes in at the back corner, top left: either jack at the left edge, the
# switch by them at the top, and the bulk capacitor on the switched supply with its two small ones.
jacks = board.parts("CON101", "CON102")
power = board["SW101"]
board.annotate(jacks[0], sides={"socket": Edge.LEFT})
board.annotate(jacks[1], sides={"socket": Edge.LEFT})
board.place(jacks[0], against=Edge.LEFT, outward="socket", along=0.16)
board.place(jacks[1], against=Edge.LEFT, outward="socket", after=jacks[0])
board.place(power, against=Edge.TOP, along=0.3)
bulk = board["C101"]
board.place(bulk, near=power.pin(1), toward=Edge.BOTTOM, within=25 * mm, at_least=8 * mm)
board.place(board["C102"], near=bulk.pin(1), within=12 * mm)
board.place(board["C103"], near=bulk.pin(1), within=14 * mm)

# The two LM317s drop what the output does not take, and are the heat on this board.
# They stand along the back edge, past the heatsink the board is drilled for, where a
# tab can be bolted to the case, with every electrolytic of theirs stood off.
limit, volts = board["U102"], board["U103"]
board.place(limit, against=Edge.TOP, along=0.73)
board.place(volts, against=Edge.TOP, along=0.86)
board.place(board["D101"], near=limit.pin(2), within=12 * mm)
board.place(board["D102"], near=limit.pin(1), within=12 * mm)
board.place(board["C105"], near=limit.pin(1), within=15 * mm, at_least=7 * mm)
board.place(board["R102"], near=volts.pin(2), within=14 * mm)
board.place(board["C106"], near=volts.pin(1), within=15 * mm, at_least=7 * mm)
board.place(board["C107"], near=volts.pin(2), within=25 * mm, at_least=7 * mm)
board.place(board["D104"], near=volts.pin(2), within=14 * mm)
board.place(board["D105"], near=volts.pin(1), within=14 * mm)

# The supplies for the meters: 12 V from the switched supply, 5 V from that.
reg12, reg5 = board["U101"], board["U104"]
board.place(reg12, against=Edge.RIGHT, along=0.16)
board.place(board["C110"], near=reg12.pin(3), toward=Edge.LEFT, within=14 * mm, at_least=5 * mm)
board.place(reg5, against=Edge.RIGHT, along=0.28)
board.place(board["C104"], near=reg5.pin(3), toward=Edge.LEFT, within=14 * mm, at_least=5 * mm)

# The front of the panel, the bottom half. The meters side by side, read from the
# front; under them the current switch and the voltage pot; the posts at the front
# edge, 0.75 inch apart as a double banana plug is.
voltmeter, ammeter = board["DS101"], board["DS102"]
for meter in (voltmeter, ammeter):
    board.annotate(meter, oriented=True)
board.place(voltmeter, against=Edge.LEFT, along=0.46, facing=Edge.TOP)
board.place(ammeter, against=Edge.RIGHT, along=0.46, facing=Edge.TOP)
board.decouple(voltmeter, [board["C108"]], within=14 * mm)
board.decouple(ammeter, [board["C109"]], within=14 * mm)
board.place(board["RV102"], near=ammeter.pin(1), within=12 * mm)  # the ammeter's trim

current, pot = board["SW201"], board["RV101"]
board.place(current, against=Edge.LEFT, along=0.76)
board.place(pot, against=Edge.RIGHT, along=0.76)
posts = board.parts("P102", "P101")  # minus on the left
board.row(posts, along=Edge.BOTTOM, pitch=0.75 * inch)
out_switch, bypass = board["SW103"], board["SW102"]
board.place(out_switch, near=posts[1], within=25 * mm, at_least=12 * mm)
board.place(bypass, near=current, within=30 * mm, at_least=15 * mm)


def sense(resistor):
    """A resistor that sets one current, by the switch position it is picked at, or by
    the resistor it is in series with."""
    for pin in resistor.pins():
        if pin.net in picked:
            return place(resistor, near=picked[pin.net], within=40 * mm)
    raise LookupError(f"{resistor} is on no position of the switch")


picked = {pin.net: pin for pin in current.pins() if pin.net is not None and pin.number != "1"}
picked.pop(board.net("/current_limit_r/R_LIM+"), None)  # the switch's two wipers
picked[board.net("N-0000022")] = board["R208"].pin(2)  # R211 is in series with R208
for resistor in board.parts("R201..R212"):
    board.add(sense(resistor))

# The power light and its resistor, by the volt meter.
led = board["D103"]
board.annotate(led, oriented=True)
board.place(led, near=voltmeter.pin(2), within=20 * mm, facing=Edge.TOP)
board.place(board["R101"], near=led.pin(2), within=12 * mm)

board.rules(track=0.5 * mm, clearance=0.3 * mm)
board.pour("GND", layer="B.Cu")
board.route()
