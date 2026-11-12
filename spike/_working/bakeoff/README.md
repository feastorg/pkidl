# Router bake-off harness

The scripts behind `../07-router-bakeoff.md` (plan: `../../_planning/04-router-bakeoff.md`), kept as they were run on 2026-11-10. They are evidence, not maintained code: `spike/pyproject.toml` leaves `_working/` out of ruff and pyright.

## They do not run from here

Each script finds its inputs beside itself (`HERE = Path(__file__).resolve().parent`). They ran from `build/bakeoff/`, which also held:

- `boards/`: the DSN and KiCad board for each case;
- `results/<router>/<board>/run<k>/`: each run's SES, log and `result.json`;
- `drc/`: boards assembled for KiCad's DRC;
- `fastroute/`, `rpmroute/`, `openpcb/`, `copperline/`: each candidate cloned and built from a pinned commit.

`assemble.py` also reads the project and rules of our own boards from the directory above, `build/<board>/`.

None of that is kept. The external boards keep their own licences and were never committed; the candidates are re-clonable at the commits `../07-router-bakeoff.md` names. To re-run, copy the scripts into a directory laid out that way.

## The files

| File | What it does |
| --- | --- |
| `runner.py` | Runs every router on every board twice, capped at 600 s a run |
| `smoke.py` | `runner.py` as first tried: one run a board, without `fastroute-default` |
| `evaluate.py` | Reads the results and prints `results.tsv` |
| `connectivity.py` | The independent count: which pads of each net a SES leaves unconnected |
| `assemble.py` | Puts a router's SES onto its board, for KiCad's DRC |
| `kicad_gaps.py` | Splits a DRC report's unconnected items into pad-to-pad gaps and ones with a via end |
| `zone_nets.py` | Prints the nets that have zones in a board |
| `pieces.py` | Fill pieces per net and layer on a filled board, with areas |
| `results.tsv` | `evaluate.py`'s output: one row per router and board |

## `repro/`

The reproduction behind candidate report 1 in `../07-router-bakeoff.md`: Freerouting 2.5.0 counts a fixed via inside a plane of its own net as a clearance violation when `plane_as_obstacle` is on.

| File | What it is |
| --- | --- |
| `via-in-plane.dsn` | One GND plane, two GND pads, one fixed GND via inside the plane |
| `via-outside-plane.dsn` | The same with the plane shrunk so the via is outside it |
| `via-foreign-in-plane.dsn` | The same as the first with the via on another net, `SIG` |
| `log-on.txt` | `via-in-plane.dsn` with the flag on: `ObstacleArea#2 [net GND] <-> FixedVia#5 [net GND]` before routing |
| `log-off.txt` | `via-in-plane.dsn` with the flag off: 0 violations |
| `log-outside.txt` | `via-outside-plane.dsn`: no violation in the loaded design |

`log-outside.txt` ends with "0 unrouted and 2 violations" after routing: with the plane shrunk, the two pads are no longer joined by it, and Freerouting routes them. Those two were not looked into.

The logs name the directory they ran in, which no longer exists. The run of `via-foreign-in-plane.dsn` on the `master` snapshot is recorded in the note; its log was not kept.

A board from copperline's own fixtures sat beside these and is not copied here. It is that project's file, and the project has no licence file.
