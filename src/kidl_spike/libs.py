"""Resolve KiCad libraries from committed tables rather than global config.

The whole point of this project is that a board can be regenerated from source.
That is only true if symbol and footprint nicknames resolve the same way on every
machine — so we read the library tables committed to KiCad-Master-Lib and never
touch the developer's global KiCad configuration.

See `_planning/01-kidl-spike.md` (risk R1) for why this exists.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

# Library tables committed to KiCad-Master-Lib, keyed by what they register.
TABLES = {
    "symbol": "kmlib.sym-lib-table",
    "footprint": "kmlib.fp-lib-table",
    "design_block": "kmlib.design-block-lib-table",
}

_LIB_RE = re.compile(r'\(name "([^"]+)"\)\(type "[^"]*"\)\(uri "([^"]+)"\)')


class LibraryError(RuntimeError):
    """Library resolution is misconfigured. Never guess — fail loudly."""


@dataclass(frozen=True)
class Library:
    nickname: str
    path: Path


def master_lib_root() -> Path:
    """The KiCad-Master-Lib checkout, from $KICAD_MASTER_LIB."""
    raw = os.environ.get("KICAD_MASTER_LIB")
    if not raw:
        raise LibraryError(
            "KICAD_MASTER_LIB is not set. Point it at a KiCad-Master-Lib checkout; "
            "without it no symbol or footprint nickname can be resolved."
        )
    root = Path(raw).expanduser().resolve()
    if not root.is_dir():
        raise LibraryError(f"KICAD_MASTER_LIB does not exist: {root}")
    return root


def load_table(kind: str, root: Path | None = None) -> dict[str, Library]:
    """Parse one committed library table into {nickname: Library}."""
    if kind not in TABLES:
        raise LibraryError(f"unknown table kind {kind!r}; expected one of {sorted(TABLES)}")
    root = root or master_lib_root()
    table = root / TABLES[kind]
    if not table.is_file():
        raise LibraryError(
            f"{table.name} missing from {root}. Regenerate it there with "
            "`python3 scripts/gen_lib_tables.py`."
        )

    libs: dict[str, Library] = {}
    for nickname, uri in _LIB_RE.findall(table.read_text()):
        libs[nickname] = Library(nickname, Path(uri.replace("${KICAD_MASTER_LIB}", str(root))))
    if not libs:
        raise LibraryError(f"{table.name} registers no libraries")
    return libs


def symbol_search_paths(root: Path | None = None) -> list[Path]:
    """Directories holding .kicad_sym files, for SKiDL's library search path.

    SKiDL searches directories rather than reading a sym-lib-table, so we derive
    the directory set from the table instead of hardcoding paths.
    """
    dirs = {lib.path.parent for lib in load_table("symbol", root).values()}
    return sorted(dirs)


def missing_libraries(root: Path | None = None) -> list[Library]:
    """Registered libraries whose files are not actually on disk.

    A sparse checkout that excludes 3D models is fine; one that has lost a
    library is not.
    """
    root = root or master_lib_root()
    missing = []
    for kind in TABLES:
        missing += [lib for lib in load_table(kind, root).values() if not lib.path.exists()]
    return missing


def stock_dirs() -> tuple[Path | None, Path | None]:
    """The KiCad-supplied symbol and footprint libraries (Device, Connector, ...).

    Most parts on these boards come from stock KiCad, not the master library. The
    flatpak keeps them outside any obvious prefix, so allow an explicit override
    for CI and containers where the layout differs.
    """

    def pick(env: str, glob: str) -> Path | None:
        if raw := os.environ.get(env):
            p = Path(raw)
            return p if p.is_dir() else None
        return next((p for p in Path("/var/lib/flatpak/runtime").glob(glob) if p.is_dir()), None)

    return (
        pick("KICAD_STOCK_SYMBOL_DIR", "org.kicad.KiCad.Library.Symbols/*/*/*/files/symbols"),
        pick(
            "KICAD_STOCK_FOOTPRINT_DIR",
            "org.kicad.KiCad.Library.Footprints/*/*/*/files/footprints",
        ),
    )


def footprint_file(lib_id: str, root: Path | None = None) -> Path:
    """The `.kicad_mod` file for a "Library:Footprint" id.

    Master-library nicknames resolve through the committed table; anything else
    is looked for among the stock KiCad footprints.
    """
    nickname, _, name = lib_id.partition(":")
    table = load_table("footprint", root)
    if nickname in table:
        lib_dir = table[nickname].path
    else:
        _, stock_fp = stock_dirs()
        if stock_fp is None:
            raise LibraryError(f"{lib_id}: not in the master library, and no stock footprints")
        lib_dir = stock_fp / f"{nickname}.pretty"
    path = lib_dir / f"{name}.kicad_mod"
    if not path.is_file():
        raise LibraryError(f"{lib_id}: {path} does not exist")
    return path


def write_fp_lib_table(dest: Path, root: Path | None = None) -> Path:
    """Materialise a KiCad-standard `fp-lib-table` that SKiDL can actually read.

    SKiDL looks for a file named exactly `fp-lib-table` in a search directory;
    ours is committed as `kmlib.fp-lib-table`, so it would never be found. Expand
    ${KICAD_MASTER_LIB} and add the stock KiCad footprints, then write it out.
    """
    root = root or master_lib_root()

    def entry(nickname: str, uri: Path) -> str:
        return f'  (lib (name "{nickname}")(type "KiCad")(uri "{uri}")(options "")(descr ""))'

    entries = [entry(lib.nickname, lib.path) for lib in load_table("footprint", root).values()]

    _, stock_fp = stock_dirs()
    if stock_fp:
        entries += [entry(p.stem, p) for p in sorted(stock_fp.glob("*.pretty"))]

    dest.mkdir(parents=True, exist_ok=True)
    table = dest / "fp-lib-table"
    table.write_text("(fp_lib_table\n  (version 7)\n" + "\n".join(entries) + "\n)\n")
    return table


def write_project_lib_tables(dest: Path, root: Path | None = None) -> None:
    """Write a project's `sym-lib-table` and `fp-lib-table` into *dest*.

    Generated projects carry their own tables so KiCad's ERC and DRC resolve
    libraries from the project, not from a machine's global configuration. URIs
    keep their variables (`${KICAD_MASTER_LIB}`, `${KICAD10_SYMBOL_DIR}`, ...),
    which KiCad expands, so the same tables work in any environment that sets
    them.
    """
    root = root or master_lib_root()
    stock: dict[str, Path | None] = dict(zip(("symbol", "footprint"), stock_dirs(), strict=True))
    for kind, table_name, stock_var, suffix in (
        ("symbol", "sym-lib-table", "KICAD10_SYMBOL_DIR", ".kicad_sym"),
        ("footprint", "fp-lib-table", "KICAD10_FOOTPRINT_DIR", ".pretty"),
    ):
        raw = (root / TABLES[kind]).read_text()
        entries = dict(_LIB_RE.findall(raw))
        if stock_dir := stock[kind]:
            for p in sorted(stock_dir.glob(f"*{suffix}")):
                entries.setdefault(p.stem, f"${{{stock_var}}}/{p.name}")
        head = table_name.replace("-", "_")
        lines = [
            f'  (lib (name "{n}")(type "KiCad")(uri "{u}")(options "")(descr ""))'
            for n, u in sorted(entries.items())
        ]
        (dest / table_name).write_text(f"({head}\n  (version 7)\n" + "\n".join(lines) + "\n)\n")


def configure_skidl(tool=None, workdir: Path | None = None) -> None:
    """Point SKiDL at our libraries, so nothing resolves via global KiCad config.

    Must be called before any Part() lookup. Idempotent.
    """
    import skidl

    # SKiDL injects KICAD5..KICAD10 onto the module at import time by scanning
    # tools/, so they are invisible to static analysis.
    tool = tool or getattr(skidl, "KICAD10")  # noqa: B009
    root = master_lib_root()
    workdir = workdir or Path("build/kicad-env")
    workdir.mkdir(parents=True, exist_ok=True)

    stock_sym, _ = stock_dirs()
    sym_paths = [str(p) for p in symbol_search_paths(root)]
    if stock_sym:
        sym_paths.append(str(stock_sym))

    for path in sym_paths:
        if path not in skidl.lib_search_paths[tool]:
            skidl.lib_search_paths[tool].append(path)

    fp_dir = str(write_fp_lib_table(workdir, root).parent)
    if fp_dir not in skidl.footprint_search_paths[tool]:
        skidl.footprint_search_paths[tool].append(fp_dir)
