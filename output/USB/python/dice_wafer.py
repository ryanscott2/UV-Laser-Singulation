"""One-button wafer dicing: OptiScan III stage + WinLase Pro, fully sequenced.

For each station P1..P4 it moves the stage to the taught position, (optionally) sets
focus, then marks that station's pre-built WinLase job. The jig stays put; the stage
indexes the wafer under the fixed field, so stage position i lines up with job i.

Pipeline it ties together:
  1. tools/winlase_build_jobs.py  -> builds <set>/WinLaseJobs/<set>_P1..P4.wlj
  2. tools/optiscan.py jog        -> teaches tools/optiscan_positions.json (P1..P4)
  3. THIS script                  -> move -> (focus) -> mark, P1->P2->P3->P4

SAFETY -- this can fire the laser, so it is gated:
  * Default is SIMULATE: real stage moves, but marking is faked (a short dwell).
    Run it this way first to prove the motion and sequencing with NO laser.
  * Pass --arm to actually load and mark jobs through WinLase.
  * A countdown precedes the run; pressing a key during the countdown, or between
    stations / between mark passes, aborts (stage controlled-stop `I` + WinLase
    TerminateMark). Mid-pass you cannot interrupt in software -- keep a hand on the
    hardware e-stop. This live-laser path could not be tested off the machine.

WinLase note: the WinLase GUI and the COM server can't both hold the marker library,
so CLOSE the WinLase GUI before an armed run. Python 3.8, no network; serial via
pyserial-or-pywin32 (see optiscan.py), WinLase via pywin32 (win32com).

    python tools/dice_wafer.py output/DXFs/081326_AlignmentTest_v2                 # SIMULATE
    python tools/dice_wafer.py output/DXFs/081326_AlignmentTest_v2 --list          # show plan only
    python tools/dice_wafer.py output/DXFs/081326_AlignmentTest_v2 --arm           # LIVE laser
    python tools/dice_wafer.py <set> --arm --home-after     # passes from dice_passes.csv (or --passes N)
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

from optiscan import OptiScan  # same tools/ dir

STATION_ORDER = ("P1", "P2", "P3", "P4")
DEFAULT_PASSES = 175
DEFAULT_PASSES_FILE = Path(__file__).resolve().parent / "dice_passes.csv"
DEFAULT_COUNTDOWN_S = 10


def _aborted() -> bool:
    """True if a key was pressed (non-blocking), on Windows."""
    try:
        import msvcrt
    except ImportError:
        return False
    if msvcrt.kbhit():
        msvcrt.getch()
        return True
    return False


# ------------------------------------------------------------------- WinLase COM
class WinLaseMarker:
    """Loads and marks pre-built .wlj jobs through the WinLase automation server."""

    def __init__(self):
        try:
            from win32com.client import Dispatch, gencache
        except ImportError as exc:
            raise SystemExit(
                "pywin32 is not installed in this venv, so WinLase COM is unavailable.\n"
                "Install it offline (wheels are in venv\\wheels), then re-run:\n"
                "    pip install --no-index --find-links venv\\wheels pywin32\n"
                "    python venv\\Scripts\\pywin32_postinstall.py -install"
            ) from exc
        try:
            self.m = gencache.EnsureDispatch("Winlase.Automate")
        except Exception:
            self.m = Dispatch("Winlase.Automate")
        self.m.AttachToMarker()
        if int(self.m.GetScanCardCount()) < 1:
            raise SystemExit("WinLase reports no scan card; can't mark. Run on the laser PC.")

    def ready(self) -> bool:
        return int(self.m.GetBusyStatus(0)) == 0

    def mark_job(self, wlj: Path, loops: int, abort) -> bool:
        """Load a job and mark it `loops` times. Returns False if aborted."""
        job_index = int(self.m.LoadJobFromFile(str(wlj.resolve())))
        self.m.SetActiveJob(job_index)
        try:
            for i in range(loops):
                if abort():
                    self.m.TerminateMark()
                    return False
                t0 = time.time()
                while not self.ready():
                    if time.time() - t0 > 30:
                        self.m.TerminateMark()
                        raise TimeoutError("WinLase stayed busy >30 s before pass %d" % (i + 1))
                    time.sleep(0.02)
                self.m.MarkAllObj(0)   # blocks until this pass finishes
        finally:
            try:
                self.m.CloseJob(job_index)
            except Exception:
                pass
        return True

    def stop(self) -> None:
        try:
            self.m.TerminateMark()
        except Exception:
            pass

    def close(self) -> None:
        try:
            self.m.ReleaseMarker()
        except Exception:
            pass


# --------------------------------------------------------------------- planning
def load_plan(set_dir: Path, positions_path: Path):
    if not positions_path.is_file():
        raise SystemExit("No taught positions at %s -- run `optiscan.py jog` first." % positions_path)
    data = json.loads(positions_path.read_text(encoding="utf-8"))
    stations = data.get("stations", {})
    jobs_dir = set_dir / "WinLaseJobs"
    plan = []
    for label in STATION_ORDER:
        if label not in stations:
            raise SystemExit("Position %s missing from %s; teach all four." % (label, positions_path))
        wlj = jobs_dir / ("%s_%s.wlj" % (set_dir.name, label))
        if not wlj.is_file():
            raise SystemExit("Job not found: %s -- run winlase_build_jobs.py for this set." % wlj)
        plan.append((label, stations[label], wlj))
    return plan


def load_passes(csv_path: Path, set_name: str, default: int):
    """Mark passes per station for a set, from a CSV of `set,passes` rows.

    Exact set-folder match wins; else a 'default' row; else `default`. Blank lines,
    '#' comments, and a 'set,passes' header are ignored. Returns (passes, source).
    """
    table = {}
    if csv_path.is_file():
        with csv_path.open(newline="", encoding="utf-8") as stream:
            for row in csv.reader(stream):
                if len(row) < 2 or not row[0].strip() or row[0].lstrip().startswith("#"):
                    continue
                key, value = row[0].strip(), row[1].strip()
                if key.lower() in ("set", "name"):
                    continue
                try:
                    table[key] = int(value)
                except ValueError:
                    pass
    if set_name in table:
        return table[set_name], "%s in %s" % (set_name, csv_path.name)
    if "default" in table:
        return table["default"], "default in %s" % csv_path.name
    return default, "built-in default (%d)" % default


def print_plan(set_dir: Path, plan, passes: int, focus: bool, armed: bool) -> None:
    print("\nDicing plan for %s   [%s, %d passes/station%s]" % (
        set_dir.name, "ARMED - LASER LIVE" if armed else "SIMULATE - no laser",
        passes, ", focus on" if focus else ""))
    for label, pos, wlj in plan:
        z = ("  Z=%d" % pos["z"]) if (focus and "z" in pos) else ""
        print("  %s  ->  X=%-8d Y=%-8d%s   mark %s" % (
            label, pos["x"], pos["y"], z, wlj.name))


# ------------------------------------------------------------------------- run
def countdown(seconds: int, should_abort) -> bool:
    """Abortable countdown. Returns True to proceed, False if aborted."""
    print("\nStarting in %d s -- press any key (or the UI Stop) to ABORT." % seconds)
    for n in range(seconds, 0, -1):
        sys.stdout.write("\r  %2d ... " % n)
        sys.stdout.flush()
        end = time.time() + 1.0
        while time.time() < end:
            if should_abort():
                print("\naborted at countdown.")
                return False
            time.sleep(0.05)
    print("\r  go.      ")
    return True


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("set_dir", type=Path, help="built set directory (has WinLaseJobs/)")
    p.add_argument("--positions", type=Path,
                   default=Path(__file__).resolve().parent / "optiscan_positions.json")
    p.add_argument("--port", default="COM5")
    p.add_argument("--passes", type=int, default=None,
                   help="mark passes per station; overrides dice_passes.csv for this run")
    p.add_argument("--passes-file", type=Path, default=DEFAULT_PASSES_FILE,
                   help="CSV of 'set,passes' rows (default: dice_passes.csv next to this script)")
    p.add_argument("--arm", action="store_true", help="ACTUALLY fire the laser (default: simulate)")
    p.add_argument("--focus", action="store_true", help="set Z from taught positions (needs motor)")
    p.add_argument("--countdown", type=int, default=DEFAULT_COUNTDOWN_S)
    p.add_argument("--home-after", action="store_true", help="return stage to 0,0 when done")
    p.add_argument("--list", action="store_true", help="print the plan and exit (no motion)")
    p.add_argument("--yes", action="store_true",
                   help="skip the 'type DICE' arm prompt (the UI confirms instead)")
    p.add_argument("--stop-flag", type=Path, default=None,
                   help="do a controlled stop if this file appears -- how the UI signals Stop")
    args = p.parse_args()

    if args.passes is not None:
        passes, passes_src = args.passes, "--passes"
    else:
        passes, passes_src = load_passes(args.passes_file, args.set_dir.name, DEFAULT_PASSES)

    plan = load_plan(args.set_dir, args.positions)
    print("passes per station: %d  [%s]" % (passes, passes_src))
    print_plan(args.set_dir, plan, passes, args.focus, args.arm)
    if args.list:
        return 0

    marker = None
    if args.arm:
        print("\n*** ARMED: the laser will fire. Close the WinLase GUI. Hand on e-stop. ***")
        if not args.yes and input('type "DICE" to arm: ').strip() != "DICE":
            print("not armed; exiting.")
            return 1
        marker = WinLaseMarker()
        if not marker.ready():
            marker.close()
            raise SystemExit("WinLase busy at start; aborting.")

    stage = OptiScan(args.port)
    print("stage connected on %s: %s" % (stage.port, stage.identity))

    def abort() -> bool:
        return _aborted() or (args.stop_flag is not None and args.stop_flag.exists())

    try:
        if not countdown(args.countdown, abort):
            return 1
        completed = False
        for label, pos, wlj in plan:
            print("\n[%s] move -> X=%d Y=%d" % (label, pos["x"], pos["y"]))
            stage.goto(pos["x"], pos["y"])
            if args.focus and "z" in pos:
                stage.goto_z(pos["z"])
            if abort():
                print("aborted before marking %s." % label)
                break
            if args.arm:
                print("[%s] marking %s x%d ..." % (label, wlj.name, passes))
                if not marker.mark_job(wlj, passes, abort):
                    print("aborted during %s." % label)
                    break
            else:
                print("[%s] SIMULATE mark %s x%d (no laser)" % (label, wlj.name, passes))
                time.sleep(1.0)
            print("[%s] done." % label)
        else:
            print("\nAll stations complete.")
            completed = True
        # Only auto-home after a clean run -- never drive the stage right after an abort.
        if args.home_after and completed:
            print("returning stage to 0,0 ...")
            stage.goto(0, 0)
    except KeyboardInterrupt:
        print("\ninterrupted -- stopping stage and mark.")
    finally:
        try:
            stage.stop()
        except Exception:
            pass
        stage.close()
        if marker is not None:
            marker.stop()
            marker.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
