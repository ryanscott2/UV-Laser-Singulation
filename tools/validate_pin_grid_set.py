"""Validate a built pin-grid set against the masters it was cut from.

Three independent checks, all of which must pass before a set is exposed:

1. Reconstruction. Each tile is translated back by its own field center and
   unioned. The result must XOR to exactly zero area against the layer-0 master,
   which proves no cut geometry was lost, duplicated, or shifted by the split.
2. Registration. Every file must carry four anchors on
   `REGISTRATION_DO_NOT_EXPOSE` whose combined bounding box is exactly
   the declared field half size, so a laser importer that centers on content
   bounds cannot displace one job relative to another.
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

from pin_grid_layout import GRID_PITCH, REGISTRATION_HALF_SIZE_MM, STATIONS

REPO_ROOT = Path(__file__).resolve().parent.parent
SPLITTER = REPO_ROOT / "python" / "split_klayout_four_windows.py"
DEFAULT_MASTERS = Path("dxf/100mm_10x30mm_Masters")
DEFAULT_SET = Path("output/DXFs/080826_FourPosDicer_PinGrid54mm")
ORIENTATIONS = ("Horizontal", "Vertical")
MASTER_STEM = "100mm_wafer_10x30mm_{orientation}_master"

DXF_UNIT_UM = 1_000.0  # 1 DXF drawing unit = 1 mm
CUT_LAYER = 0
REGISTRATION_LAYER_NAME = "REGISTRATION_DO_NOT_EXPOSE"

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


def header_extents_mm(path: Path) -> dict[str, tuple[float, float]]:
    """Read $EXTMIN/$EXTMAX out of a DXF HEADER, in drawing units.

    These are what an importer should use instead of inferring the extent from
    entities. Parsed straight from the group codes: `9` names the variable, then
    `10` and `20` carry its X and Y.
    """
    lines = path.read_text(encoding="utf-8", errors="strict").splitlines()
    found: dict[str, tuple[float, float]] = {}
    for index, line in enumerate(lines):
        if line.strip() not in {"$EXTMIN", "$EXTMAX"}:
            continue
        name = line.strip()
        values: dict[str, float] = {}
        for offset in range(index + 1, min(index + 7, len(lines)) - 1, 2):
            code, value = lines[offset].strip(), lines[offset + 1].strip()
            if code in {"10", "20"}:
                values[code] = float(value)
        if "10" in values and "20" in values:
            found[name] = (values["10"], values["20"])
    return found


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


def validate(masters_dir: Path, set_dir: Path) -> tuple[list[str], bool]:
    lines: list[str] = []
    ok = True

    grid_lines, grid_ok = check_grid_alignment()
    lines.extend(grid_lines)
    ok &= grid_ok

    for orientation in ORIENTATIONS:
        stem = MASTER_STEM.format(orientation=orientation)
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
            # Undo the splitter's translation to put the tile back on the wafer.
            rebuilt += tile.transformed(
                pya.Trans(
                    mm_to_dbu(station.field_center_mm[0], dbu),
                    mm_to_dbu(station.field_center_mm[1], dbu),
                )
            )

        xor_area = (master.merged() ^ rebuilt.merged()).area()
        ok &= xor_area == 0
        lines.append(
            f"{orientation}.dxf: master_polygons={master.merged().count()}, "
            f"reconstructed_polygons={rebuilt.count()}, xor_area_dbu2={xor_area}"
        )

    problems = []
    for station in STATIONS:
        for orientation in ORIENTATIONS:
            path = set_dir / station.label / f"{orientation}.dxf"
            anchors, dbu = read_region(path, REGISTRATION_LAYER_NAME)
            where = f"{station.label}/{orientation}.dxf"
            if anchors is None or anchors.count() != 4:
                problems.append(f"{where}: anchors={0 if anchors is None else anchors.count()}")
                continue
            half = mm_to_dbu(REGISTRATION_HALF_SIZE_MM, dbu)
            box = anchors.bbox()
            if (box.left, box.bottom, box.right, box.top) != (-half, -half, half, half):
                problems.append(
                    f"{where}: bbox={(box.left * dbu / 1000.0, box.bottom * dbu / 1000.0, box.right * dbu / 1000.0, box.top * dbu / 1000.0)} mm"
                )

    if problems:
        ok = False
        lines.append("Registration envelope PROBLEMS: " + "; ".join(problems))
    else:
        lines.append(
            f"Registration envelope: all {len(STATIONS) * len(ORIENTATIONS)} files have four "
            f"anchors on {REGISTRATION_LAYER_NAME} with bbox exactly "
            f"+/-{REGISTRATION_HALF_SIZE_MM:.3f} mm"
        )

    # The anchors only fix per-file centering for an importer that counts a layer
    # the operator has set to no marking. The header extents do not depend on that.
    extent_problems = []
    half = REGISTRATION_HALF_SIZE_MM
    for station in STATIONS:
        for orientation in ORIENTATIONS:
            path = set_dir / station.label / f"{orientation}.dxf"
            found = header_extents_mm(path)
            where = f"{station.label}/{orientation}.dxf"
            if set(found) != {"$EXTMIN", "$EXTMAX"}:
                extent_problems.append(f"{where}: missing {sorted({'$EXTMIN','$EXTMAX'} - set(found))}")
                continue
            if found["$EXTMIN"] != (-half, -half) or found["$EXTMAX"] != (half, half):
                extent_problems.append(
                    f"{where}: $EXTMIN={found['$EXTMIN']} $EXTMAX={found['$EXTMAX']}"
                )

    if extent_problems:
        ok = False
        lines.append("Declared header extents PROBLEMS: " + "; ".join(extent_problems))
    else:
        lines.append(
            f"Declared header extents: all {len(STATIONS) * len(ORIENTATIONS)} files declare "
            f"$EXTMIN/$EXTMAX at exactly +/-{half:.3f} mm, so an importer need not infer "
            "the window from entities"
        )

    lines.append(
        "Station labels name the jig position; each exposes the opposite quadrant: "
        + ", ".join(f"{s.label}={s.jig_station}->{s.exposed_wafer_area}" for s in STATIONS)
    )
    return lines, ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--masters", type=Path, default=DEFAULT_MASTERS)
    parser.add_argument("--set", dest="set_dir", type=Path, default=DEFAULT_SET)
    args = parser.parse_args()

    os.chdir(REPO_ROOT)
    lines, ok = validate(args.masters, args.set_dir)

    report = "\n".join(lines) + "\n"
    print(report, end="")
    (args.set_dir / "validation_report.txt").write_text(report, encoding="utf-8")
    print("\nALL CHECKS PASS" if ok else "\nFAILURES PRESENT")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
