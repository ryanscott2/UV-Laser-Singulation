"""Build the four-position pin-grid production set from the master DXFs.

Runs `python/split_klayout_four_windows.py` once per orientation, then assembles
the labeled folder structure the operator uses at the machine:

    <set>/P1/Horizontal.dxf   <set>/P1/Vertical.dxf
    <set>/P2/...              <set>/P3/...   <set>/P4/...
    <set>/BuildLogs/<orientation>/*_split_log.txt and *_window_manifest.csv
    <set>/Master/  copies of the masters this set was cut from
    <set>/position_manifest.csv

Needs the standalone `klayout` Python wheel, not the KLayout application. The
splitter reads its overrides out of `globals()` (KLayout's `-rd` mechanism) and
has no argv parsing, so this script injects them with `runpy`.

Everything is done with repository-relative paths so the generated logs stay
portable. Run `validate_pin_grid_set.py` afterwards.

    python tools/build_pin_grid_set.py
"""

from __future__ import annotations

import argparse
import csv
import os
import runpy
import shutil
from pathlib import Path

from pin_grid_layout import STATIONS, hole_label

REPO_ROOT = Path(__file__).resolve().parent.parent
SPLITTER = Path("python/split_klayout_four_windows.py")
DEFAULT_MASTERS = Path("dxf/100mm_10x30mm_Masters")
DEFAULT_SET = Path("output/DXFs/080826_FourPosDicer_PinGrid54mm")
ORIENTATIONS = ("Horizontal", "Vertical")
MASTER_STEM = "100mm_wafer_10x30mm_{orientation}_master"


def build(masters_dir: Path, set_dir: Path) -> None:
    for orientation in ORIENTATIONS:
        stem = MASTER_STEM.format(orientation=orientation)
        master = masters_dir / f"{stem}.dxf"
        if not master.is_file():
            raise FileNotFoundError(f"Master not found: {master}")

        # The splitter writes the four tiles plus its log and manifest here; the
        # tiles are moved out below so BuildLogs keeps only the records.
        staging = set_dir / "BuildLogs" / orientation
        staging.mkdir(parents=True, exist_ok=True)
        runpy.run_path(
            str(SPLITTER),
            init_globals={"input": str(master), "output_dir": str(staging)},
            run_name="__main__",
        )

        for station in STATIONS:
            tile = staging / f"{stem}_{station.splitter_job}.dxf"
            if not tile.is_file():
                raise FileNotFoundError(
                    f"Splitter did not emit {tile.name}. Its WINDOWS labels and "
                    "tools/pin_grid_layout.py have drifted apart."
                )
            # Folder names are stable across rebuilds, so overwrite in place
            # rather than removing directories. OneDrive blocks rmdir here.
            destination = set_dir / station.label
            destination.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(tile, destination / f"{orientation}.dxf")
            tile.unlink()

    master_copy = set_dir / "Master"
    master_copy.mkdir(parents=True, exist_ok=True)
    for name in sorted(p.name for p in masters_dir.iterdir() if p.is_file()):
        shutil.copyfile(masters_dir / name, master_copy / name)

    write_position_manifest(set_dir)


def write_position_manifest(set_dir: Path) -> Path:
    path = set_dir / "position_manifest.csv"
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            [
                "folder", "jig_row", "jig_col", "jig_station", "exposed_wafer_area",
                "field_center_x_wafer_mm", "field_center_y_wafer_mm",
                "engraved_outer_front_left_pin",
                "outer_pin_columns", "outer_pin_rows",
                "horizontal_file", "vertical_file",
            ]
        )
        for station in STATIONS:
            column, row = station.outer_front_left_pin
            writer.writerow(
                [
                    station.label, station.jig_row, station.jig_col,
                    station.jig_station, station.exposed_wafer_area,
                    f"{station.field_center_mm[0]:+.3f}",
                    f"{station.field_center_mm[1]:+.3f}",
                    hole_label(column, row),
                    ",".join(str(v + 1) for v in station.outer_columns),
                    ",".join(str(v + 1) for v in station.outer_rows),
                    f"{station.label}/Horizontal.dxf",
                    f"{station.label}/Vertical.dxf",
                ]
            )
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--masters", type=Path, default=DEFAULT_MASTERS,
                        help=f"master DXF directory (default: {DEFAULT_MASTERS})")
    parser.add_argument("--set", dest="set_dir", type=Path, default=DEFAULT_SET,
                        help=f"output set directory (default: {DEFAULT_SET})")
    args = parser.parse_args()

    # Relative paths keep the generated build logs free of local absolute paths.
    os.chdir(REPO_ROOT)
    build(args.masters, args.set_dir)

    print(f"\nBuilt {args.set_dir} from {args.masters}")
    for station in STATIONS:
        print(f"  {station.label}  jig {station.jig_station:13} exposes {station.exposed_wafer_area}")
    print("\nNow run: python tools/validate_pin_grid_set.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
