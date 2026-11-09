"""Board composition from YAML: generated and listed references, and errors that say
where."""

import re

import pytest

from kidl_spike.boards.spec import SpecError, load, parse

BASE = {
    "name": "t",
    "buck": "AP63205",
    "nano": {"pins": {4: "GND"}, "unused": [1]},
}


def _board(*channels):
    return parse(BASE | {"channels": list(channels)}, "t.yaml")


def test_references_are_generated_after_the_root_parts():
    spec = _board({"kind": "thermocouple", "ch": "TC1", "ss": 16, "anchor": [10, 20]},
                  {"kind": "thermocouple", "ch": "TC2", "ss": 14})  # fmt: skip
    tc1, tc2 = spec.channels("thermocouple")
    # U1, C1-C4 and J1 are the bus, buck and its passives: generated ones come after.
    assert (tc1["U"], tc1["C"], tc1["FBP"], tc1["FBN"], tc1["RCLK"], tc1["RSS"], tc1["J"]) == (
        "U2", "C5", "FB1", "FB2", "R1", "R2", "J2")  # fmt: skip
    assert (tc2["U"], tc2["C"], tc2["J"]) == ("U3", "C6", "J3")
    assert spec.anchors == {"TC1": (10.0, 20.0)}


def test_listed_references_are_kept_and_skipped():
    spec = _board({"kind": "relay", "ch": "CH1", "ctrl": 9, "refs": {"U": "U4", "J": "J2"}},
                  {"kind": "relay", "ch": "CH2", "ctrl": 10})  # fmt: skip
    ch1, ch2 = spec.channels("relay")
    assert (ch1["U"], ch1["J"]) == ("U4", "J2")
    assert (ch2["U"], ch2["J"]) == ("U2", "J3")  # J2 is taken by CH1's list


def test_rlht_yaml_keeps_the_originals_references():
    relays = load("rlht").channels("relay")
    assert [(r["ch"], r["K"], r["U"], r["J"]) for r in relays] == [
        ("CH1", "K1", "U4", "J4"), ("CH2", "K2", "U5", "J5")]  # fmt: skip


@pytest.mark.parametrize(
    ("channel", "message"),
    [
        ({"kind": "relais", "ch": "CH1", "ctrl": 9}, "channels[0].kind: unknown block 'relais'"),
        ({"kind": "relay", "ch": "CH1"}, "channels[0].ctrl: missing"),
        (
            {"kind": "relay", "ch": "CH1", "ctrl": 9, "anchor": [1]},
            "channels[0].anchor: expected [x, y]",
        ),
        (
            {"kind": "relay", "ch": "CH1", "ctrl": 9, "refs": {"Q": "Q1"}},
            "channels[0].refs: expected roles",
        ),
        (
            {"kind": "relay", "ch": "CH1", "ctrl": 9, "refs": {"U": "R7"}},
            "channels[0].refs.U: 'R7' is not a U",
        ),
        (
            {"kind": "bridge", "ch": "CH1", "pins": {"DIR": 1}},
            "channels[0].pins: expected a pin number",
        ),
    ],
)
def test_errors_name_the_file_and_key(channel, message):
    with pytest.raises(SpecError, match=r"^t\.yaml: " + re.escape(message)):
        _board(channel)
