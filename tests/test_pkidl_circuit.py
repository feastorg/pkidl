"""pkidl.circuit: the parts, pins and nets a board file refers to, and what it declares
about them."""

import copy

import pytest

from pkidl import on_net, where
from pkidl.circuit import Circuit, natural


def _part(ref: str, value: str, footprint: str, **pads: str) -> dict:
    return {"ref": ref, "value": value, "footprint": footprint,
            "pads": {number.lstrip("p"): net for number, net in pads.items()}}  # fmt: skip


# A regulator with two ground pins and one pin on no net, a pull-up, a divider across the
# rails, a resistor between two signals, and two capacitors. As circuit.json lists them:
# references sorted as text, R10 before R2.
DATA = {
    "parts": [
        _part("C1", "100nF", "Device:C", p1="VCC", p2="GND"),
        _part("C2", "10uF", "Device:C", p1="Net-(U1-Pad5)", p2="GND"),
        _part("R1", "10k", "Device:R", p1="VCC", p2="EN"),
        _part("R10", "1k", "Device:R", p1="EN", p2="Net-(U1-Pad5)"),
        _part("R2", "10k", "Device:R", p1="VCC", p2="GND"),
        _part("U1", "REG", "Pkg:SOT", p1="VCC", p2="GND", p3="EN", p4="GND", p5="Net-(U1-Pad5)"),
    ],
    "nets": ["EN", "GND", "Net-(U1-Pad5)", "VCC"],
}
PADS = {"Device:C": ["1", "2"], "Device:R": ["1", "2"], "Pkg:SOT": ["1", "2", "3", "4", "5", "6"]}


@pytest.fixture
def c() -> Circuit:
    return Circuit(copy.deepcopy(DATA), PADS)


def _refs(parts) -> list[str]:
    return [p.ref for p in parts]


def test_references_sort_as_people_read_them():
    assert sorted(["R10", "R2", "C1", "R1"], key=natural) == ["C1", "R1", "R2", "R10"]


def test_a_part_is_found_by_its_reference_and_says_what_it_is(c):
    r1 = c.part("R1")
    assert (r1.ref, r1.value, r1.footprint, str(r1)) == ("R1", "10k", "Device:R", "R1")
    with pytest.raises(LookupError, match="no part 'R3'"):
        c.part("R3")


def test_two_handles_for_one_thing_are_equal_whichever_circuit_they_came_from(c):
    other = Circuit(copy.deepcopy(DATA), PADS)
    assert c.part("R1") == other.part("R1") != c.part("R2")
    assert c.net("GND") == other.net("GND") != c.net("VCC")
    assert c.part("U1").pin(3) == other.part("U1").pin("3") != c.part("U1").pin(4)
    assert len({c.part("R1"), other.part("R1"), c.net("GND"), other.net("GND")}) == 2


def test_parts_come_in_the_order_asked_for_each_once(c):
    assert _refs(c.parts("U1", "C2", "R1")) == ["U1", "C2", "R1"]
    assert _refs(c.parts("R2", "R1..R2", c.part("C1"), "R2")) == ["R2", "R1", "C1"]
    u1, c2 = c.parts("U1", "C2")
    assert (u1.ref, c2.ref) == ("U1", "C2")


def test_with_nothing_asked_for_every_part_comes_in_reference_order(c):
    assert _refs(c.parts()) == ["C1", "C2", "R1", "R2", "R10", "U1"]


def test_a_run_is_every_reference_from_its_first_to_its_last(c):
    assert _refs(c.parts("C1..C2")) == ["C1", "C2"]
    assert _refs(c.parts("R1..R1")) == ["R1"]
    with pytest.raises(LookupError, match=r"'R1..R4': no part 'R3'"):
        c.parts("R1..R4")
    padded = Circuit({"parts": [_part(f"C{n:02d}", "1u", "Device:C", p1="A") for n in (8, 9, 10)],
                      "nets": ["A"]})  # fmt: skip
    assert _refs(padded.parts("C08..C10")) == ["C08", "C09", "C10"]


@pytest.mark.parametrize("run", ["R2..R1", "R1..C2", "R1..", "..R2", "R..R2", "R1...R2"])
def test_something_that_is_not_a_run_is_refused(c, run):
    with pytest.raises(ValueError, match="is not a run of references"):
        c.parts(run)


def test_selectors_pick_parts_by_what_they_are_and_what_they_are_on(c):
    assert _refs(c.parts(where(value="10k"))) == ["R1", "R2"]
    assert _refs(c.parts(where(footprint="Device:C"))) == ["C1", "C2"]
    assert _refs(c.parts(where(value="10k", footprint="Device:C"))) == []
    assert _refs(c.parts(on_net("EN"))) == ["R1", "R10", "U1"]
    assert _refs(c.parts(on_net(c.net("EN")), where(value="10k"))) == ["R1", "R10", "U1", "R2"]
    assert _refs(c.parts(lambda p: p.ref.startswith("C"))) == ["C1", "C2"]
    with pytest.raises(LookupError, match="no net 'ENABLE'"):
        c.parts(on_net("ENABLE"))


def test_a_pin_is_found_by_its_number_and_knows_its_net(c):
    u1 = c.part("U1")
    assert u1.pin(3) == u1.pin("3")
    assert (str(u1.pin(3)), u1.pin(3).number, u1.pin(3).part) == ("U1.3", "3", u1)
    assert u1.pin(3).net == c.net("EN")
    assert [p.number for p in u1.pins()] == ["1", "2", "3", "4", "5", "6"]
    assert [p.number for p in u1.pins(5, "2")] == ["5", "2"]
    with pytest.raises(LookupError, match="U1 has no pin 7"):
        u1.pin(7)
    with pytest.raises(LookupError, match="U1 has no pin 9"):
        u1.pins(1, 9)


def test_a_pin_on_no_net_is_still_a_pin(c):
    assert c.part("U1").pin(6).net is None
    # Without the footprints' pads, the pins are the ones the circuit connects.
    assert [p.number for p in Circuit(DATA).part("U1").pins()] == ["1", "2", "3", "4", "5"]


def test_pads_sharing_a_number_are_one_pin_and_unnumbered_pads_are_none():
    data = {"parts": [_part("J1", "USB", "Conn:USB", p1="VBUS", pS="GND")],
            "nets": ["GND", "VBUS"]}  # fmt: skip
    j1 = Circuit(data, {"Conn:USB": ["1", "S", "S", "", "S", ""]}).part("J1")
    assert [p.number for p in j1.pins()] == ["1", "S"]
    assert j1.pin_on("GND") == j1.pin("S")


def test_a_parts_nets_come_once_each_in_pin_order(c):
    assert [n.name for n in c.part("U1").nets()] == ["VCC", "GND", "EN", "Net-(U1-Pad5)"]


def test_a_net_knows_its_pins_and_its_parts(c):
    en = c.net("EN")
    assert [str(p) for p in en.pins()] == ["R1.2", "R10.1", "U1.3"]
    assert _refs(en.parts()) == ["R1", "R10", "U1"]
    assert [str(p) for p in c.net("GND").pins()] == ["C1.2", "C2.2", "R2.2", "U1.2", "U1.4"]
    assert _refs(c.net("GND").parts()) == ["C1", "C2", "R2", "U1"]
    assert [n.name for n in c.nets()] == DATA["nets"]
    with pytest.raises(LookupError, match="no net 'VDD'"):
        c.net("VDD")


def test_the_pin_on_a_net_is_found_when_there_is_one(c):
    u1 = c.part("U1")
    assert u1.pin_on("EN") == u1.pin(3)
    assert u1.pin_on(c.net("VCC")) == u1.pin(1)
    with pytest.raises(LookupError, match="R2 has no pin on EN"):
        c.part("R2").pin_on("EN")
    with pytest.raises(ValueError, match=r"U1 has 2 pins on GND \(2, 4\): say which"):
        u1.pin_on("GND")


def test_rails_are_declared_and_given_back(c):
    vcc, gnd = c.rails("VCC", c.net("GND"))
    assert (vcc, gnd) == (c.net("VCC"), c.net("GND"))
    assert [n.name for n in c.nets() if n.is_rail] == ["GND", "VCC"]
    with pytest.raises(LookupError, match="no net '5V'"):
        c.rails("5V")


def test_the_signal_net_is_the_one_that_is_not_a_rail(c):
    c.rails("VCC", "GND")
    assert c.part("R1").signal_net == c.net("EN")
    assert c.part("C2").signal_net == c.net("Net-(U1-Pad5)")
    assert c.part("U1").pin_on(c.part("R1").signal_net) == c.part("U1").pin(3)


def test_a_part_with_no_one_signal_net_says_which_it_has(c):
    with pytest.raises(ValueError, match="R1 has no one signal net: .* are VCC, EN; no rails"):
        _ = c.part("R1").signal_net
    c.rails("VCC", "GND")  # an answer that was never given does not hold the rails to it
    with pytest.raises(ValueError, match=r"R2 has no one signal net: .* are none$"):
        _ = c.part("R2").signal_net
    with pytest.raises(ValueError, match=r"R10 has no one signal net: .* EN, Net-\(U1-Pad5\)$"):
        _ = c.part("R10").signal_net


def test_rails_are_declared_before_anything_asks_what_a_rail_is(c):
    c.rails("GND")
    assert c.part("C1").signal_net == c.net("VCC")
    with pytest.raises(ValueError, match="rails declared after C1.signal_net was read"):
        c.rails("VCC")
    assert c.rails("GND") == (c.net("GND"),)  # saying it again changes nothing
    assert c.part("C1").signal_net == c.net("VCC")

    asked = Circuit(DATA)
    assert not asked.net("GND").is_rail
    with pytest.raises(ValueError, match="rails declared after GND.is_rail was read"):
        asked.rails("GND")


def test_a_named_net_answers_to_both_names_and_the_circuit_keeps_its_own(c):
    (vout,) = c.name_nets({"Net-(U1-Pad5)": "VOUT"})
    assert vout == c.net("VOUT") == c.net("Net-(U1-Pad5)")
    assert (vout.name, str(vout), str(c.net("GND"))) == ("Net-(U1-Pad5)", "VOUT", "GND")
    assert c.data == DATA
    assert c.rails("VOUT") == (vout,)
    assert c.part("U1").pin_on("VOUT") == c.part("U1").pin(5)
    assert _refs(c.parts(on_net("VOUT"))) == ["C2", "R10", "U1"]
    assert c.part("R10").signal_net == c.net("EN")  # VOUT is a rail under either name


def test_nets_are_given_back_in_the_order_named(c):
    en, vout = c.name_nets({"EN": "ENABLE", "Net-(U1-Pad5)": "VOUT"})
    assert (str(en), str(vout)) == ("ENABLE", "VOUT")
    assert c.name_nets({"EN": "ENABLE"}) == (en,)  # saying it again changes nothing


def test_a_name_that_would_be_two_things_is_refused(c):
    c.name_nets({"Net-(U1-Pad5)": "VOUT"})
    with pytest.raises(ValueError, match=r"Net-\(U1-Pad5\) is named VOUT, and cannot also be"):
        c.name_nets({"Net-(U1-Pad5)": "OUT"})
    with pytest.raises(ValueError, match=r"EN cannot be named VOUT: Net-\(U1-Pad5\) is"):
        c.name_nets({"EN": "VOUT"})
    with pytest.raises(ValueError, match="EN cannot be named GND: the circuit has a net"):
        c.name_nets({"EN": "GND"})
    with pytest.raises(LookupError, match="no net 'ENABLE'"):
        c.name_nets({"ENABLE": "EN2"})
    assert str(c.net("EN")) == "EN"


def test_a_circuit_that_contradicts_itself_is_refused():
    twice = {"parts": [DATA["parts"][0], DATA["parts"][0]], "nets": DATA["nets"]}
    with pytest.raises(ValueError, match="C1 is in the circuit twice"):
        Circuit(twice)
    with pytest.raises(ValueError, match="C1 is on GND, VCC, not a net of the circuit"):
        Circuit({"parts": [DATA["parts"][0]], "nets": ["EN"]})
