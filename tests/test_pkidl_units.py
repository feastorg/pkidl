"""pkidl.units: lengths with their unit, kept as whole nanometres."""

# The refusals below are of operands of the wrong type, written on purpose.
# pyright: reportOperatorIssue=false, reportArgumentType=false

import pytest

from pkidl import inch, mil, mm
from pkidl.units import Length, length


def test_one_distance_written_three_ways_is_one_value():
    assert 1.27 * mm == mm * 1.27 == 50 * mil == 0.05 * inch == Length(1_270_000)
    assert 0.1 * inch == 2.54 * mm  # 0.1 * 25_400_000 is not a whole number as a float
    assert len({1.27 * mm, 50 * mil, length("1.27mm")}) == 1


@pytest.mark.parametrize(
    ("text", "nm"),
    [("1.27mm", 1_270_000), (" 50 mil ", 1_270_000), ("0.1in", 2_540_000), ("0.1inch", 2_540_000),
     (".5mm", 500_000), ("2.mm", 2_000_000), ("-1mm", -1_000_000), ("3mm", 3_000_000)],
)  # fmt: skip
def test_a_length_is_read_from_a_number_and_its_unit(text, nm):
    assert length(text) == Length(nm)
    assert length(Length(nm)) == Length(nm)


@pytest.mark.parametrize("text", ["1.27", "mm", "1.27 furlongs", "1,27mm", "1.27mmm", "1e3mm", ""])
def test_text_that_is_not_a_number_and_a_unit_is_refused(text):
    with pytest.raises(ValueError, match="is not a length"):
        length(text)


def test_a_bare_number_is_not_a_length():
    with pytest.raises(TypeError, match=r'1.27 has no unit: write 1.27 \* mm or "1.27mm"'):
        length(1.27)
    for nm in (1.5, True, "3"):
        with pytest.raises(TypeError, match="whole number of nanometres"):
            Length(nm)


def test_lengths_add_scale_and_compare_without_drifting():
    assert sum([0.1 * mm] * 10, Length(0)) == mm  # 0.1 + ... + 0.1 is not 1.0 in floats
    assert inch - 25.4 * mm == Length(0)
    assert inch / 2 == 12.7 * mm
    # To the nearest nanometre, not the one below.
    assert (2 * mm) / 3 == (2 / 3) * mm == Length(666_667)
    assert inch / mm == 25.4
    assert -mm == Length(-1_000_000)
    assert mil < mm < inch and -mm < Length(0) < mil
    assert (1.27 * mm).mm == 1.27


@pytest.mark.parametrize(
    "wrong",
    [lambda: mm * mm, lambda: mm + 1, lambda: 1 - mm, lambda: True * mm, lambda: mm / True,
     lambda: mm < 1],
)  # fmt: skip
def test_a_length_does_not_mix_with_what_is_not_one(wrong):
    with pytest.raises(TypeError):
        wrong()


def test_a_length_prints_in_millimetres_to_the_nanometre():
    assert [str(x) for x in (1.27 * mm, 3 * mm, Length(0), Length(1), 0.1 * inch, -0.5 * mm)] == [
        "1.27 mm", "3 mm", "0 mm", "0.000001 mm", "2.54 mm", "-0.5 mm"]  # fmt: skip
