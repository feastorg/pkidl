"""Shared by pkidl's tests."""

import pytest


@pytest.fixture(autouse=True, scope="session")
def no_kicad():
    """pkidl's tests need no KiCad, and are not to change with whether it is installed:
    a build asks KiCad about its pours where it finds it. For the whole run, fixtures
    that build once for a module among it. A test that wants KiCad says which command
    it is, for itself."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("KICAD_CLI", "no-such-kicad-cli")
        yield
