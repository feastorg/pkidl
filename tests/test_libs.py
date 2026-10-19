"""Library resolution must not depend on global KiCad config — that was risk R1."""

from pathlib import Path

import pytest

from kidl_spike import libs

MASTER_LIB = Path(__file__).resolve().parents[2] / "KiCad-Master-Lib"

pytestmark = pytest.mark.skipif(
    not MASTER_LIB.is_dir(), reason="KiCad-Master-Lib checkout not present"
)


def test_master_lib_root_requires_env(monkeypatch):
    monkeypatch.delenv("KICAD_MASTER_LIB", raising=False)
    with pytest.raises(libs.LibraryError, match="KICAD_MASTER_LIB"):
        libs.master_lib_root()


@pytest.mark.parametrize("kind", sorted(libs.TABLES))
def test_every_table_loads(kind):
    assert libs.load_table(kind, MASTER_LIB)


def test_bread_slice_bus_connector_resolves():
    """The BREADS slice-bus connector is the one part the standard cannot lose."""
    fp = libs.load_table("footprint", MASTER_LIB)["KMLib_Connectors"]
    assert (fp.path / "BREAD_Slice_Bus_10Pin.kicad_mod").is_file()


def test_no_registered_library_is_missing_from_disk():
    assert libs.missing_libraries(MASTER_LIB) == []


def test_symbol_search_paths_are_real_dirs():
    paths = libs.symbol_search_paths(MASTER_LIB)
    assert paths and all(p.is_dir() for p in paths)


def test_configure_skidl_resolves_master_library_sources(monkeypatch, tmp_path):
    """First-party and vendored parts must resolve through our tables.

    This is the check that would have caught R1: counting table entries proves
    nothing, pulling a real part through SKiDL proves the toolchain works. These
    parts are the reproducibility boundary and are always verified.
    """
    skidl = pytest.importorskip("skidl")
    monkeypatch.setenv("KICAD_MASTER_LIB", str(MASTER_LIB))
    libs.configure_skidl(workdir=tmp_path)

    for lib_name, part_name in [
        ("KMLib_IC_Power", "AP63205WU-7_Buck_Regulator"),
        ("SparkFun-LED", "WS2812B_5050"),
    ]:
        assert skidl.Part(lib_name, part_name, dest=skidl.TEMPLATE)


def test_configure_skidl_resolves_stock_part(monkeypatch, tmp_path):
    """A stock KiCad part resolves where stock symbol libraries are present.

    SKiDL reads single-file `.kicad_sym` libraries; KiCad 10 ships stock symbols
    as sharded `.kicad_symdir` directories it cannot yet parse. So this is
    exercised only where a stock symbol library is actually available (e.g. a
    local flatpak install) and skipped where none is (e.g. CI). The master
    library, resolved in the test above, is the reproducibility boundary.
    """
    skidl = pytest.importorskip("skidl")
    stock_sym, _ = libs.stock_dirs()
    if stock_sym is None:
        pytest.skip("no stock KiCad symbol library present")
    monkeypatch.setenv("KICAD_MASTER_LIB", str(MASTER_LIB))
    libs.configure_skidl(workdir=tmp_path)
    assert skidl.Part("Device", "R", dest=skidl.TEMPLATE)
