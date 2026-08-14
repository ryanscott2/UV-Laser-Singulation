"""Build WinLase Pro jobs from a built pin-grid set: 4 jobs per wafer.

For each station folder (P1..P4) in a set, this creates ONE WinLase job holding both
the station's `Horizontal.dxf` (parallel fill @ 0 deg) and `Vertical.dxf` (fill @ 90
deg), positions each at its true field coordinates (the DXF origin is the field
center -- auto-centering stays effectively OFF), sets the 0.01 mm fill spacing, one
pass, mark-fill on / outline off, and saves a `.wlj`. That replaces the per-file drag,
drop, and settings the operator does 8 times a wafer with a single command.

It drives WinLase Professional's COM Automation server -- `CreateObject("Winlase.
Automate")`, the `IAutomate` interface documented in the *WinLase Automation Server
Reference Manual* (Lanmark Controls, Rev 8.8). The functions used, with their manual
signatures:

    AttachToMarker() / ReleaseMarker()
    GetScanCardCount() -> count
    GetLensCalFactor(card, head) -> bits/mm            (converts mm <-> field bits)
    GetDefaultProfile(profileIndex) -> (Mode, PassCount, MarkSpeed, ... )  [read-only here]
    NewJob(fileName) -> jobIndex
    NewVectorGraphic(objName, fileName) -> objIndex    (imports *.dxf directly)
    GetObjRect(objIndex) -> (Left, Top, Right, Bottom) in field bits
    OffsetObj(objIndex, dxBits, dyBits)
    SetObjFill(objIndex, spacingBits, slope1Deg, slope2Deg, style)   style 0 = parallel
    SetObjMarkFillFlag(objIndex, 1) / SetObjMarkOutlineFlag(objIndex, 0)
    SetObjNumPasses(objIndex, 1)
    IsObjOutOfBounds(objIndex) -> flag
    GetObjCount() -> count
    SaveJobToFile(fileName, appVersion, date, appName, company)
    CloseJob(jobIndex)

The field is a Cartesian grid in "bits": (0,0) at the field center, +/-32768 at the
corners. GetLensCalFactor gives bits/mm for the loaded lens, so a mark at X mm lands
at round(X * bits_per_mm) bits. Placement here is defensive: after each import it
reads the object's actual rect and OFFSETS it so the object's center matches the
DXF's own (field-centered) bounding-box center -- correct whether the import
preserved coordinates or auto-centered the graphic.

RUN THIS ON THE LASER PC. It needs WinLase Pro + its dongle + a scan card + a loaded
lens cal. Close the WinLase GUI first: the GUI and the automation server cannot hold
the marker library at the same time. This script only BUILDS and SAVES jobs -- it
never downloads or marks.

NOT automated (do these in the GUI, once per job, per OPERATING_PROCEDURE.md sec 3):
  - Job loop 175x  (a run-time execution setting, not stored geometry)
  - Z / table height, jig re-seat between stations, and the actual mark.
This script sets the mark speed to 400 mm/s (the WinLase default profile is 1000 mm/s)
by writing ONLY the speed field of Profile 0: it reads the profile, changes the speed,
writes it back, then reads it again and verifies laser power and frequency are unchanged
(aborting the build if not). It never sets laser power or frequency itself; those, the
delays, and jump settings all come from WinLase's default profile.

Usage:
    python tools/winlase_build_jobs.py output/DXFs/081326_AlignmentTest_v2
    python tools/winlase_build_jobs.py output/DXFs/081326_AlignmentTest_v2 --dry-run
    python tools/winlase_build_jobs.py <set> --verify   # build P1 in memory, report
                                                         # placement, do not save
    python tools/winlase_build_jobs.py <setA> <setB> ... # several wafers at once
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

# --- Settings from OPERATING_PROCEDURE.md section 3 -------------------------------
FILL_SPACING_MM = 0.01
FILL_STYLE_PARALLEL = 0            # SetObjFill style: 0 = parallel lines
FILL_ANGLE_DEG = {"Horizontal": 0, "Vertical": 90}   # 0 deg for H cuts, 90 for V
NUM_PASSES = 1
MARK_SPEED_MM_S = 400.0            # written onto Profile 0 (WinLase default profile is 1000 mm/s);
SPEED_TOLERANCE_MM_S = 10.0        # ONLY the speed is written -- power/frequency are verified unchanged
JOB_LOOP_COUNT = 175               # informational only; the real loop count is per set (dice_passes.csv)

ORIENTATIONS = ("Horizontal", "Vertical")
STATION_FOLDERS = ("P1", "P2", "P3", "P4")
FIELD_BIT_LIMIT = 32768            # +/- field half in bits

APP_NAME = "pin-grid winlase_build_jobs"
APP_VERSION = "1.0"
COMPANY = "Stanford UV Laser Singulation"


# --- DXF bounds (dependency-free; the laser PC need not have klayout) -------------
def dxf_bounds_mm(path: Path) -> tuple[float, float, float, float]:
    """Return (xmin, ymin, xmax, ymax) in mm over the ENTITIES section.

    These klayout/ezdxf files carry each mark as a closed LWPOLYLINE whose vertices
    are group code 10 (x) / 20 (y) pairs, in mm. The header's $EXTMIN/$EXTMAX are
    left as sentinels, so the extents are read straight off the vertices. Only the
    ENTITIES section is scanned; later sections (OBJECTS, etc.) also carry 10/20
    codes and would corrupt the box.
    """
    lines = [ln.strip() for ln in path.read_text(errors="strict").splitlines()]
    # DXF is strict code/value pairs on alternating lines.
    pairs = list(zip(lines[0::2], lines[1::2]))
    xs: list[float] = []
    ys: list[float] = []
    in_entities = False
    for code, value in pairs:
        if value == "ENTITIES":
            in_entities = True
            continue
        if in_entities and value == "ENDSEC":
            break
        if not in_entities:
            continue
        if code == "10":
            xs.append(float(value))
        elif code == "20":
            ys.append(float(value))
    if not xs or not ys:
        raise ValueError(f"No LWPOLYLINE vertices found in {path}")
    return min(xs), min(ys), max(xs), max(ys)


# --- Job discovery ----------------------------------------------------------------
def read_jig_stations(set_dir: Path) -> dict[str, str]:
    manifest = set_dir / "position_manifest.csv"
    labels: dict[str, str] = {}
    if manifest.is_file():
        with manifest.open(newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                labels[row["folder"]] = row.get("jig_station", "")
    return labels


def discover_jobs(set_dir: Path) -> list[dict]:
    """One entry per station folder that has both orientation DXFs present."""
    jig = read_jig_stations(set_dir)
    jobs: list[dict] = []
    for folder in STATION_FOLDERS:
        files = {o: set_dir / folder / f"{o}.dxf" for o in ORIENTATIONS}
        missing = [str(p) for p in files.values() if not p.is_file()]
        if missing:
            if any((set_dir / folder).exists() for _ in [0]):
                print(f"  ! {folder}: missing {missing}; skipped")
            continue
        jobs.append({
            "folder": folder,
            "jig_station": jig.get(folder, ""),
            "files": files,
            "name": f"{set_dir.name}_{folder}",
        })
    return jobs


# --- COM session ------------------------------------------------------------------
class WinLaseSession:
    """Thin wrapper over the IAutomate COM interface.

    Every COM call is isolated here. win32com early binding (EnsureDispatch) reads
    winlase.tlb, so documented [out] parameters come back as return values; if your
    build's type library flags a parameter differently, this is the one place to
    adjust.
    """

    def __init__(self) -> None:
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
            self.m = gencache.EnsureDispatch("Winlase.Automate")   # early binding
        except Exception:
            self.m = Dispatch("Winlase.Automate")                  # late binding
        self.m.AttachToMarker()
        self.cards = int(self.m.GetScanCardCount())
        if self.cards < 1:
            raise RuntimeError(
                "GetScanCardCount() == 0: no scan card detected. Run on the laser PC "
                "with the card + dongle installed, or use --dry-run off the machine."
            )
        self.bits_per_mm = int(self.m.GetLensCalFactor(0, 0))
        if self.bits_per_mm <= 0:
            raise RuntimeError("GetLensCalFactor returned <= 0; is a lens cal loaded?")

    def print_default_profile(self) -> None:
        try:
            p = self.m.GetDefaultProfile(0)
            # (Mode, PassCount, MarkSpeed[bits/ms], Jumpspeed, ..., Laserpower[%], ..., T1[kHz], ...)
            speed_mm_s = float(p[2]) / self.bits_per_mm * 1000.0
            print(f"  default Profile0 (inherited by marks): mark speed "
                  f"{speed_mm_s:.0f} mm/s, laser power {float(p[7]):.0f} %, "
                  f"freq {float(p[11]):.2f} kHz  [set in GUI if these are wrong]")
        except Exception as exc:  # read-only convenience; never fatal
            print(f"  (could not read default profile: {exc})")

    def mm_to_bits(self, mm: float) -> int:
        return int(round(mm * self.bits_per_mm))

    def build_job(self, job: dict, save: bool) -> list[str]:
        """Create one job with the H and V graphics; return warning strings."""
        warnings: list[str] = []
        out_path = job["out_path"]
        job_index = int(self.m.NewJob(str(out_path)))

        for orientation in ORIENTATIONS:
            dxf = job["files"][orientation]
            xmin, ymin, xmax, ymax = dxf_bounds_mm(dxf)
            want_cx = self.mm_to_bits((xmin + xmax) / 2.0)
            want_cy = self.mm_to_bits((ymin + ymax) / 2.0)

            obj = int(self.m.NewVectorGraphic(f"{job['folder']}_{orientation}", str(dxf)))

            left, top, right, bottom = (float(v) for v in self.m.GetObjRect(obj))
            got_cx = (left + right) / 2.0
            got_cy = (top + bottom) / 2.0
            self.m.OffsetObj(obj, int(round(want_cx - got_cx)), int(round(want_cy - got_cy)))

            # Size sanity: imported width/height should equal the DXF mm size * bits/mm.
            want_w = self.mm_to_bits(xmax - xmin)
            want_h = self.mm_to_bits(ymax - ymin)
            got_w, got_h = abs(right - left), abs(top - bottom)
            tol = max(2, int(0.02 * max(want_w, want_h, 1)))
            if abs(got_w - want_w) > tol or abs(got_h - want_h) > tol:
                warnings.append(
                    f"{job['folder']}/{orientation}: imported size {got_w:.0f}x{got_h:.0f} "
                    f"bits != expected {want_w}x{want_h} (unexpected import scaling?)"
                )

            spacing_bits = self.mm_to_bits(FILL_SPACING_MM)
            if spacing_bits < 1:
                spacing_bits = 1
                warnings.append(
                    f"{job['folder']}/{orientation}: 0.01 mm rounds below 1 bit at "
                    f"{self.bits_per_mm} bits/mm; fill spacing set to 1 bit"
                )
            angle = FILL_ANGLE_DEG[orientation]
            self.m.SetObjFill(obj, spacing_bits, angle, angle, FILL_STYLE_PARALLEL)
            self.m.SetObjMarkFillFlag(obj, 1)
            self.m.SetObjMarkOutlineFlag(obj, 0)
            self.m.SetObjNumPasses(obj, NUM_PASSES)
            # Force the mark speed to 400 mm/s (the WinLase default profile is 1000).
            # Write ONLY the speed: read Profile 0, change just the speed field, write
            # it back (laser power, frequency, and delays are echoed unchanged), then
            # read again and VERIFY power (index 5) and frequency/T1 (index 9) did not
            # move. A corrupt round-trip aborts the build rather than alter the laser.
            before = list(self.m.GetObjProfile(obj, 0))
            after = list(before)
            after[0] = MARK_SPEED_MM_S / 1000.0 * self.bits_per_mm  # mm/s -> bits/mSec
            self.m.SetObjProfile(obj, 0, *after)
            check = list(self.m.GetObjProfile(obj, 0))
            if (abs(float(check[5]) - float(before[5])) > 1e-3
                    or abs(float(check[9]) - float(before[9])) > 1e-3):
                raise RuntimeError(
                    "%s/%s: profile write moved power/frequency (power %s->%s %%, "
                    "freq %s->%s kHz) -- ABORTING build, no job saved"
                    % (job['folder'], orientation, before[5], check[5], before[9], check[9]))
            got_speed = float(check[0]) / self.bits_per_mm * 1000.0
            if abs(got_speed - MARK_SPEED_MM_S) > SPEED_TOLERANCE_MM_S:
                raise RuntimeError("%s/%s: mark speed is %.0f mm/s after write, not %.0f"
                                   % (job['folder'], orientation, got_speed, MARK_SPEED_MM_S))

            if int(self.m.IsObjOutOfBounds(obj)):
                warnings.append(
                    f"{job['folder']}/{orientation}: object falls outside the markable "
                    f"field (needs |x|,|y| <= {FIELD_BIT_LIMIT} bits = "
                    f"{FIELD_BIT_LIMIT / self.bits_per_mm:.1f} mm)"
                )

        count = int(self.m.GetObjCount())
        if count != len(ORIENTATIONS):
            warnings.append(f"{job['folder']}: job holds {count} objects, expected {len(ORIENTATIONS)}")

        if save:
            self.m.SaveJobToFile(str(out_path), APP_VERSION, _today(), APP_NAME, COMPANY)
        self.m.CloseJob(job_index)
        return warnings

    def close(self) -> None:
        try:
            self.m.ReleaseMarker()
        except Exception:
            pass


def _today() -> str:
    from datetime import date
    return date.today().isoformat()


# --- Planning / dry run -----------------------------------------------------------
def print_plan(set_dir: Path, jobs: list[dict], out_dir: Path) -> None:
    print(f"\n{set_dir.name}: {len(jobs)} job(s) -> {out_dir}")
    for job in jobs:
        tag = f" (jig {job['jig_station']})" if job["jig_station"] else ""
        print(f"  {job['name']}.wlj{tag}")
        for orientation in ORIENTATIONS:
            dxf = job["files"][orientation]
            xmin, ymin, xmax, ymax = dxf_bounds_mm(dxf)
            cx, cy = (xmin + xmax) / 2.0, (ymin + ymax) / 2.0
            print(f"     {orientation:10} fill {FILL_ANGLE_DEG[orientation]:>2} deg @ "
                  f"{FILL_SPACING_MM} mm, {NUM_PASSES} pass  |  bbox "
                  f"[{xmin:.3f},{ymin:.3f}]..[{xmax:.3f},{ymax:.3f}] mm, center "
                  f"({cx:+.3f},{cy:+.3f}) mm")
    print(f"  reminder: set the job loop to {JOB_LOOP_COUNT}x in the GUI before marking.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("sets", nargs="+", type=Path,
                        help="one or more built set directories (each = one wafer)")
    parser.add_argument("--out-subdir", default="WinLaseJobs",
                        help="subfolder written inside each set (default: WinLaseJobs)")
    parser.add_argument("--dry-run", action="store_true",
                        help="parse and print the plan without loading WinLase (no COM)")
    parser.add_argument("--verify", action="store_true",
                        help="build the first job in memory and report placement, do not save")
    args = parser.parse_args()

    plans = []
    for set_dir in args.sets:
        if not set_dir.is_dir():
            print(f"! not a directory: {set_dir}")
            continue
        jobs = discover_jobs(set_dir)
        if not jobs:
            print(f"! no complete P1..P4 station folders under {set_dir}")
            continue
        out_dir = set_dir / args.out_subdir
        for job in jobs:
            job["out_path"] = (out_dir / f"{job['name']}.wlj").resolve()
        plans.append((set_dir, jobs, out_dir))
        print_plan(set_dir, jobs, out_dir)

    if not plans:
        return 1
    if args.dry_run:
        print("\nDry run: no jobs written. Re-run on the laser PC without --dry-run.")
        return 0

    session = WinLaseSession()
    print(f"\nWinLase attached: {session.cards} scan card(s), lens {session.bits_per_mm} bits/mm "
          f"(field +/-{FIELD_BIT_LIMIT / session.bits_per_mm:.1f} mm).")
    session.print_default_profile()
    try:
        if args.verify:
            set_dir, jobs, out_dir = plans[0]
            print(f"\nVERIFY: building {jobs[0]['name']} in memory (not saved)...")
            warnings = session.build_job(jobs[0], save=False)
            for w in warnings:
                print(f"  WARN {w}")
            print("  placement math ran; " + ("see warnings above." if warnings
                  else "no warnings -- safe to run the full build."))
            return 0

        total = 0
        for set_dir, jobs, out_dir in plans:
            out_dir.mkdir(parents=True, exist_ok=True)
            print(f"\nBuilding {set_dir.name} -> {out_dir}")
            for job in jobs:
                warnings = session.build_job(job, save=True)
                flag = "  <-- CHECK" if warnings else ""
                print(f"  wrote {job['out_path'].name}{flag}")
                for w in warnings:
                    print(f"     WARN {w}")
                total += 1
        print(f"\nDone: {total} job(s) written. Open each in the WinLase GUI, set loop "
              f"{JOB_LOOP_COUNT}x, seat the jig, and mark P1 -> P2 -> P3 -> P4.")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
