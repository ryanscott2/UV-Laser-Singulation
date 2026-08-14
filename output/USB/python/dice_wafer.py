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
  * LASER-PROFILE GATE: after arming, before ANY stage motion, every job is read back
    and its profile checked against the confirmed WinLase settings (power 100 %,
    frequency 30 kHz, mark speed 400 mm/s). Any mismatch aborts the run -- no motion,
    no firing. Each job is re-checked once more at mark time. This script never WRITES
    laser power or frequency; it only reads and verifies them.
  * A countdown precedes the run; pressing a key during the countdown, or between
    stations / between mark passes, aborts (stage controlled-stop `I` + WinLase
    TerminateMark). Mid-pass you cannot interrupt in software -- keep a hand on the
    hardware e-stop. This live-laser path could not be tested off the machine.
  * After a clean armed run the .wlj job files are deleted (rebuild each run); pass
    --keep-jobs to keep them.

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

# Required laser profile -- must match the WinLase "Vector Graphic -> Properties ->
# Profile" the operator confirmed: power 100 %, frequency 30 kHz, mark speed 400 mm/s.
# Before ANY stage motion or firing, every job is read back and checked against these;
# a mismatch aborts the whole run. GetObjProfile index map (same as winlase_build_jobs):
# [0] = mark speed (bits/mSec), [5] = laser power %, [9] = T1 frequency (kHz).
EXPECTED_LASER_POWER_PCT = 100.0
EXPECTED_FREQ_KHZ = 30.0
EXPECTED_MARK_SPEED_MM_S = 400.0
POWER_TOLERANCE_PCT = 0.5
FREQ_TOLERANCE_KHZ = 0.1
SPEED_TOLERANCE_MM_S = 10.0
PROFILE_SPEED_IDX, PROFILE_POWER_IDX, PROFILE_FREQ_IDX = 0, 5, 9

# WinLase marking is ASYNCHRONOUS: MarkAllObj starts a pass and returns; GetBusyStatus
# polls for completion. So we wait for idle before starting a job (drains any prior
# job's tail) and after every pass (so a job fully finishes before it is closed and the
# next one loads -- otherwise closing/loading mid-mark wedges WinLase "busy").
MARK_POLL_S = 0.02           # GetBusyStatus poll interval
MARK_SETTLE_S = 0.1          # let a just-issued mark register as busy before we poll for done
MARK_WAIT_TIMEOUT_S = 120.0  # max wait for one pass (or a job transition) to go idle


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
            from win32com.client import dynamic
        except ImportError as exc:
            raise SystemExit(
                "pywin32 is not installed in this venv, so WinLase COM is unavailable.\n"
                "Install it offline (wheels are in venv\\wheels), then re-run:\n"
                "    pip install --no-index --find-links venv\\wheels pywin32\n"
                "    python venv\\Scripts\\pywin32_postinstall.py -install"
            ) from exc
        # Late/dynamic binding on purpose -- see the note in winlase_build_jobs.py:
        # WinLase's non-retval [out] params break early binding; dynamic auto-returns them.
        self.m = dynamic.Dispatch("Winlase.Automate")
        self.m.AttachToMarker()
        if int(self.m.GetScanCardCount()) < 1:
            raise SystemExit("WinLase reports no scan card; can't mark. Run on the laser PC.")
        self.bits_per_mm = int(self.m.GetLensCalFactor(0, 0))
        if self.bits_per_mm <= 0:
            raise SystemExit("GetLensCalFactor returned <= 0; is a lens cal loaded?")

    def ready(self) -> bool:
        return int(self.m.GetBusyStatus(0)) == 0

    def _wait_not_busy(self, abort, timeout_s: float) -> bool:
        """Poll until WinLase is idle (two consecutive not-busy reads, so a transient 0
        can't be mistaken for done). Returns True when idle, False if aborted mid-wait.
        Raises TimeoutError (after TerminateMark) if it never goes idle in time."""
        t0 = time.time()
        idle_hits = 0
        while True:
            if abort():
                return False
            if self.ready():
                idle_hits += 1
                if idle_hits >= 2:
                    return True
            else:
                idle_hits = 0
            if time.time() - t0 > timeout_s:
                try:
                    self.m.TerminateMark()
                except Exception:
                    pass
                raise TimeoutError("WinLase stayed busy > %.0f s" % timeout_s)
            time.sleep(MARK_POLL_S)

    def _check_active_params(self, label: str):
        """Read every object's profile in the ACTIVE job and compare to the required
        laser settings. Returns a list of human-readable problem strings (empty = OK)."""
        problems = []
        count = int(self.m.GetObjCount())
        if count < 1:
            return ["%s: job holds no objects to verify" % label]
        for obj in range(count):
            prof = list(self.m.GetObjProfile(obj, 0))
            power = float(prof[PROFILE_POWER_IDX])
            freq = float(prof[PROFILE_FREQ_IDX])
            speed = float(prof[PROFILE_SPEED_IDX]) / self.bits_per_mm * 1000.0
            if abs(power - EXPECTED_LASER_POWER_PCT) > POWER_TOLERANCE_PCT:
                problems.append("%s obj %d: laser power %.3f %% (need %.0f %%)"
                                % (label, obj, power, EXPECTED_LASER_POWER_PCT))
            if abs(freq - EXPECTED_FREQ_KHZ) > FREQ_TOLERANCE_KHZ:
                problems.append("%s obj %d: frequency %.2f kHz (need %.2f kHz)"
                                % (label, obj, freq, EXPECTED_FREQ_KHZ))
            if abs(speed - EXPECTED_MARK_SPEED_MM_S) > SPEED_TOLERANCE_MM_S:
                problems.append("%s obj %d: mark speed %.0f mm/s (need %.0f mm/s)"
                                % (label, obj, speed, EXPECTED_MARK_SPEED_MM_S))
        return problems

    def verify_job_params(self, wlj: Path):
        """Load a job read-only, check its laser profile, close it. Returns problems."""
        idx = int(self.m.LoadJobFromFile(str(wlj.resolve())))
        try:
            self.m.SetActiveJob(idx)
            return self._check_active_params(wlj.name)
        finally:
            try:
                self.m.CloseJob(idx)
            except Exception:
                pass

    def mark_job(self, wlj: Path, loops: int, abort) -> bool:
        """Load a job and mark it `loops` times. Returns False if aborted."""
        job_index = int(self.m.LoadJobFromFile(str(wlj.resolve())))
        self.m.SetActiveJob(job_index)
        # Last-instant re-check right before firing (defence in depth on top of the
        # pre-flight gate): never mark a job whose laser profile is not exactly right.
        problems = self._check_active_params(wlj.name)
        if problems:
            try:
                self.m.CloseJob(job_index)
            except Exception:
                pass
            raise RuntimeError("laser profile check failed at mark time:\n  "
                               + "\n  ".join(problems))
        try:
            # Make sure the marker is idle before we start -- this also drains the tail
            # of the previous station's job so loading/closing never collides with a mark.
            if not self._wait_not_busy(abort, MARK_WAIT_TIMEOUT_S):
                self.m.TerminateMark()
                return False
            for i in range(loops):
                if abort():
                    self.m.TerminateMark()
                    return False
                self.m.MarkAllObj(0)          # async: starts this pass, returns immediately
                time.sleep(MARK_SETTLE_S)     # let the mark register as busy before polling
                if not self._wait_not_busy(abort, MARK_WAIT_TIMEOUT_S):  # wait for THIS pass to finish
                    self.m.TerminateMark()
                    return False
        finally:
            try:
                self.m.CloseJob(job_index)    # safe now: the job has fully finished marking
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


def delete_jobs(plan) -> None:
    """Remove the .wlj files this run marked (and the WinLaseJobs folder if it empties).
    They rebuild each run, so nothing is lost -- this just keeps the set folder clean."""
    jobs_dir = None
    removed = 0
    for _label, _pos, wlj in plan:
        jobs_dir = wlj.parent
        try:
            wlj.unlink()
            removed += 1
        except OSError:
            pass
    if jobs_dir is not None:
        try:
            jobs_dir.rmdir()  # only removes it if now empty
        except OSError:
            pass
    print("cleaned up %d job file(s); rebuild for the next run." % removed)


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
    p.add_argument("--keep-jobs", action="store_true",
                   help="keep the .wlj files after an armed run (default: delete them, "
                        "so they regenerate fresh on the next build -- no clutter)")
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
        # Pre-flight laser gate: read every job back and confirm the profile matches the
        # confirmed WinLase settings BEFORE any stage motion or firing. Abort otherwise.
        print("\nverifying laser profile in every job (need power %.0f %%, freq %.2f kHz, "
              "speed %.0f mm/s) ..." % (EXPECTED_LASER_POWER_PCT, EXPECTED_FREQ_KHZ,
                                        EXPECTED_MARK_SPEED_MM_S))
        problems = []
        for _label, _pos, wlj in plan:
            problems.extend(marker.verify_job_params(wlj))
        if problems:
            marker.close()
            print("*** ABORTING: laser parameters do not match the confirmed profile ***")
            for pr in problems:
                print("  " + pr)
            print("Fix the profile in WinLase and rebuild the jobs; no motion, no firing.")
            return 1
        print("  OK -- all jobs match. Safe to arm.")

    stage = OptiScan(args.port)
    print("stage connected on %s: %s" % (stage.port, stage.identity))

    def abort() -> bool:
        return _aborted() or (args.stop_flag is not None and args.stop_flag.exists())

    rc = 0
    completed = False
    try:
        if not countdown(args.countdown, abort):
            return 1
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
        rc = 1
    except (RuntimeError, TimeoutError, ValueError) as exc:
        # A safety/hardware check tripped mid-run (laser-profile mismatch, stage move
        # timeout, WinLase stuck busy, out-of-envelope target). Abort cleanly, no traceback.
        print("\n*** ABORTED: %s ***" % exc)
        rc = 1
    finally:
        try:
            stage.stop()
        except Exception:
            pass
        stage.close()
        if marker is not None:
            marker.stop()
            marker.close()
    # Ephemeral jobs: after a clean armed run, delete the .wlj so they never clutter.
    if completed and args.arm and not args.keep_jobs:
        delete_jobs(plan)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
