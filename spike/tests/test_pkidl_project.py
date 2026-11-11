"""pkidl writes KiCad custom design rules that gate what netclasses only suggest."""

from pkidl.project import DruRule, NetClass, width_rules, write_rules


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
