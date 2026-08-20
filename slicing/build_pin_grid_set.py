"""Build the four-position pin-grid production set from the master DXFs.

Runs `slicing/split_klayout.py` once per orientation, then assembles
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

    python slicing/build_pin_grid_set.py
"""

from __future__ import annotations

import argparse
import csv
import os
import runpy
import shutil
import sys
from pathlib import Path

from pin_grid_layout import STATIONS, hole_label

REPO_ROOT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent
SPLITTER = HERE / "split_klayout.py"
DEFAULT_MASTERS = Path("dxf/100mm_10x30mm_Masters")
DEFAULT_SET = Path("output/DXFs/080826_FourPosDicer_PinGrid54mm")
ORIENTATIONS = ("Horizontal", "Vertical")
MASTER_STEM = "100mm_wafer_10x30mm_{orientation}_master"


def build(masters_dir: Path, set_dir: Path, master_stem: str = MASTER_STEM,
          splitter_overrides: dict | None = None) -> None:
    for orientation in ORIENTATIONS:
        stem = master_stem.format(orientation=orientation)
        master = masters_dir / f"{stem}.dxf"
        if not master.is_file():
            raise FileNotFoundError(f"Master not found: {master}")

        # The splitter writes the four tiles plus its log and manifest here; the
        # tiles are moved out below so BuildLogs keeps only the records.
        staging = set_dir / "BuildLogs" / orientation
        staging.mkdir(parents=True, exist_ok=True)
        init_globals = {"input": str(master), "output_dir": str(staging)}
        if splitter_overrides:
            init_globals.update(splitter_overrides)
        runpy.run_path(str(SPLITTER), init_globals=init_globals, run_name="__main__")

        for station in STATIONS:
            tile = staging / f"{stem}_{station.splitter_job}.dxf"
            if not tile.is_file():
                raise FileNotFoundError(
                    f"Splitter did not emit {tile.name}. Its WINDOWS labels and "
                    "slicing/pin_grid_layout.py have drifted apart."
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


def parse_cut_layer(spec: str) -> tuple[int, int]:
    """`5` -> (5, 0);  `5/2` -> (5, 2)."""
    spec = spec.strip()
    if "/" in spec:
        layer, datatype = spec.split("/", 1)
        return int(layer), int(datatype)
    return int(spec), 0


def build_combined(source: Path, cut_layer: tuple[int, int], set_dir: Path,
                   edge_bead_mm: float, rotation_deg: int = 0,
                   splitter_overrides: dict | None = None) -> str:
    """Front end for a single source whose cut layer holds both orientations.

    Reads the cut layer, optionally insets it by an edge bead, splits it into
    horizontal and vertical regions (lossless), writes those as two masters, then
    runs the normal per-orientation build against them. Returns the master stem.
    """
    import klayout.db as pya  # noqa: E402 - lazy so a masters-only build needs no wheel import here

    sys.path.insert(0, str(HERE))
    import split_cut_orientation as sco  # noqa: E402

    layout = pya.Layout()
    # DXF drawing units are millimeters by this repo's convention (see split_klayout.py's
    # INPUT_DXF_UNIT_UM = 1000, "1 unit = 1 mm = 1000 um"). KLayout's default DXF unit is NOT
    # mm, so a DXF source read WITHOUT dxf_unit comes in 1000x too small -- collapsing an
    # mm-scale pattern into a few um at the origin (every window then clips all of it). GDS/OAS
    # carry their own units and are read as-is.
    if source.suffix.lower() == ".dxf":
        load_options = pya.LoadLayoutOptions()
        load_options.dxf_unit = 1000.0
        layout.read(str(source), load_options)
    else:
        layout.read(str(source))
    dbu = layout.dbu

    region = sco.read_layer_region(layout, cut_layer[0], cut_layer[1])
    # Rotate the cut geometry to the physical wafer-flat orientation BEFORE splitting, so the
    # H/V classification and street pitch follow the jig (k*90 CCW about the wafer center /
    # origin; exact via pya.Trans). flat -Y=0, +X=90, +Y=180, -X=270. Re-teach P1-P4 to match.
    rot_k = int(round(rotation_deg / 90.0)) % 4
    if rot_k:
        region.transform(pya.Trans(rot_k))
    # Split the pristine cut network FIRST, so the lossless gate validates the H/V
    # decomposition of the actual cuts. The edge-bead clip is applied AFTER: clipping
    # the streets to the wafer arc leaves sub-micron diagonal slivers that would trip
    # the exact-zero gate (a ~0.02 um^2 rounding residual) even though the split is sound.
    horizontal, vertical = sco.split_horizontal_vertical(region)
    if not sco.lossless(region, horizontal, vertical):
        raise RuntimeError(
            "H/V split lost geometry: the cut layer is not purely axis-aligned. "
            "Author the cuts on two layers and use --masters instead."
        )
    if edge_bead_mm and edge_bead_mm > 0:
        safe = sco.safe_wafer_region(layout, edge_bead_mm * 1000.0)
        if rot_k:
            safe.transform(pya.Trans(rot_k))  # keep the wafer arc/flats aligned with the rotated cuts
        horizontal &= safe
        vertical &= safe
        horizontal.merge()
        vertical.merge()

    # Name the masters after the set (which carries the run date), not the source
    # GDS -- output files use today's date, not the date the GDS was authored.
    base = set_dir.name
    master_stem = f"{base}_{{orientation}}_master"
    staging = set_dir / "BuildLogs" / "combined_source_masters"
    staging.mkdir(parents=True, exist_ok=True)
    sco.write_master_dxf(staging / f"{base}_Horizontal_master.dxf", dbu, horizontal)
    sco.write_master_dxf(staging / f"{base}_Vertical_master.dxf", dbu, vertical)

    print(f"Combined layer {cut_layer[0]}/{cut_layer[1]}: split into "
          f"H ({horizontal.count()} polys) + V ({vertical.count()} polys)"
          + (f", inset {edge_bead_mm:g} mm edge bead" if edge_bead_mm > 0 else ""))
    build(staging, set_dir, master_stem=master_stem, splitter_overrides=splitter_overrides)
    return master_stem


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
                        help=f"pre-split master DXF directory (default: {DEFAULT_MASTERS})")
    parser.add_argument("--set", dest="set_dir", type=Path, default=DEFAULT_SET,
                        help=f"output set directory (default: {DEFAULT_SET})")
    parser.add_argument("--combined", type=Path, default=None,
                        help="single source (GDS/DXF/OAS) whose cut layer holds both "
                             "orientations; split into H/V automatically instead of --masters")
    parser.add_argument("--cut-layer", default=None,
                        help="cut-lines layer for --combined, e.g. 5 or 5/0")
    parser.add_argument("--edge-bead", type=float, default=0.0,
                        help="mm to inset the cuts from the wafer edge before splitting (0 = none)")
    parser.add_argument("--rotation", choices=("0", "90", "180", "270"), default="0",
                        help="rotate the cut geometry to match the physical wafer flat "
                             "(flat -Y=0, +X=90, +Y=180, -X=270), applied BEFORE the H/V split so "
                             "orientations reclassify and street pitch rotates with the jig. "
                             "--combined only; re-teach P1-P4 for the rotated jig.")
    parser.add_argument("--jig-flat", choices=("front", "right", "back", "left"), default=None,
                        help="convenience for --rotation from the wafer-flat direction on the "
                             "stage: front(-Y)=0, right(+X)=90, back(+Y)=180, left(-X)=270. "
                             "Overrides --rotation when given.")
    # Optional splitter overrides. Omitted => the splitter's baked calibration/settings.
    parser.add_argument("--cut-width", type=float, default=None,
                        help="force/cap the cut width in um (default: the splitter's baked value)")
    parser.add_argument("--width-mode", choices=("cap", "force"), default=None,
                        help="cap narrows wider cuts only; force sets every cut to --cut-width")
    parser.add_argument("--global-x", type=float, default=None,
                        help="global X offset in um (default: the baked calibration)")
    parser.add_argument("--global-y", type=float, default=None,
                        help="global Y offset in um (default: the baked calibration)")
    parser.add_argument("--stitch", type=float, default=None, help="seam overlap in um")
    parser.add_argument("--offset", action="append", default=[], metavar="LABEL=X,Y",
                        help="per-station nudge in um on top of the global; repeatable")
    args = parser.parse_args()

    # Relative paths keep the generated build logs free of local absolute paths.
    os.chdir(REPO_ROOT)

    # --jig-flat maps the wafer-flat direction to a rotation and overrides --rotation.
    jig_flat_deg = {"front": 0, "right": 90, "back": 180, "left": 270}
    rotation_deg = jig_flat_deg[args.jig_flat] if args.jig_flat else int(args.rotation)

    overrides: dict = {}
    if args.cut_width is not None:
        overrides["max_cut_width_um"] = str(args.cut_width)
    if args.width_mode is not None:
        overrides["cut_width_mode"] = args.width_mode
    if args.global_x is not None:
        overrides["global_x_um"] = str(args.global_x)
    if args.global_y is not None:
        overrides["global_y_um"] = str(args.global_y)
    if args.stitch is not None:
        overrides["stitch_overlap_um"] = str(args.stitch)
    if args.offset:
        overrides["window_offsets"] = ";".join(s.replace("=", ":") for s in args.offset)

    # A width-forced build narrows filled cuts, so the validator needs the expected
    # width to normalize the master before its XOR. Thread it into the printed hint.
    width_hint = ""
    if args.width_mode == "force" and args.cut_width is not None:
        width_hint = f" --cut-width {args.cut_width:g} --width-mode force"

    if args.combined is not None:
        if args.cut_layer is None:
            parser.error("--cut-layer is required with --combined")
        stem = build_combined(args.combined, parse_cut_layer(args.cut_layer),
                              args.set_dir, args.edge_bead, rotation_deg=rotation_deg,
                              splitter_overrides=overrides)
        source_desc = f"{args.combined} (auto-split combined cut layer)"
        validate_hint = (f"python slicing/validate_pin_grid_set.py --set {args.set_dir} "
                         f"--masters {args.set_dir / 'Master'} --master-stem \"{stem}\"" + width_hint)
    else:
        if rotation_deg != 0:
            parser.error("--rotation/--jig-flat is only supported with --combined (pre-split "
                         "masters can't be reclassified); regenerate rotated masters or use --combined.")
        build(args.masters, args.set_dir, splitter_overrides=overrides)
        source_desc = str(args.masters)
        validate_hint = "python slicing/validate_pin_grid_set.py" + width_hint

    print(f"\nBuilt {args.set_dir} from {source_desc}")
    for station in STATIONS:
        print(f"  {station.label}  jig {station.jig_station:13} exposes {station.exposed_wafer_area}")
    print(f"\nNow run: {validate_hint}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
