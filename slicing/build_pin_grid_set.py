"""Build the four-position pin-grid production set from the master DXFs.

Runs `slicing/split_klayout.py` once per orientation, then assembles
the labeled folder structure the operator uses at the machine:

    <set>/P1/+0.0.dxf         <set>/P1/+90.0.dxf
    <set>/P2/...              <set>/P3/...   <set>/P4/...
    <set>/BuildLogs/<angle>/*_split_log.txt and *_window_manifest.csv
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


def angle_label(a: float) -> str:
    """Filename stem for a pass angle in [-90, +90]: +45.0, -45.0, +0.0, +90.0.

    The laser PC reads this back with float(path.stem) to set the fill angle, so the
    format must round-trip. One pass angle per file.
    """
    return f"{float(a) + 0.0:+.1f}"


def _master_angle_label(stem: str) -> str:
    """Pass-angle label for a master DXF, from an explicit angle token (e.g.
    `<base>_+45.0_master`) or a legacy Horizontal/Vertical name (-> +0.0 / +90.0)."""
    core = stem[:-7] if stem.endswith("_master") else stem
    token = core.rsplit("_", 1)[-1]
    try:
        return angle_label(float(token))
    except ValueError:
        if "Horizontal" in stem:
            return angle_label(0.0)
        if "Vertical" in stem:
            return angle_label(90.0)
    raise ValueError(f"cannot read a pass angle from master name '{stem}'")


def _dxf_nonempty(path: Path) -> bool:
    """True if the DXF has at least one ENTITIES vertex (dependency-free)."""
    lines = [ln.strip() for ln in path.read_text(errors="strict").splitlines()]
    in_entities = False
    for code, value in zip(lines[0::2], lines[1::2]):
        if value == "ENTITIES":
            in_entities = True
            continue
        if in_entities and value == "ENDSEC":
            break
        if in_entities and code == "10":
            return True
    return False


def _tile_masters(master_paths, set_dir: Path, splitter_overrides: dict | None) -> None:
    """Tile each (label, master) into <set>/P{n}/<label>.dxf via split_klayout.

    A station tile with no geometry (a pass angle whose cuts miss that quadrant) is
    skipped, so each station folder holds only the angles that actually mark there --
    one pass angle per file, named by the angle.
    """
    for label, master in master_paths:
        stem = master.stem
        staging = set_dir / "BuildLogs" / label
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
            if _dxf_nonempty(tile):
                # Folder names are stable across rebuilds, so overwrite in place
                # rather than removing directories. OneDrive blocks rmdir here.
                destination = set_dir / station.label
                destination.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(tile, destination / f"{label}.dxf")
            tile.unlink()


def _copy_masters(masters, set_dir: Path) -> None:
    master_copy = set_dir / "Master"
    master_copy.mkdir(parents=True, exist_ok=True)
    for path in masters:
        shutil.copyfile(path, master_copy / path.name)


def build(masters_dir: Path, set_dir: Path, master_stem: str = MASTER_STEM,
          splitter_overrides: dict | None = None) -> None:
    """Tile a directory of masters (any pass angles) into the P1-P4 set.

    Masters are discovered by `*_master.dxf`; each one's pass angle comes from its name
    (an explicit angle token, or a legacy Horizontal/Vertical stem). Station files are
    named by the angle.
    """
    masters = sorted(masters_dir.glob("*_master.dxf"))
    if not masters:
        masters = [masters_dir / f"{master_stem.format(orientation=o)}.dxf"
                   for o in ORIENTATIONS]
    for m in masters:
        if not m.is_file():
            raise FileNotFoundError(f"Master not found: {m}")
    master_paths = [(_master_angle_label(m.stem), m) for m in masters]
    _tile_masters(master_paths, set_dir, splitter_overrides)
    _copy_masters(masters, set_dir)
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
    # Group the cut network by pass angle FIRST, so the lossless gate validates the
    # decomposition of the actual cuts. The edge-bead clip is applied AFTER: clipping
    # the streets to the wafer arc leaves sub-micron slivers that would trip the
    # exact-zero gate even though the split is sound. Any cut angle is supported.
    groups = sco.split_by_angle(region)
    if not sco.lossless_multi(region, list(groups.values())):
        raise RuntimeError(
            "angle split lost geometry: a cut could not be classified. The cut layer "
            "should be clean line/rectangle geometry (any angle is fine)."
        )
    if edge_bead_mm and edge_bead_mm > 0:
        safe = sco.safe_wafer_region(layout, edge_bead_mm * 1000.0)
        if rot_k:
            safe.transform(pya.Trans(rot_k))  # keep the wafer arc/flats aligned with the rotated cuts
        for a in list(groups):
            clipped = groups[a] & safe
            clipped.merge()
            groups[a] = clipped

    # Name the masters after the set (which carries the run date), not the source GDS.
    # One master per pass angle: <base>_<+/-angle>_master.dxf.
    base = set_dir.name
    staging = set_dir / "BuildLogs" / "combined_source_masters"
    staging.mkdir(parents=True, exist_ok=True)
    master_paths = []
    for a in sorted(groups):
        if groups[a].is_empty():
            continue
        label = angle_label(a)
        master = staging / f"{base}_{label}_master.dxf"
        sco.write_master_dxf(master, dbu, groups[a])
        master_paths.append((label, master))
    if not master_paths:
        raise RuntimeError(f"cut layer {cut_layer[0]}/{cut_layer[1]} has no geometry")

    print(f"Combined layer {cut_layer[0]}/{cut_layer[1]}: {len(master_paths)} pass angle(s): "
          + ", ".join(lbl for lbl, _ in master_paths)
          + (f"; inset {edge_bead_mm:g} mm edge bead" if edge_bead_mm > 0 else ""))
    _tile_masters(master_paths, set_dir, splitter_overrides)
    _copy_masters([m for _, m in master_paths], set_dir)
    write_position_manifest(set_dir)
    return f"{base}_*_master"


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
                "pass_files",
            ]
        )
        for station in STATIONS:
            column, row = station.outer_front_left_pin
            pass_files = ";".join(sorted(p.name for p in (set_dir / station.label).glob("*.dxf")))
            writer.writerow(
                [
                    station.label, station.jig_row, station.jig_col,
                    station.jig_station, station.exposed_wafer_area,
                    f"{station.field_center_mm[0]:+.3f}",
                    f"{station.field_center_mm[1]:+.3f}",
                    hole_label(column, row),
                    ",".join(str(v + 1) for v in station.outer_columns),
                    ",".join(str(v + 1) for v in station.outer_rows),
                    pass_files,
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
    # Decoupled tiling: independent X/Y window centers + field. For an asymmetric stage
    # envelope (ample X travel, pipe-limited Y) use tighter Y rows + a bigger field so the
    # wafer is still covered. Omitted => the splitter's symmetric defaults (25.4/25.4, 54 mm).
    parser.add_argument("--window-center-x", type=float, default=None,
                        help="X window-center (half-spacing) in um; default 25400")
    parser.add_argument("--window-center-y", type=float, default=None,
                        help="Y window-center (half-spacing) in um; decouple from X for a "
                             "pipe-limited Y (e.g. 12000)")
    parser.add_argument("--field", type=float, default=None,
                        help="declared galvo field in um (default 54000; up to ~78485 full "
                             "field to cover the wafer from tight Y rows)")
    parser.add_argument("--clip-mode", choices=("partition", "full_window"), default=None,
                        help="partition = each station owns its half + stitch; full_window = "
                             "each station cuts its whole field (needed when the field is much "
                             "bigger than the spacing, e.g. the decoupled dicing config)")
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
    if args.window_center_x is not None:
        overrides["window_center_x_um"] = str(args.window_center_x)
    if args.window_center_y is not None:
        overrides["window_center_y_um"] = str(args.window_center_y)
    if args.field is not None:
        overrides["qualified_field_size_um"] = str(args.field)
    if args.clip_mode is not None:
        overrides["clip_mode"] = args.clip_mode

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
