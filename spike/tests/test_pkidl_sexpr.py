"""pkidl reads and writes KiCad s-expressions without changing them."""

from pkidl.sexpr import Sym, dumps, num, parse


def test_round_trip_keeps_tree_and_atom_kinds():
    text = (
        '(footprint "A:B" (layer "F.Cu") (at 1.50 -2 90) '
        '(property "Value" "say \\"hi\\"") (hide yes))'
    )
    tree = parse(text)
    assert parse(dumps(tree)) == tree
    assert not isinstance(tree[2][1], Sym)  # quoted string stays a string
    assert tree[3][1] == "1.50" and isinstance(tree[3][1], Sym)  # number kept as written
    assert tree[4][2] == 'say "hi"'


def test_dumps_is_kicad_shaped():
    assert dumps(parse('(a (b 1) (c "x"))')) == '(a\n\t(b 1)\n\t(c "x")\n)'


def test_num_formats_like_kicad():
    assert [num(x) for x in (1.0, -0.0, 0.1 + 0.2, 1.23456789, -2.5)] == [
        "1",
        "0",
        "0.3",
        "1.234568",
        "-2.5",
    ]
