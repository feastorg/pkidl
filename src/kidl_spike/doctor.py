"""Check that the toolchain and library resolution are actually wired up.

Run `just doctor` before trusting anything this project generates. It exists
because the failure mode we care about is silent: a board that *looks* generated
but was resolved against the wrong libraries, or not resolved at all.
"""

from __future__ import annotations

import shlex
import subprocess
import sys
from collections.abc import Iterator

from kidl_spike import libs

# KiCad is pinned to an exact version. Stock symbol libraries change across KiCad
# releases, and this project exists to eliminate exactly that silent drift, so a
# KiCad upgrade is a REVIEWED EVENT: bump this pin deliberately, in its own commit.
# This constant is the single source of truth for the pinned version.
# See _planning/01-kidl-spike.md (P4).
WANT_KICAD = "10.0.6"


def _kicad_cli() -> list[str]:
    import os

    return shlex.split(
        os.environ.get("KICAD_CLI", "flatpak run --command=kicad-cli org.kicad.KiCad")
    )


def _check(name: str, ok: bool, detail: str) -> tuple[bool, str]:
    return ok, f"{'PASS' if ok else 'FAIL'}  {name:<22} {detail}"


def checks() -> Iterator[tuple[bool, str]]:
    yield _check(
        "python",
        sys.version_info >= (3, 13),
        f"{sys.version_info.major}.{sys.version_info.minor}",
    )

    try:
        import skidl

        yield _check("skidl", True, skidl.__version__)
    except ImportError as e:  # pragma: no cover - environment failure
        yield _check("skidl", False, str(e))

    try:
        out = subprocess.run(
            [*_kicad_cli(), "version"], capture_output=True, text=True, timeout=60, check=True
        ).stdout.strip()
        ver = out.split()[0] if out else out
        yield _check(
            "kicad-cli",
            ver == WANT_KICAD,
            out
            if ver == WANT_KICAD
            else f"{out} (pinned {WANT_KICAD}; a bump is a reviewed event)",
        )
    except (OSError, subprocess.SubprocessError) as e:
        yield _check("kicad-cli", False, f"not runnable: {e}")

    try:
        root = libs.master_lib_root()
        yield _check("KICAD_MASTER_LIB", True, str(root))
    except libs.LibraryError as e:
        yield _check("KICAD_MASTER_LIB", False, str(e))
        return  # every check below depends on this

    for kind in libs.TABLES:
        try:
            n = len(libs.load_table(kind))
            yield _check(f"{kind} table", True, f"{n} libraries")
        except libs.LibraryError as e:
            yield _check(f"{kind} table", False, str(e))

    missing = libs.missing_libraries()
    yield _check(
        "libraries on disk",
        not missing,
        "all present"
        if not missing
        else f"{len(missing)} missing: " + ", ".join(m.nickname for m in missing[:3]),
    )

    stock_sym, stock_fp = libs.stock_dirs()
    yield _check("stock symbols", stock_sym is not None, str(stock_sym or "NOT FOUND"))
    yield _check("stock footprints", stock_fp is not None, str(stock_fp or "NOT FOUND"))

    # The checks above only prove the tables parse. This proves SKiDL can actually
    # pull a part through them -- the difference between a green light and a
    # working toolchain, and the whole reason this command exists.
    for lib_name, part_name in (
        ("Device", "R"),  # stock KiCad
        ("KMLib_IC_Power", "AP63205WU-7_Buck_Regulator"),  # first-party
        ("SparkFun-LED", "WS2812B_5050"),  # vendored upstream
    ):
        try:
            import skidl

            libs.configure_skidl()
            skidl.Part(lib_name, part_name, dest=skidl.TEMPLATE)
            yield _check(f"resolve {lib_name}", True, part_name)
        except Exception as e:  # noqa: BLE001 - any failure here is a real failure
            yield _check(f"resolve {lib_name}", False, f"{part_name}: {type(e).__name__} {e}")


def main() -> int:
    results = list(checks())
    for _, line in results:
        print(line)
    failed = [line for ok, line in results if not ok]
    print()
    if failed:
        print(f"{len(failed)} check(s) failed — generated output cannot be trusted.")
        return 1
    print("Environment OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
