"""pkidl runs Freerouting single-threaded, autorouter and optimizer both."""

import sys

from pkidl.route import freerouting

STUB = """import sys
args = sys.argv[1:]
open(sys.argv[0] + ".args", "w").write("\\n".join(args))
open(args[args.index("-do") + 1], "w").write("(session x)")
"""


def test_both_router_stages_run_on_one_thread(tmp_path, monkeypatch):
    """-mt 1 limits only the autorouter; the optimizer's threads made the same DSN route
    three different ways in six runs, so its own limit must be passed too."""
    stub = tmp_path / "router.py"
    stub.write_text(STUB)
    monkeypatch.setenv("FREEROUTING", f"{sys.executable} {stub}")
    (tmp_path / "b.dsn").write_text("(pcb b)")
    freerouting(tmp_path / "b.dsn", tmp_path / "b.ses", options=["--x=1"])
    args = (tmp_path / "router.py.args").read_text().split("\n")
    assert args[args.index("-mt") + 1] == "1"
    assert "--router.optimizer.max_threads=1" in args
    assert args[-1] == "--x=1"  # the caller's options come last
