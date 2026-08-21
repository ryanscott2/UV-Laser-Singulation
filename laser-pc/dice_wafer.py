"""One-button wafer dicing: OptiScan III stage + WinLase Pro, fully sequenced.

For each station P1..P4 it moves the stage to the taught position, (optionally) sets
focus, then marks that station's pre-built WinLase job. The jig stays put; the stage
indexes the wafer under the fixed field, so stage position i lines up with job i.

Pipeline it ties together:
  1. laser-pc/winlase_build_jobs.py  -> builds <set>/WinLaseJobs/<set>_P1..P4.wlj
  2. laser-pc/optiscan.py jog        -> teaches laser-pc/optiscan_positions.json (P1..P4)
  3. THIS script                  -> move -> (focus) -> mark, P1->P2->P3->P4

SAFETY -- this can fire the laser, so it is gated:
  * Default is SIMULATE: real stage moves, but marking is faked (a short dwell).
    Run it this way first to prove the motion and sequencing with NO laser.
  * Pass --arm to actually load and mark jobs through WinLase.
  * LASER-PROFILE GATE: after arming, before ANY stage motion, every job is read back
    and its profile checked against the confirmed WinLase settings (power 100 %,
    frequency 30 kHz, mark speed 100 mm/s). Any mismatch aborts the run -- no motion,
    no firing. Each job is re-checked once more at mark time. This script never WRITES
    laser power or frequency; it only reads and verifies them.
  * A countdown precedes the run; pressing a key during the countdown, or between
    stations / between mark passes, aborts (stage controlled-stop `I` + WinLase
    TerminateMark). Mid-pass you cannot interrupt in software -- keep a hand on the
    hardware e-stop. This live-laser path could not be tested off the machine.
  * The built .wlj job files are KEPT after a run, so a set can be re-marked without
    rebuilding through WinLase; pass --delete-jobs to remove them after a clean armed run.

WinLase note: the WinLase GUI and the COM server can't both hold the marker library,
so CLOSE the WinLase GUI before an armed run. Python 3.8, no network; serial via
pyserial-or-pywin32 (see optiscan.py), WinLase via pywin32 (win32com).

    python laser-pc/dice_wafer.py output/DXFs/081326_AlignmentTest_v2                 # SIMULATE
    python laser-pc/dice_wafer.py output/DXFs/081326_AlignmentTest_v2 --list          # show plan only
    python laser-pc/dice_wafer.py output/DXFs/081326_AlignmentTest_v2 --arm           # LIVE laser
    python laser-pc/dice_wafer.py <set> --arm --home-after     # passes from dice_passes.csv (or --passes N)
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

from optiscan import OptiScan  # same laser-pc/ dir

STATION_ORDER = ("P1", "P2", "P3", "P4")
DEFAULT_PASSES = 175
# Usable stage window (absolute um) after the 2026-08 re-datum; keep in sync with
# dice_ui.REACHABLE_UM and the exposure exposure_calibration.json reachable_um. Used to reject
# stale / out-of-datum taught stations BEFORE any motion (a stale old-datum P1 has negative X,
# unreachable on this datum -> the stage silently fails to move X).
# -Y floor is -38140 (NOT the -57210 hard stop): the stage hits a PIPE at the back past that,
# so clamping here protects the hardware and improves alignment. Keep in sync across repos + optiscan.
REACHABLE_UM = {"x_min": 16236, "x_max": 138529, "y_min": -38140, "y_max": 0}
DEFAULT_PASSES_FILE = Path(__file__).resolve().parent / "dice_passes.csv"
DEFAULT_COUNTDOWN_S = 10

# Required laser profile -- must match the WinLase "Vector Graphic -> Properties ->
# Profile" the operator confirmed: power 100 %, frequency 30 kHz, mark speed 100 mm/s.
# Before ANY stage motion or firing, every job is read back and checked against these;
# a mismatch aborts the whole run. GetObjProfile index map (same as winlase_build_jobs):
# [0] = mark speed (bits/mSec), [5] = laser power %, [9] = T1 frequency (kHz).
EXPECTED_LASER_POWER_PCT = 100.0
EXPECTED_FREQ_KHZ = 30.0
EXPECTED_MARK_SPEED_MM_S = 100.0
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

# Time-estimate (ETA): empirical, measured live. Emitted as "[eta] ..." lines that the
# launcher UI mirrors into its Est. time field. A small per-set cache warm-starts it so a
# repeat run shows a number from t=0. Cosmetic only -- never affects motion or firing.
ETA_LOG_INTERVAL_S = 15.0    # min seconds between [eta] progress lines
DEFAULT_MOVE_S = 8.0         # rough stage-move guess until a real move is timed
DEFAULT_ETA_CACHE = Path(__file__).resolve().parent / ".dice_eta.json"


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

    def mark_job(self, wlj: Path, loops: int, abort, on_pass=None) -> bool:
        """Load a job and mark it `loops` times. Returns False if aborted.

        `on_pass(i, dt)`, if given, is called after each pass with its index and measured
        wall-clock seconds (trigger -> idle), for the live time estimate. It is best-effort:
        an exception in it is swallowed so a cosmetic estimate can never abort a mark."""
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
                t_pass = time.time()
                self.m.MarkAllObj(0)          # async: starts this pass, returns immediately
                time.sleep(MARK_SETTLE_S)     # let the mark register as busy before polling
                if not self._wait_not_busy(abort, MARK_WAIT_TIMEOUT_S):  # wait for THIS pass to finish
                    self.m.TerminateMark()
                    return False
                if on_pass is not None:
                    try:
                        on_pass(i, time.time() - t_pass)
                    except Exception:
                        pass                  # ETA is cosmetic; never let it break a mark
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


# ------------------------------------------------------------------ time estimate
def _fmt_dur(seconds: float) -> str:
    seconds = int(round(max(0.0, seconds)))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return "%d:%02d:%02d" % (h, m, s) if h else "%d:%02d" % (m, s)


def load_eta_cache(path: Path, set_name: str) -> dict:
    """Warm-start per-pass/move seconds for a set from a prior armed run. Returns {} for
    a missing, unreadable, or malformed cache -- every shape is validated, so a bad or
    hand-edited .dice_eta.json can never raise into (and abort) a dicing run."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        entry = data.get(set_name)
        if not isinstance(entry, dict):
            return {}
        warm = {}
        per_pass = entry.get("per_pass")
        if isinstance(per_pass, dict):
            for k, v in per_pass.items():
                if isinstance(v, (int, float)):
                    warm[str(k)] = float(v)
        if isinstance(entry.get("move"), (int, float)):
            warm["move"] = float(entry["move"])
        return warm
    except (OSError, ValueError, TypeError):
        return {}


def save_eta_cache(path: Path, set_name: str, per_pass: dict, move_s) -> None:
    """Persist this run's measured pace so the next run of the same set estimates from
    t=0. Best-effort: any failure is swallowed (an ETA cache is never worth an error)."""
    try:
        data = {}
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                data = {}
        if not isinstance(data, dict):   # a valid-but-non-object file must not crash the write
            data = {}
        entry = {"per_pass": {k: round(v, 3) for k, v in per_pass.items() if v is not None}}
        if move_s is not None:
            entry["move"] = round(move_s, 3)
        entry["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        data[set_name] = entry
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except (OSError, ValueError, TypeError):
        pass


class EtaTracker:
    """Live, empirical time estimate for a dicing run.

    Every mark pass of a station reloads the same job, so its wall-clock time is
    near-constant; we measure it (and each stage move) and extrapolate over the
    remaining passes and stations. No geometry, no machine constants -- just measured
    pace, refined as the run proceeds, so the estimate captures galvo jumps, fill,
    settle and poll overhead that a computed model cannot reach. A per-set cache
    warm-starts it. Estimates are marked '~' and are best-effort.
    """

    def __init__(self, labels, passes, warm=None, final_move=False, emit=print):
        self.labels = list(labels)
        self.passes = int(passes)
        self.warm = dict(warm or {})
        self.final_move = bool(final_move)
        self.emit = emit
        self.per_pass = {label: [] for label in self.labels}
        self.moves = []
        self.run_t0 = None
        self.cur_idx = 0
        self.cur_pass = 0
        self._last_emit = 0.0

    # -- measurement --------------------------------------------------------
    def start(self):
        self.run_t0 = time.time()

    def record_move(self, seconds):
        self.moves.append(float(seconds))

    def on_station_start(self, idx, label):
        self.cur_idx = idx
        self.cur_pass = 0
        self._maybe_emit(force=True)

    def on_pass(self, idx, label, pass_i, dt):
        self.cur_idx = idx
        self.cur_pass = pass_i + 1
        self.per_pass[label].append(float(dt))
        # Refresh on the first real sample of a station (the estimate sharpens there).
        self._maybe_emit(force=(len(self.per_pass[label]) == 1))

    # -- estimation ---------------------------------------------------------
    def _move_est(self):
        if self.moves:
            return sum(self.moves) / len(self.moves)
        return self.warm.get("move", DEFAULT_MOVE_S)

    def _per_pass_est(self, label):
        vals = self.per_pass.get(label, [])
        if len(vals) >= 2:
            return sum(vals[1:]) / len(vals[1:])   # drop the cold-start first pass
        if len(vals) == 1:
            return vals[0]
        if label in self.warm:
            return self.warm[label]
        measured = [v for lst in self.per_pass.values() for v in lst]
        if measured:
            return sum(measured) / len(measured)
        warm_vals = [self.warm[l] for l in self.labels if l in self.warm]
        if warm_vals:
            return sum(warm_vals) / len(warm_vals)
        return None

    def _remaining(self):
        known = True
        total = 0.0
        cur = self._per_pass_est(self.labels[self.cur_idx])
        if cur is None:
            known, cur = False, 0.0
        total += max(0, self.passes - self.cur_pass) * cur
        for idx in range(self.cur_idx + 1, len(self.labels)):
            est = self._per_pass_est(self.labels[idx])
            if est is None:
                known, est = False, 0.0
            total += self.passes * est
        remaining_moves = (len(self.labels) - 1 - self.cur_idx) + (1 if self.final_move else 0)
        total += max(0, remaining_moves) * self._move_est()
        return total, known

    def per_pass_means(self):
        out = {}
        for label in self.labels:
            vals = self.per_pass[label]
            if len(vals) >= 2:
                out[label] = sum(vals[1:]) / len(vals[1:])
            elif vals:
                out[label] = vals[0]
        return out

    def move_mean(self):
        return (sum(self.moves) / len(self.moves)) if self.moves else None

    # -- output -------------------------------------------------------------
    def preview(self):
        total = 0.0
        for label in self.labels:
            pp = self.warm.get(label)
            if pp is None:
                return
            total += self.passes * pp
        moves = len(self.labels) + (1 if self.final_move else 0)
        total += moves * self._move_est()
        self.emit("[eta] estimated total ~%s (%d passes/station, from this set's last armed run)"
                  % (_fmt_dur(total), self.passes))

    def _maybe_emit(self, force):
        now = time.time()
        if not force and (now - self._last_emit) < ETA_LOG_INTERVAL_S:
            return
        self._last_emit = now
        elapsed = now - (self.run_t0 or now)
        remaining, known = self._remaining()
        done = sum(len(v) for v in self.per_pass.values())
        total_passes = self.passes * len(self.labels)
        label = self.labels[self.cur_idx]
        if known:
            tail = "remaining ~%s | total ~%s" % (_fmt_dur(remaining), _fmt_dur(elapsed + remaining))
        else:
            tail = "remaining estimating..."
        self.emit("[eta] elapsed %s | %s (%d/%d) pass %d/%d | %d/%d passes | %s"
                  % (_fmt_dur(elapsed), label, self.cur_idx + 1, len(self.labels),
                     self.cur_pass, self.passes, done, total_passes, tail))

    def finish(self):
        elapsed = time.time() - (self.run_t0 or time.time())
        self.emit("[eta] done | total elapsed %s" % _fmt_dur(elapsed))


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
    p.add_argument("--redatum", choices=["off", "row", "move"], default="off",
                   help="re-establish the stage datum with RIS to stop an open-loop run from "
                        "accumulating drift: 'move'=before every station, 'row'=before the first "
                        "station only (dicing is a flat P1..P4 list, no rows), 'off'=never "
                        "(default). RIS drives to the hard limits, so keep the full-travel path "
                        "clear; only as accurate as the limit-switch repeatability -- qualify "
                        "that first. Runs in dry-run too (stage-only, no laser).")
    p.add_argument("--countdown", type=int, default=DEFAULT_COUNTDOWN_S)
    p.add_argument("--home-after", action="store_true", help="return stage to 0,0 when done")
    p.add_argument("--extract-after", action="store_true",
                   help="when done, move the stage to the P3 station (front-right) to unload")
    p.add_argument("--delete-jobs", action="store_true",
                   help="delete the .wlj files after a clean armed run (default: KEEP them, "
                        "so a set can be re-marked without rebuilding through WinLase)")
    p.add_argument("--keep-jobs", action="store_true", help=argparse.SUPPRESS)  # deprecated no-op: keeping is the default now
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

    # Pre-flight reachability: refuse if any TAUGHT station is outside the usable stage window.
    # Catches stale positions from a prior datum (e.g. old P1 with negative X, unreachable on
    # the re-datumed rig) that otherwise fail silently as "X won't move". Re-teach for this datum.
    R = REACHABLE_UM
    oob = [(label, pos["x"], pos["y"]) for label, pos, _w in plan
           if not (R["x_min"] <= pos["x"] <= R["x_max"] and R["y_min"] <= pos["y"] <= R["y_max"])]
    if oob:
        print("\n*** REFUSING TO RUN: taught station(s) outside the usable stage window "
              "X[%d,%d] Y[%d,%d]. Re-teach P1-P4 for this datum: `python optiscan.py jog`. ***"
              % (R["x_min"], R["x_max"], R["y_min"], R["y_max"]))
        for label, x, y in oob:
            print("    %s taught at X=%d Y=%d (out of window)" % (label, x, y))
        return 1

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
    eta = None
    try:
        # Time estimate: warm-start from this set's last armed run if we have it. Kept
        # inside the try so any surprise here still reaches the stage/marker cleanup in
        # `finally` below rather than leaking open hardware handles.
        warm = load_eta_cache(DEFAULT_ETA_CACHE, args.set_dir.name)
        eta = EtaTracker(STATION_ORDER, passes, warm=warm,
                         final_move=(args.home_after or args.extract_after))
        if warm:
            eta.preview()
        elif not args.arm:
            print("[eta] no timing history for %s yet -- run --arm once to record it."
                  % args.set_dir.name)
        if not countdown(args.countdown, abort):
            return 1
        eta.start()
        for idx, (label, pos, wlj) in enumerate(plan):
            # Re-datum cadence (RIS) to stop the open-loop stage accumulating drift: 'move' at
            # every station, 'row' at the first only (the plan is a flat P1..P4 list). MOVE
            # FIRST, then RIS, then re-command the target: RIS drives to the hard limits and
            # RETURNS to its pre-RIS position (the target we just moved to), re-referencing the
            # datum there, so the final goto is a short, consistent datum->target correction in
            # the freshly restored frame. RIS drives full travel (path must be clear); a failure
            # is a controlled stop -- never fire on an unverified datum.
            do_ris = (args.redatum == "move" or (args.redatum == "row" and idx == 0))
            print("\n[%s] move -> X=%d Y=%d" % (label, pos["x"], pos["y"]))
            move_t0 = time.time()
            stage.goto(pos["x"], pos["y"])                 # move to the target FIRST
            if do_ris:
                print("[redatum] RIS at %s (restoring index at the hard limits) ..." % label)
                try:
                    rx, ry = stage.redatum()
                except (RuntimeError, TimeoutError, ValueError) as exc:
                    print("*** re-datum (RIS) FAILED at %s: %s -- controlled stop, "
                          "not firing. ***" % (label, exc))
                    break
                print("[redatum] datum restored; stage reads X=%d Y=%d" % (rx, ry))
                if abort():
                    print("aborted after re-datum, before re-seating %s." % label)
                    break
                stage.goto(pos["x"], pos["y"])             # re-seat in the fresh datum frame
            if args.focus and "z" in pos:
                stage.goto_z(pos["z"])
            eta.record_move(time.time() - move_t0)
            if abort():
                print("aborted before marking %s." % label)
                break
            eta.on_station_start(idx, label)
            if args.arm:
                print("[%s] marking %s x%d ..." % (label, wlj.name, passes))
                if not marker.mark_job(
                        wlj, passes, abort,
                        on_pass=lambda i, dt, _i=idx, _l=label: eta.on_pass(_i, _l, i, dt)):
                    print("aborted during %s." % label)
                    break
            else:
                print("[%s] SIMULATE mark %s x%d (no laser)" % (label, wlj.name, passes))
                time.sleep(1.0)
            print("[%s] done." % label)
        else:
            print("\nAll stations complete.")
            completed = True
            eta.finish()
        # Only move the stage after a CLEAN run -- never drive it right after an abort.
        if completed:
            if args.home_after:
                print("returning stage to 0,0 ...")
                stage.goto(0, 0)
            elif args.extract_after:
                p3 = next((pos for label, pos, _w in plan if label == "P3"), None)
                if p3 is None:
                    print("extract requested but P3 is not taught; leaving the stage put.")
                else:
                    print("extract: moving stage to P3 (front-right) X=%d Y=%d ..."
                          % (p3["x"], p3["y"]))
                    stage.goto(int(p3["x"]), int(p3["y"]))
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
    # Jobs are KEPT by default so a set can be re-marked without a rebuild; only a clean
    # armed run with an explicit --delete-jobs removes them (--keep-jobs is a legacy no-op).
    if completed and args.arm and args.delete_jobs:
        delete_jobs(plan)
    # Record this run's measured pace so the next run of this set estimates from t=0.
    if completed and args.arm and eta is not None:
        save_eta_cache(DEFAULT_ETA_CACHE, args.set_dir.name,
                       eta.per_pass_means(), eta.move_mean())
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
