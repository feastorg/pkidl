"""Bench supply: a barrel jack in, an LM317 that limits current by a resistor a rotary
switch picks, an LM317 that sets the voltage by a pot, a volt meter and an ammeter, and
banana posts out. A 7812 and a 7805 run the meters. All through-hole, and the board is
the back of its own front panel: the meters, the knobs, the switches and the posts are
where the panel is drilled for them."""

from pkidl import Board, Edge, inch, mA, mm

board = Board.from_inputs(__file__)  # the circuit, outline, holes and footprints beside it
board.rails("12V", "5V")
board.ground("GND")
board.name_nets({"N-0000017": "JACK", "N-0000018": "RAW", "N-000006": "VOUT", "N-000007": "ADJ"})

# Both LM317s are on the one heatsink the board is drilled for, back to back, a tab to
# each face of its web: the limiter takes the heat when the output is shorted, the
# regulator when it is not, never both, about 10 W at the worst from a 24 V jack. Each
# has its middle lead midway between the heatsink's pins and its row of leads 0.15 inch
# off the web's line, which is this heatsink's seat for a TO-220. The tabs are their
# outputs, two nets: each is fitted with an insulating pad and a shouldered washer.
sink = board.fixed("530002B02500G")
limit, volts = board["U102"], board["U103"]
board.place(limit, on=sink, at=(12.7 * mm, -3.81 * mm), of=limit.pin(2), facing=Edge.RIGHT)
board.place(volts, on=sink, at=(12.7 * mm, 3.81 * mm), of=volts.pin(2), facing=Edge.LEFT)
# No copper runs on the front under the heatsink, whose body sits there. The
# electrolytics stand 5 mm clear of it for its heat, and the regulators' diodes and
# resistor 1 mm, room for an iron beside its fins.
board.keepout(sink, copper=True)
board.apart(board.parts("C101", "C105", "C106", "C107"), sink, 5 * mm)
board.apart(board.parts("D101", "D102", "D104", "D105", "R102", "C103"), sink, 1 * mm)
board.place(board["D101"], near=limit.pin(2), within=30 * mm)
board.place(board["D102"], near=limit.pin(1), within=30 * mm)
board.place(board["C105"], near=limit.pin(1), within=30 * mm, at_least=8 * mm)
board.place(board["R102"], near=volts.pin(2), within=30 * mm)
board.place(board["C106"], near=volts.pin(1), within=30 * mm, at_least=8 * mm)
board.place(board["C107"], near=volts.pin(2), within=30 * mm, at_least=8 * mm)
board.place(board["D104"], near=volts.pin(2), within=30 * mm)
board.place(board["D105"], near=volts.pin(1), within=30 * mm)

# Power comes in at the back corner, top left: either jack at the left edge, the
# switch by them at the top, and the bulk capacitor on the switched supply.
jacks = board.parts("CON101", "CON102")
power = board["SW101"]
for jack in jacks:
    board.annotate(jack, sides={"socket": Edge.LEFT})
board.place(jacks[0], against=Edge.LEFT, outward="socket", along=0.16)
board.place(jacks[1], against=Edge.LEFT, outward="socket", after=jacks[0])
board.place(power, at=(26 * mm, 7 * mm), facing=Edge.LEFT)
bulk = board["C101"]
board.place(bulk, near=power.pin(1), toward=Edge.BOTTOM, within=25 * mm, at_least=8 * mm)
board.place(board["C102"], near=bulk.pin(1), within=12 * mm)
board.place(board["C103"], near=bulk.pin(1), within=14 * mm)

# The supplies for the meters, at the right edge clear of the heatsink.
reg12, reg5 = board["U101"], board["U104"]
board.place(reg12, against=Edge.RIGHT, along=0.14)
board.place(board["C110"], near=reg12.pin(3), toward=Edge.LEFT, within=14 * mm, at_least=5 * mm)
board.place(reg5, against=Edge.RIGHT, along=0.28)
board.place(board["C104"], near=reg5.pin(3), toward=Edge.LEFT, within=14 * mm, at_least=5 * mm)

# The front of the panel, by its drilling: the meters side by side, the current switch
# and the voltage pot under them, the posts at the front edge 0.75 inch apart.
voltmeter, ammeter = board["DS101"], board["DS102"]
for meter in (voltmeter, ammeter):
    board.annotate(meter, oriented=True)
board.place(voltmeter, at=(17.8 * mm, 50 * mm), facing=Edge.TOP)
board.place(ammeter, at=(76 * mm, 46.5 * mm), facing=Edge.TOP)
# Each meter is held by two M3 screws through the board, 13.97 mm and 14.5 mm either
# side of its middle. No copper and no part is under a head or a standoff on either
# face: 6 mm across, which an M3 pan head is inside. At 7 mm, for a washer, the router
# leaves four connections unmade.
for meter, off in ((voltmeter, 13.97 * mm), (ammeter, 14.5 * mm)):
    half = 3 * mm
    screws = board.annotate(
        meter,
        left_screw=((-off - half, -half), (-off + half, half)),
        right_screw=((off - half, -half), (off + half, half)),
    )
    for screw in screws:
        board.keepout(screw, copper=True, both_sides=True)
board.decouple(voltmeter, [board["C108"]], within=18 * mm)
board.decouple(ammeter, [board["C109"]], within=14 * mm)
board.place(board["RV102"], at=(74 * mm, 38 * mm), facing=Edge.TOP)  # the ammeter's trim, above it

current, pot = board["SW201"], board["RV101"]
board.place(current, at=(21 * mm, 72.5 * mm), facing=Edge.TOP)
board.place(pot, at=(88 * mm, 80 * mm), facing=Edge.TOP)
posts = board.parts("P102", "P101")  # minus on the left
board.row(posts, along=Edge.BOTTOM, pitch=0.75 * inch)
board.place(board["SW103"], at=(52 * mm, 55 * mm), facing=Edge.TOP)  # output on and off
board.place(board["SW102"], at=(39.3 * mm, 55 * mm), facing=Edge.TOP)  # the limit's bypass

# The resistors the switch picks among, in two banks of six beside it: twelve in one
# line are 39 mm, more than the panel has there.
board.row(board.parts("R201..R206"), beside=current, toward=Edge.RIGHT, pitch=3.7 * mm)
board.row(board.parts("R207..R212"), beside=current, toward=Edge.RIGHT, pitch=3.7 * mm)

# The power light and its resistor.
led = board["D103"]
board.annotate(led, oriented=True)
board.place(led, at=(78 * mm, 6 * mm), facing=Edge.TOP)  # top right of the panel, on the 5 V rail
board.place(board["R101"], near=led.pin(2), within=12 * mm)

# The way the load's current goes, half an amp of it at the most with the limit in:
# 1.25 V across the four 10 ohm resistors side by side, the least the switch picks. In
# at either jack, through the power switch and the limiter to the current switch; from
# the far side of the resistors through the regulator and the output switch to the plus
# post; and back from the minus post through the ammeter to ground. Between the current
# switch and the resistors there is a net for each of its positions, which is no one
# stretch of copper, so that part of the way is not said.
for jack in jacks:
    board.path(jack, power, current=500 * mA)
board.path(power, limit, current, current=500 * mA)
board.path("/current_limit_r/R_LIM-", volts, board["SW103"], board["P101"], current=500 * mA)
board.path(board["P102"], ammeter, "GND", current=500 * mA)

board.rules(track=0.5 * mm, clearance=0.3 * mm, assembly="hand")
board.pour("GND", layer="B.Cu")
board.route()
