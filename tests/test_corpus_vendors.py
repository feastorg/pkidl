"""The vendor boards: what ``corpus/vendors/`` pins, and how ``scripts/corpus.py fetch``
gets a board. Nothing here downloads anything: a board is fetched from a directory laid
out as the vendor's file server is.
"""

import importlib.util
import json
import re
import urllib.parse
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
VENDORS = ROOT / "corpus" / "vendors"
MANIFESTS = {p.stem: json.loads(p.read_text()) for p in sorted(VENDORS.glob("*.json"))}
ROWS = [(vendor, b) for vendor, m in MANIFESTS.items() for b in m["boards"]]
# What a row is. Only a "board" is fetched unless everything is asked for.
KINDS = {"board", "panel", "backup", "duplicate", "stub", "drawing", "template", "example",
         "jig", "mechanical", "vendored", "copy", "guide"}  # fmt: skip
FORMATS = {"kicad_pcb", "eagle_brd_xml", "eagle_brd_binary", "brd"}

each_vendor = pytest.mark.parametrize("vendor", sorted(MANIFESTS))


def _script():
    spec = importlib.util.spec_from_file_location("corpus_script", ROOT / "scripts" / "corpus.py")
    assert spec is not None and spec.loader is not None
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    return script


script = _script()


def _row(vendor: str, repository: str, path: str) -> dict:
    return next(b for b in MANIFESTS[vendor]["boards"]
                if (b["repository"], b["path"]) == (repository, path))  # fmt: skip


def test_the_manifests_are_found():
    # An empty glob would pass every test below.
    assert {v: len(m["boards"]) for v, m in MANIFESTS.items()} == {
        "adafruit": 953, "olimex": 423, "sparkfun": 1705,
    }  # fmt: skip
    assert len(script.vendor_boards()) == len(ROWS)


@each_vendor
def test_every_row_says_what_is_needed_to_fetch_and_check_it(vendor):
    manifest = MANIFESTS[vendor]
    assert manifest["vendor"] == vendor
    for b in manifest["boards"]:
        where = f"{b['repository']} {b['path']}"
        pinned = manifest["repositories"][b["repository"]]
        assert re.fullmatch(r"[0-9a-f]{40}", pinned["commit"]), where
        assert re.fullmatch(r"[0-9a-f]{40}", b["blob"]), where
        assert isinstance(b["size"], int) and b["size"] > 0, where
        assert re.fullmatch(r"[^/]+/[^/]+", b["repository"]), where
        # A path is kept under the cache as it is: it may not climb out of it.
        parts = b["path"].split("/")
        assert not b["path"].startswith("/") and ".." not in parts and "" not in parts, where
        assert b["path"].lower().endswith((".kicad_pcb", ".brd")), where
        assert b["format"] in FORMATS and b["kind"] in KINDS, where
        assert (b["format"] == "kicad_pcb") == b["path"].endswith(".kicad_pcb"), where
        assert b["product"] and isinstance(b["current"], bool), where
    listed = Counter((b["repository"], b["path"]) for b in manifest["boards"])
    assert max(listed.values()) == 1
    # A repository is in the manifest for its boards, and its facts are all there.
    assert set(manifest["repositories"]) == {b["repository"] for b in manifest["boards"]}
    for facts in manifest["repositories"].values():
        assert set(facts) == {"commit", "commit_date", "licence_file", "licence_spdx",
                              "readme_read", "ratings"}  # fmt: skip
        # A rating is a sentence of a README that was read, and of no other.
        assert facts["readme_read"] or not facts["ratings"]


@each_vendor
def test_only_a_product_board_is_a_current_revision(vendor):
    boards = MANIFESTS[vendor]["boards"]
    assert all(b["kind"] == "board" for b in boards if b["current"])
    # Of one product in one repository and one format, the current files are one revision.
    revisions: dict[tuple, set] = {}
    for b in boards:
        if b["current"]:
            key = (b["repository"], b["product"], b["format"])
            revisions.setdefault(key, set()).add(b["revision"])
    assert [key for key, revs in revisions.items() if len(revs) > 1] == []


def test_an_olimex_product_has_one_current_board_file_in_a_repository():
    current = Counter((b["repository"], b["product"])
                      for b in MANIFESTS["olimex"]["boards"] if b["current"])  # fmt: skip
    assert [key for key, n in current.items() if n > 1] == []


@each_vendor
def test_a_duplicate_names_the_board_whose_bytes_it_is(vendor):
    boards = MANIFESTS[vendor]["boards"]
    kept = {f"{b['repository']}:{b['path']}": b for b in boards if b["kind"] == "board"}
    assert max(Counter(b["blob"] for b in kept.values()).values()) == 1
    for b in boards:
        assert ("same_as" in b) == (b["kind"] == "duplicate")
        if b["kind"] == "duplicate":
            assert kept[b["same_as"]]["blob"] == b["blob"]
            assert kept[b["same_as"]]["size"] == b["size"]


@each_vendor
def test_a_stub_is_a_file_too_small_to_be_a_board(vendor):
    for b in MANIFESTS[vendor]["boards"]:
        assert (b["kind"] == "stub") == (b["size"] < 2000), b["path"]


@pytest.mark.parametrize(("vendor", "repository", "path", "kind", "current"), [
    # "Holder" and "Solderable" have "older" in them, and are not older revisions.
    ("sparkfun", "sparkfun/Coin_Cell_Battery_Holder_Breakout-24.5mm",
     "Hardware/SparkFun_Coin_Cell_Battery_Holder-24.5mm.brd", "board", True),
    ("sparkfun", "sparkfun/Solderable_Breadboard_Large",
     "hardware/Solderable_Breadboard_Large.brd", "board", True),
    # The front of an enclosure is a panel, and not a panel of boards for production.
    ("sparkfun", "sparkfun/SparkFun_RTK_mosaic-X5",
     "Front_Panel/RTK_mosaic-X5_Front_Panel.brd", "mechanical", False),
    # A file under Production/ is a production copy, whatever its name.
    ("sparkfun", "sparkfun/gator_microphone",
     "hardware/Production/gatormicrophone.brd", "panel", False),
    ("sparkfun", "sparkfun/Qwiic_IMU_BNO080",
     "Hardware/TestJig/Jig-Top-Layer.brd", "jig", False),
    # A revision named by its folder alone.
    ("sparkfun", "sparkfun/Pro_Micro", "Hardware/v13/SparkFun_Pro_Micro.brd", "board", False),
    ("sparkfun", "sparkfun/Pro_Micro", "Hardware/v20/SparkFun_Pro_Micro.brd", "board", True),
    # Two revisions in one folder named the latest: the higher is.
    ("olimex", "OLIMEX/OLINUXINO",
     "HARDWARE/A20-OLinuXino-LIME2/1. Latest hardware revision/A20-OLinuXino-Lime2_Rev_M.brd",
     "board", False),
    ("olimex", "OLIMEX/OLINUXINO",
     "HARDWARE/A20-OLinuXino-LIME2/1. Latest hardware revision/A20-OLinuXino-Lime2_Rev_N.brd",
     "board", True),
    # The latest revision is kept again among the older ones: the same bytes.
    ("olimex", "OLIMEX/OLINUXINO",
     "HARDWARE/A20-OLinuXino-LIME2/2. Older hardware revisions/"
     "A20-OLinuXino-LIME2 hardware revision M/A20-OLinuXino-Lime2_Rev_M.brd", "duplicate", False),
    # Rev A of the Neo6502, in a folder spelt New6502, is not a product of its own.
    ("olimex", "OLIMEX/Neo6502", "HARDWARE/New6502-Rev-A/Neo6502_Rev_A.kicad_pcb", "board", False),
    # A preliminary layout beside the released one of the same revision.
    ("olimex", "OLIMEX/S3-OLinuXino",
     "HARDWARE/S3-OLinuXino-Rev_A-preliminary/S3-OLinuXino_Rev_A.kicad_pcb", "board", False),
    ("olimex", "OLIMEX/S3-OLinuXino",
     "HARDWARE/S3-OLinuXino_Rev_A-release/S3-OLinuXino_Rev_A.kicad_pcb", "board", True),
    ("olimex", "OLIMEX/NB-IoT",
     "HARDWARE/NB-IoT-DevKit_Rev_C/Extensions/Extension_Rev_B/Extension_Rev_B.kicad_pcb",
     "stub", False),
    ("olimex", "OLIMEX/iCE40HX1K-EVB", "_autosave-ICE40-1KEVB_Rev_A.kicad_pcb", "backup", False),
    ("olimex", "OLIMEX/ESP32-C6-EVB",
     "HARDWARE/Dimensions/ESP32-C6-EVB_DIMM_Rev_A.kicad_pcb", "drawing", False),
    # A board of somebody else's tool, kept with the software.
    ("olimex", "OLIMEX/RVPC",
     "SOFTWARE/rvpc/tools/esp32s2-cookbook/hardware/exposed_power_rails/"
     "exposed_power_rails.kicad_pcb", "vendored", False),
    # "16 B" beside "16 rev C" is revision B, with no word to say so.
    ("adafruit", "adafruit/Adafruit-NeoPixel-Ring", "Adafruit NeoPixel Ring 16 B.brd",
     "board", False),
    ("adafruit", "adafruit/Adafruit-NeoPixel-Ring", "Adafruit NeoPixel Ring 16 rev C.brd",
     "board", True),
    ("adafruit", "adafruit/Adafruit_Learning_System_Guides",
     "PCB_Art_Jewelry/525floppy.kicad_pcb", "guide", False),
])  # fmt: skip
def test_the_rows_an_inventory_by_rule_had_wrong_are_as_their_paths_say(
    vendor, repository, path, kind, current
):
    row = _row(vendor, repository, path)
    assert (row["kind"], row["current"]) == (kind, current)


def test_the_neo6502_in_a_misspelt_folder_is_a_neo6502():
    row = _row("olimex", "OLIMEX/Neo6502", "HARDWARE/New6502-Rev-A/Neo6502_Rev_A.kicad_pcb")
    assert (row["product"], row["revision"]) == ("Neo6502", "A")


def test_only_product_boards_are_chosen_unless_everything_is_asked_for():
    boards = script.vendor_boards()
    assert {b["kind"] for b in script.chosen(boards)} == {"board"}
    assert len(script.chosen(boards, every=True)) == len(boards)
    olimex = script.chosen(boards, vendors=["olimex"], current=True, kicad=True)
    assert olimex and all(
        b["vendor"] == "olimex" and b["current"] and b["path"].endswith(".kicad_pcb")
        for b in olimex
    )
    # A product by its name or its repository's, in any case; and by nothing less.
    by_name = script.chosen(boards, product="esp32-poe")
    assert {b["product"] for b in by_name} == {"ESP32-PoE"} and len(by_name) > 1
    assert {b["repository"] for b in script.chosen(boards, product="OLINUXINO")} == {
        "OLIMEX/OLINUXINO"
    }
    assert script.chosen(boards, product="esp32") == []
    assert script.fetch_command(["--product", "no such product"]) == 1


def test_a_blob_hash_is_the_one_git_gives():
    # `git hash-object` of an empty file, and of one that says hello.
    assert script.blob_sha(b"") == "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"
    assert script.blob_sha(b"hello\n") == "ce013625030ba8dba906f756967f9e9ca394464a"


def test_a_board_is_asked_for_at_its_commit_with_its_path_quoted():
    board = {"repository": "OLIMEX/OLINUXINO", "commit": "c" * 40,
             "path": "HARDWARE/LCDs/A13 LCD/A13-LCD4.3''_Rev_B (2)#1+é&.brd"}  # fmt: skip
    assert script.raw_url(board) == (
        "https://raw.githubusercontent.com/OLIMEX/OLINUXINO/" + "c" * 40
        + "/HARDWARE/LCDs/A13%20LCD/A13-LCD4.3%27%27_Rev_B%20%282%29%231%2B%C3%A9%26.brd"
    )  # fmt: skip
    # Every pinned path survives the quoting, and none leaves a character that would end
    # the path or split it.
    for b in script.vendor_boards():
        tail = script.raw_url(b, "x:").removeprefix(f"x:/{b['repository']}/{b['commit']}/")
        assert urllib.parse.unquote(tail) == b["path"]
        assert re.fullmatch(r"[A-Za-z0-9._~/%-]+", tail), b["path"]


def _served(root: Path, name: str, data: bytes, *, pin: bytes | None = None) -> dict:
    """A board of *data* served under *root* as the vendors' files are, and its manifest
    row, pinning *pin* where the manifest and the server are to disagree."""
    pinned = data if pin is None else pin
    board = {
        "vendor": "olimex",
        "repository": "OLIMEX/SOME-BOARD",
        "commit": "ab" * 20,
        "path": f"HARDWARE/1. Latest hardware revision/{name}",
        "blob": script.blob_sha(pinned),
        "size": len(pinned),
        "kind": "board",
        "current": True,
        "format": "kicad_pcb",
        "product": "SOME-BOARD",
    }
    served = root / board["repository"] / board["commit"] / board["path"]
    served.parent.mkdir(parents=True, exist_ok=True)
    served.write_bytes(data)
    return board


def test_a_board_is_fetched_once_and_checked_against_its_blob_hash(tmp_path, capsys):
    server, cache = tmp_path / "server", tmp_path / "cache"
    board = _served(server, "SOME-BOARD_Rev_B (4GB)''.kicad_pcb", b"(kicad_pcb (version 4))\n")
    assert script.fetch([board], cache, server.as_uri()) == 0
    kept = script.cached(board, cache)
    assert kept == cache / "OLIMEX/SOME-BOARD" / board["path"]
    assert kept.read_bytes() == b"(kicad_pcb (version 4))\n"
    assert [p.name for p in kept.parent.iterdir()] == [kept.name]  # nothing half-written
    assert "1 fetched, 0 already there, 0 failed" in capsys.readouterr().out

    # What is there is not asked for again: the server may be gone.
    (server / board["repository"] / board["commit"] / board["path"]).unlink()
    assert script.fetch([board], cache, server.as_uri()) == 0
    assert "0 fetched, 1 already there, 0 failed" in capsys.readouterr().out


def test_a_cached_file_that_is_not_the_pinned_bytes_is_fetched_again(tmp_path, capsys):
    server, cache = tmp_path / "server", tmp_path / "cache"
    board = _served(server, "board.kicad_pcb", b"the pinned bytes\n")
    kept = script.cached(board, cache)
    kept.parent.mkdir(parents=True)
    kept.write_bytes(b"an edited copy\n")
    assert script.fetch([board], cache, server.as_uri()) == 0
    assert kept.read_bytes() == b"the pinned bytes\n"
    assert "1 fetched, 0 already there" in capsys.readouterr().out


def test_bytes_that_are_not_the_pinned_ones_are_not_kept_and_the_rest_still_are(tmp_path, capsys):
    server, cache = tmp_path / "server", tmp_path / "cache"
    moved = _served(server, "moved.kicad_pcb", b"what is served now\n", pin=b"what was pinned\n")
    gone = _served(server, "gone.kicad_pcb", b"x")
    (server / gone["repository"] / gone["commit"] / gone["path"]).unlink()
    good = _served(server, "good.kicad_pcb", b"a good board\n")
    assert script.fetch([moved, gone, good], cache, server.as_uri()) == 1
    assert not script.cached(moved, cache).exists()
    assert not script.cached(gone, cache).exists()
    assert script.cached(good, cache).read_bytes() == b"a good board\n"
    said = capsys.readouterr()
    assert "1 fetched, 0 already there, 2 failed" in said.out
    served = script.blob_sha(b"what is served now\n")
    assert f"moved.kicad_pcb: not kept: 19 bytes with the git hash {served}" in said.err
    assert f"where the manifest pins 16 bytes with {moved['blob']}" in said.err
    assert "gone.kicad_pcb: not downloaded:" in said.err
