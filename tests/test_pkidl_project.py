"""pkidl writes KiCad custom design rules that gate what netclasses only suggest."""

import json
import re

import pytest

from pkidl.project import DruRule, NetClass, exactly, width_rules, write_project, write_rules


def test_width_rules_make_each_class_width_a_minimum():
    classes = [NetClass("Default", 0.2, 0.5), NetClass("HV Relay", 1.25, 3.0)]
    rules = width_rules(classes)
    assert [(r.name, r.constraint, r.min_mm, r.condition) for r in rules] == [
        ("Default width", "track_width", 0.5, ""),
        ("HV Relay width", "track_width", 3.0, "A.NetClass == 'HV Relay'"),
    ]


def test_rules_file_format(tmp_path):
    path = write_rules(tmp_path / "b.kicad_dru", [
        DruRule("Default width", "track_width", 0.5, why="the floor"),
        DruRule("hole", "hole_clearance", 2.0, "A.memberOfFootprint('H?')", severity="error"),
    ])  # fmt: skip
    assert path.read_text() == (
        "(version 1)\n"
        "\n"
        "# the floor\n"
        '(rule "Default width"\n'
        "  (severity warning)\n"
        "  (constraint track_width (min 0.5mm)))\n"
        "\n"
        '(rule "hole"\n'
        "  (severity error)\n"
        "  (condition \"A.memberOfFootprint('H?')\")\n"
        "  (constraint hole_clearance (min 2mm)))\n"
    )


# A net's name, the pattern it is written as, and names the name itself takes when it
# is read as a pattern: each as KiCad 10.0.8's DRC had it, 2026-11-20.
NAMED = [
    ("V+", r"V\+", ["V", "VV"]),
    ("+12V", r"\+12V", []),
    ("A.B", r"A\.B", ["AxB"]),
    ("D*", r"D\x2a", ["DATA", "D"]),
    ("Q?", r"Q\x3f", ["Qx", "Q"]),
    ("Net-(U1-Pad3)", r"Net-\(U1-Pad3\)", ["Net-U1-Pad3"]),
    ("B[1]", r"B\[1\]", ["B1"]),
    ("C{2}", "C[{]2[}]", []),
    ("N}", "N[}]", []),
    ("O{", "O[{]", []),
    ("Ea|Fa", r"Ea\|Fa", ["Ea", "Fa"]),
    ("^G", r"\^G", ["G"]),
    ("H$", r"H\$", ["H"]),
    ("K\\d", r"K\\d", ["K7"]),
]


@pytest.mark.parametrize(("net", "pattern", "taken"), NAMED)
def test_a_net_is_written_as_the_pattern_that_only_its_name_matches(net, pattern, taken):
    assert exactly(net) == pattern
    # As an expression it is the name, whole, and none of what the name would take.
    assert re.fullmatch(pattern, net) and not any(re.fullmatch(pattern, other) for other in taken)
    assert all(re.fullmatch(net, other) for other in taken if net not in ("D*", "Q?", "+12V"))
    # As a wildcard it has nothing that stands for another character.
    assert "*" not in pattern and "?" not in pattern


@pytest.mark.parametrize(
    "net", ["GND", "N-0000018", "/current_limit_r/R_LIM-", "/a/b", "R S", "T~#<>,;:'T", "+", ""]
)
def test_a_name_kicad_reads_as_itself_is_its_own_pattern(net):
    assert exactly(net) == (net if net != "+" else r"\+")
    assert exactly("all+.*?()[]{}|^$\\") == r"all\+\.\x2a\x3f\(\)\[\][{][}]\|\^\$\\"


def test_a_project_has_each_member_as_a_pattern_for_its_name_alone(tmp_path):
    classes = [NetClass("Default", 0.2, 0.5), NetClass("Power", 0.2, 1.0)]
    wrote = write_project(tmp_path / "b.kicad_pro", netclasses=classes,
                          members={"Power": ["V+", "GND", "Net-(U1-Pad3)"]}, rules={},
                          severities={})  # fmt: skip
    assert json.loads(wrote.read_text())["net_settings"]["netclass_patterns"] == [
        {"netclass": "Power", "pattern": "GND"},
        {"netclass": "Power", "pattern": r"Net-\(U1-Pad3\)"},
        {"netclass": "Power", "pattern": r"V\+"},
    ]
    bare = write_project(tmp_path / "c.kicad_pro", netclasses=classes[:1], members={}, rules={},
                         severities={})  # fmt: skip
    assert json.loads(bare.read_text())["net_settings"]["netclass_patterns"] == []
