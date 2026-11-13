"""Shared by pkidl's tests."""

import pytest


@pytest.fixture(autouse=True)
def no_kicad(monkeypatch):
    """pkidl's tests need no KiCad, and are not to change with whether it is installed:
    a build asks KiCad about its pours where it finds it. A test that wants it says
    which command it is."""
    monkeypatch.setenv("KICAD_CLI", "no-such-kicad-cli")
