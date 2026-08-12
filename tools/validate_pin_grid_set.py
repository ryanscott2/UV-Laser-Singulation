"""Validate a built pin-grid set against the masters it was cut from.

Three independent checks, all of which must pass before a set is exposed:

1. Reconstruction. Each tile is translated back by its own field center and
   unioned. The result must XOR to exactly zero area against the layer-0 master,
   which proves no cut geometry was lost, duplicated, or shifted by the split.
2. Field placement. The laser exposes each job with auto-centering OFF, placing
   the DXF origin on the field center. This self-test confirms every tile fits
   inside the qualified field with its origin at the center, so true-coordinate
   placement reproduces the wafer (reconstruction proves the four origins rebuild
   the master). It also reports how far each job would move if auto-centering were
   accidentally left ON.
3. Grid alignment. The splitter's window centers and this repository's table-grid
   station table are separate literals that nothing else forces to agree. They
   must, because the jig indexes on the table's 1 inch grid: a mismatch would
   offset every exposure by the difference, silently.

Writes `validation_report.txt` into the set and exits non-zero on any failure.
Needs the standalone `klayout` Python wheel.

    python tools/validate_pin_grid_set.py
"""

from __future__ import annotations

import argparse
import os
import runpy
from pathlib import Path

import klayout.db as pya

from pin_grid_layout import GRID_PITCH, STATIONS, USABLE_FIELD_HALF_MM

REPO_ROOT = Path(__file__).resolve().parent.parent
SPLITTER = REPO_ROOT / "python" / "split_klayout_four_windows.py"
DEFAULT_MASTERS = Path("dxf/100mm_10x30mm_Masters")
DEFAULT_SET = Path("output/DXFs/080826_FourPosDicer_PinGrid54mm")
ORIENTATIONS = ("Horizontal", "Vertical")
MASTER_STEM = "100mm_wafer_10x30mm_{orientation}_master"

DXF_UNIT_UM = 1_000.0  # 1 DXF drawing unit = 1 mm
CUT_LAYER = 0

# A Region built from begin_shapes_rec stays bound to its Layout, so the layouts
# have to outlive the regions returned below.
_OPEN_LAYOUTS: list = []


def read_region(path: Path, layer_name: str | None = None):
    """Read one layer as a Region. `layer_name` None means numeric layer 0."""
    if not path.is_file():
        raise FileNotFoundError(f"Missing file: {path}")
    layout = pya.Layout()
    _OPEN_LAYOUTS.append(layout)
    options = pya.LoadLayoutOptions()
    options.dxf_unit = DXF_UNIT_UM
    layout.read(str(path), options)

    region = pya.Region()
    matched = False
    for index in layout.layer_indices():
        info = layout.get_info(index)
        name = str(getattr(info, "name", "") or "")
        if layer_name is None:
            hit = (info.layer == CUT_LAYER and info.datatype == 0) or name == str(CUT_LAYER)
        else:
            hit = name == layer_name
        if hit:
            matched = True
            for top in layout.top_cells():
                region += pya.Region(top.begin_shapes_rec(index))
    return (region, layout.dbu) if matched else (None, layout.dbu)


def mm_to_dbu(value_mm: float, dbu: float) -> int:
    return int(round(value_mm * 1_000.0 / dbu))


def check_grid_alignment() -> tuple[list[str], bool]:
    """Confirm the splitter's window centers still sit on the table grid.

    `WINDOW_CENTER_*_UM` in the splitter and `field_center_mm` in the station
    table are independent literals. Nothing derives one from the other, so they
    can drift apart without any other check noticing: the reconstruction test
    undoes each tile by the same station offset it was cut with, so it stays at
    zero XOR even if both are wrong together.

    The jig indexes on the table's 1 inch grid, which puts each field center
    exactly one grid space from the wafer center and adjacent stations two spaces
    (2 inches, 50.800 mm) apart. Anything else means the software and the
    hardware disagree about where a station is.
    """
    namespace = runpy.run_path(str(SPLITTER), run_name="grid_alignment_check")
    center_x_mm = namespace["WINDOW_CENTER_X_UM"] / 1000.0
    center_y_mm = namespace["WINDOW_CENTER_Y_UM"] / 1000.0
    windows = namespace["WINDOWS"]

    lines: list[str] = []
    problems: list[str] = []

    for axis, value in (("X", center_x_mm), ("Y", center_y_mm)):
        if abs(value - GRID_PITCH) > 1e-9:
            problems.append(
                f"WINDOW_CENTER_{axis}_UM is {value:.4f} mm, not one {GRID_PITCH:.3f} mm grid space"
            )

    by_label = {station.label: station for station in STATIONS}
    for job_name, x_sign, y_sign in windows:
        label = job_name.split("_", 1)[0]
        station = by_label.get(label)
        if station is None:
            problems.append(f"splitter emits {label}, which the station table does not define")
            continue
        want = station.field_center_mm
        got = (x_sign * center_x_mm, y_sign * center_y_mm)
        if abs(want[0] - got[0]) > 1e-9 or abs(want[1] - got[1]) > 1e-9:
            problems.append(f"{label}: splitter {got} vs station table {want}")

    missing = sorted(set(by_label) - {name.split("_", 1)[0] for name, _, _ in windows})
    if missing:
        problems.append(f"station table defines {missing}, which the splitter never emits")

    if problems:
        lines.append("Grid alignment PROBLEMS: " + "; ".join(problems))
        return lines, False

    lines.append(
        f"Grid alignment: window centers at +/-{center_x_mm:.3f} mm are one "
        f"{GRID_PITCH:.3f} mm grid space from wafer center, so adjacent stations are "
        f"{2.0 * GRID_PITCH:.3f} mm apart, and all {len(windows)} splitter windows match "
        "the station table"
    )
    return lines, True


def check_field_placement(set_dir: Path) -> tuple[list[str], bool]:
    """Self-test the anchor-free placement method.

    The laser runs with auto-centering OFF, so it places each job at its true
    coordinates: the DXF origin lands on the field center. For that to expose the
    wafer correctly each tile must (a) be built with its field center at the origin
    -- which the reconstruction check proves by rebuilding the master from the four
    origins -- and (b) fit inside the laser's usable field, so nothing is driven
    outside the addressable area. This checks (b), and reports the largest
    content-bbox offset from the origin: that is exactly how far a job would be
    misplaced if auto-centering were left ON, so a nonzero value is the reminder to
    keep it OFF.
    """
    problems: list[str] = []
    max_offset_mm = 0.0
    checked = 0
    half = USABLE_FIELD_HALF_MM
    for station in STATIONS:
        for path in sorted((set_dir / station.label).glob("*.dxf")):
            region, dbu = read_region(path)
            where = f"{station.label}/{path.name}"
            if region is None:
                problems.append(f"{where}: no layer 0 geometry")
                continue
            checked += 1
            if region.is_empty():
                continue
            box = region.bbox()
            half_dbu = mm_to_dbu(half, dbu)
            if (box.left < -half_dbu or box.right > half_dbu
                    or box.bottom < -half_dbu or box.top > half_dbu):
                edges = tuple(round(v * dbu / 1000.0, 3)
                              for v in (box.left, box.bottom, box.right, box.top))
                problems.append(f"{where}: geometry {edges} mm exceeds the +/-{half:.3f} mm field")
            cx = (box.left + box.right) / 2.0 * dbu / 1000.0
            cy = (box.bottom + box.top) / 2.0 * dbu / 1000.0
            max_offset_mm = max(max_offset_mm, abs(cx), abs(cy))

    if problems:
        return ["Field placement PROBLEMS: " + "; ".join(problems)], False
    return [
        f"Field placement self-test: all {checked} tiles fit within "
        f"the +/-{half:.3f} mm usable field with the DXF origin at the field center, so exposing at "
        f"true coordinates reproduces the wafer. Expose with the laser's auto-centering OFF: "
        f"leaving it ON would misplace a job by up to {max_offset_mm:.3f} mm."
    ], True


def validate(masters_dir: Path, set_dir: Path,
             master_stem: str = MASTER_STEM) -> tuple[list[str], bool]:
    lines: list[str] = []
    ok = True

    grid_lines, grid_ok = check_grid_alignment()
    lines.extend(grid_lines)
    ok &= grid_ok

    # The splitter applies GLOBAL_*_OFFSET_UM to every job as a calibration shift;
    # undo it here so reconstruction checks the split itself, not the calibration.
    ns = runpy.run_path(str(SPLITTER), run_name="pin_grid_validate_offsets")
    global_x_mm = ns["GLOBAL_X_OFFSET_UM"] / 1000.0
    global_y_mm = ns["GLOBAL_Y_OFFSET_UM"] / 1000.0

    for orientation in ORIENTATIONS:
        stem = master_stem.format(orientation=orientation)
        master, dbu = read_region(masters_dir / f"{stem}.dxf")
        if master is None:
            raise RuntimeError(f"No layer 0 in master {stem}.dxf")

        rebuilt = pya.Region()
        for station in STATIONS:
            tile, tile_dbu = read_region(set_dir / station.label / f"{orientation}.dxf")
            if tile is None:
                raise RuntimeError(f"No layer 0 in {station.label}/{orientation}.dxf")
            if tile_dbu != dbu:
                raise RuntimeError(f"{station.label}/{orientation}.dxf has dbu {tile_dbu}, not {dbu}")
            # Undo the splitter's translation (and its calibration offset) to put
            # the tile back on the wafer.
            rebuilt += tile.transformed(
                pya.Trans(
                    mm_to_dbu(station.field_center_mm[0] - global_x_mm, dbu),
                    mm_to_dbu(station.field_center_mm[1] - global_y_mm, dbu),
                )
            )

        xor_area = (master.merged() ^ rebuilt.merged()).area()
        ok &= xor_area == 0
        lines.append(
            f"{orientation}.dxf: master_polygons={master.merged().count()}, "
            f"reconstructed_polygons={rebuilt.count()}, xor_area_dbu2={xor_area}"
        )

    placement_lines, placement_ok = check_field_placement(set_dir)
    lines.extend(placement_lines)
    ok &= placement_ok

    lines.append(
        "Station labels name the jig position; each exposes the opposite quadrant: "
        + ", ".join(f"{s.label}={s.jig_station}->{s.exposed_wafer_area}" for s in STATIONS)
    )
    return lines, ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--masters", type=Path, default=DEFAULT_MASTERS)
    parser.add_argument("--set", dest="set_dir", type=Path, default=DEFAULT_SET)
    parser.add_argument("--master-stem", dest="master_stem", default=MASTER_STEM,
                        help="master filename stem with an {orientation} field "
                             "(for sets built from a combined source)")
    args = parser.parse_args()

    os.chdir(REPO_ROOT)
    lines, ok = validate(args.masters, args.set_dir, args.master_stem)

    report = "\n".join(lines) + "\n"
    print(report, end="")
    (args.set_dir / "validation_report.txt").write_text(report, encoding="utf-8")
    print("\nALL CHECKS PASS" if ok else "\nFAILURES PRESENT")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
