"""Generate a seam-test master pair for a settings-check exposure.

Instead of dicing the wafer, this writes four short marks that straddle the field
seams, where a placement error shows up: one station draws the half of a mark on
its side and the neighbour draws the other, so a lateral misregistration between
those stations appears as a step at the join, and the size of the step is the
error. Marks perpendicular to the x = 0 seam are horizontal lines (Horizontal
master); those perpendicular to y = 0 are vertical (Vertical master).

The marks are parameterized (run with -h). Placement is measured off the outermost
fitting cell centre on each seam (+/-40 mm in x, +/-30 mm in y on the production
grid):

  --placement symmetric : all four at the cell centre + --approach-um (signed;
                          + is outboard toward the edge, - is inboard)
  --placement flat      : the two flat-facing marks (-X, -Y) sit --mark-from-flat-um
                          from their flats; the other two at cell centre + approach
  --placement radial    : all four on one circle of radius (major-flat depth minus
                          --mark-from-flat-um). The -Y mark then sits that far inside
                          the major flat and the other three mirror it at the same
                          radius, an even radial spread about the wafer centre.

Variants used so far (each writes the two production filenames, so build/validate
work unchanged; then `build_pin_grid_set.py --masters <out-dir> --set <set>`):

  v1  --width-um 50 --length-mm 5  --placement symmetric --approach-um 0 --marker
  v2  --width-um 20 --length-mm 10 --placement flat      --approach-um 2000
  v3  --width-um 50 --length-mm 10 --placement symmetric --approach-um -3000

  081326 radial seam-test set (50 um x 10 mm marks stepping 1.5 mm inward):
  v1  --width-um 50 --length-mm 10 --placement radial --mark-from-flat-um 3000
  v2  --width-um 50 --length-mm 10 --placement radial --mark-from-flat-um 4500
  v3  --width-um 50 --length-mm 10 --placement radial --mark-from-flat-um 6000

Defaults reproduce v2.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import klayout.db as pya

OUTPUT_DIR = Path("dxf/AlignmentTest_v2_Marks")

# Must match the production grid, or the marks will not sit on real cell centres.
WAFER_RADIUS_UM = 50_000.0
EDGE_BEAD_MM = 2.000
X_PITCH_UM = 10_000.0
Y_PITCH_UM = 30_000.0
PRIMARY_FLAT_LENGTH_UM = 32_500.0    # major flat, faces -Y
SECONDARY_FLAT_LENGTH_UM = 18_000.0  # minor flat, faces -X
CUT_WIDTH_UM = 20.0

MARK_LENGTH_UM = 10_000.0

# The two flat-facing marks (toward the -X and -Y flats) sit MARK_FROM_FLAT_UM from
# their flat, for a consistent short mark-to-flat read. The other two (+X, +Y, on
# the plain arc) sit on the outermost fitting cell centre plus EDGE_APPROACH_UM.
MARK_FROM_FLAT_UM = 5_000.0
EDGE_APPROACH_UM = 2_000.0
PLACEMENT = "flat"  # "flat" (v2) or "symmetric" (v1/v3); see --placement

# The centered plus is dropped for v2; set True to bring it back (a plus at the
# origin that reads the four-way registration in one place). Kept in the Horizontal
# master when enabled.
INCLUDE_CENTERED_MARKER = False
MARKER_LENGTH_UM = 2_500.0
MARKER_WIDTH_UM = 50.0
MARKER_ORIENTATION = "Horizontal"

OUTPUT_LAYER = 0
OUTPUT_DATATYPE = 0
OUTPUT_LAYER_NAME = "0"
DXF_POLYGON_MODE = 1
MASTER_STEM = "100mm_wafer_10x30mm_{orientation}_master"


def to_dbu(layout, value_um: float) -> int:
    return int(round(value_um / layout.dbu))


def seam_marks() -> list[tuple[float, float, str]]:
    """(x, y, orientation) for each mark, in um.

    `orientation` is the master the mark belongs to, which is the one whose
    lines run perpendicular to the seam being crossed.
    """
    safe_um = WAFER_RADIUS_UM - EDGE_BEAD_MM * 1000.0
    half_x, half_y = X_PITCH_UM / 2.0, Y_PITCH_UM / 2.0
    half_mark = MARK_LENGTH_UM / 2.0
    half_cut = CUT_WIDTH_UM / 2.0

    def cell_fits(cx: float, cy: float) -> bool:
        return all(math.hypot(cx + sx * half_x, cy + sy * half_y) <= safe_um
                   for sx in (-1, 1) for sy in (-1, 1))

    primary_depth = math.sqrt(WAFER_RADIUS_UM ** 2 - (PRIMARY_FLAT_LENGTH_UM / 2.0) ** 2)
    secondary_depth = math.sqrt(WAFER_RADIUS_UM ** 2 - (SECONDARY_FLAT_LENGTH_UM / 2.0) ** 2)

    # Outermost cell centre that fits on each seam.
    best_x = max((abs(i) * X_PITCH_UM for i in range(-6, 7)
                  if i != 0 and cell_fits(i * X_PITCH_UM, 0.0)), default=None)
    best_y = max((abs(j) * Y_PITCH_UM for j in range(-3, 4)
                  if j != 0 and cell_fits(0.0, j * Y_PITCH_UM)), default=None)

    marks: list[tuple[float, float, str]] = []

    if PLACEMENT == "radial":
        # All four marks lie on one circle whose radius is referenced off the major
        # (-Y) flat: radius = primary_depth - MARK_FROM_FLAT_UM. The -Y mark then sits
        # MARK_FROM_FLAT_UM inside the major flat and the other three mirror it at the
        # same radius, an even radial spread that crosses both seams twice. best_x /
        # best_y (cell-centre placement) are unused here on purpose.
        radius = primary_depth - MARK_FROM_FLAT_UM
        marks.append((+radius, 0.0, "Vertical"))    # +X on the y = 0 seam
        marks.append((-radius, 0.0, "Vertical"))    # -X on the y = 0 seam
        marks.append((0.0, +radius, "Horizontal"))  # +Y on the x = 0 seam
        marks.append((0.0, -radius, "Horizontal"))  # -Y, MARK_FROM_FLAT_UM inside major flat
    else:
        # Horizontal seam y = 0: vertical marks at +/-X (Vertical master).
        if best_x is not None:
            if PLACEMENT == "flat":
                # left (-X) a fixed distance from the secondary flat; right (+X) at the
                # cell centre plus the approach.
                marks.append((-(secondary_depth - MARK_FROM_FLAT_UM), 0.0, "Vertical"))
                marks.append((best_x + EDGE_APPROACH_UM, 0.0, "Vertical"))
            else:  # symmetric: both at the cell centre plus the (signed) approach
                for sign in (-1, 1):
                    marks.append((sign * (best_x + EDGE_APPROACH_UM), 0.0, "Vertical"))

        # Vertical seam x = 0: horizontal marks at 0,+/-Y (Horizontal master).
        if best_y is not None:
            if PLACEMENT == "flat":
                marks.append((0.0, -(primary_depth - MARK_FROM_FLAT_UM), "Horizontal"))
                marks.append((0.0, best_y + EDGE_APPROACH_UM, "Horizontal"))
            else:
                for sign in (-1, 1):
                    marks.append((0.0, sign * (best_y + EDGE_APPROACH_UM), "Horizontal"))

    # Every mark must clear the edge bead. Use the real footprint: half the mark
    # length along its long axis, half the cut width across it.
    for x, y, orientation in marks:
        if orientation == "Horizontal":   # long in x
            far = math.hypot(abs(x) + half_mark, abs(y) + half_cut)
        else:                             # vertical, long in y
            far = math.hypot(abs(x) + half_cut, abs(y) + half_mark)
        if far > safe_um:
            raise SystemExit(f"mark at ({x/1000:.1f},{y/1000:.1f}) reaches "
                             f"{far/1000:.2f} mm, past the {safe_um/1000:.1f} mm safe radius")
    return marks


def mark_boxes(layout, orientation: str):
    half_cut = CUT_WIDTH_UM / 2.0
    half_mark = MARK_LENGTH_UM / 2.0
    boxes = []
    for x, y, kind in seam_marks():
        if kind != orientation:
            continue
        if orientation == "Vertical":       # vertical line crossing the y = 0 seam
            boxes.append(pya.Box(
                to_dbu(layout, x - half_cut), to_dbu(layout, y - half_mark),
                to_dbu(layout, x + half_cut), to_dbu(layout, y + half_mark)))
        else:                               # horizontal line crossing the x = 0 seam
            boxes.append(pya.Box(
                to_dbu(layout, x - half_mark), to_dbu(layout, y - half_cut),
                to_dbu(layout, x + half_mark), to_dbu(layout, y + half_cut)))
    return boxes


def centered_marker(layout):
    """A plus at the wafer origin, built the same way the production master does."""
    half_length = MARKER_LENGTH_UM / 2.0
    half_width = MARKER_WIDTH_UM / 2.0
    horizontal = pya.Region(pya.Box(
        to_dbu(layout, -half_length), to_dbu(layout, -half_width),
        to_dbu(layout, half_length), to_dbu(layout, half_width)))
    vertical = pya.Region(pya.Box(
        to_dbu(layout, -half_width), to_dbu(layout, -half_length),
        to_dbu(layout, half_width), to_dbu(layout, half_length)))
    return horizontal + vertical


def write_dxf(path: Path, layout, region, cell_name: str) -> None:
    out = pya.Layout()
    out.dbu = layout.dbu
    cell = out.create_cell(cell_name)
    info = pya.LayerInfo(OUTPUT_LAYER, OUTPUT_DATATYPE)
    info.name = OUTPUT_LAYER_NAME
    cell.shapes(out.layer(info)).insert(region)

    options = pya.SaveLayoutOptions()
    options.set_format_from_filename(str(path))
    options.dxf_polygon_mode = DXF_POLYGON_MODE
    options.scale_factor = 0.001
    out.write(str(path), options)

    generated = f"L{OUTPUT_LAYER}D{OUTPUT_DATATYPE}_{OUTPUT_LAYER_NAME}"
    text = path.read_text(encoding="utf-8", errors="strict")
    path.write_text(text.replace(generated, OUTPUT_LAYER_NAME),
                    encoding="utf-8", newline="")


def main() -> None:
    global OUTPUT_DIR, CUT_WIDTH_UM, MARK_LENGTH_UM, PLACEMENT
    global EDGE_APPROACH_UM, MARK_FROM_FLAT_UM, INCLUDE_CENTERED_MARKER

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out-dir", type=Path, default=OUTPUT_DIR,
                        help="output masters directory")
    parser.add_argument("--width-um", type=float, default=CUT_WIDTH_UM,
                        help="mark line width in um")
    parser.add_argument("--length-mm", type=float, default=MARK_LENGTH_UM / 1000.0,
                        help="mark line length in mm")
    parser.add_argument("--placement", choices=("flat", "symmetric", "radial"), default=PLACEMENT,
                        help="flat: -X/-Y marks a fixed distance from their flats; "
                             "symmetric: all four at the cell centre + approach; "
                             "radial: all four on one circle, radius = major-flat depth "
                             "- mark-from-flat-um")
    parser.add_argument("--approach-um", type=float, default=EDGE_APPROACH_UM,
                        help="signed offset from the cell centre; + outboard, - inboard")
    parser.add_argument("--mark-from-flat-um", type=float, default=MARK_FROM_FLAT_UM,
                        help="distance from the flat for the flat-facing marks (flat placement)")
    parser.add_argument("--marker", action="store_true",
                        help="add the centered plus marker")
    args = parser.parse_args()

    OUTPUT_DIR = args.out_dir
    CUT_WIDTH_UM = args.width_um
    MARK_LENGTH_UM = args.length_mm * 1000.0
    PLACEMENT = args.placement
    EDGE_APPROACH_UM = args.approach_um
    MARK_FROM_FLAT_UM = args.mark_from_flat_um
    INCLUDE_CENTERED_MARKER = args.marker

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Placement {PLACEMENT}; width {CUT_WIDTH_UM:g} um; length {MARK_LENGTH_UM/1000:g} mm; "
          f"approach {EDGE_APPROACH_UM:g} um -> {OUTPUT_DIR}")
    print("Seam-crossing marks (centre -> the two stations that must meet there):")
    for x, y, kind in seam_marks():
        seam = "y = 0" if kind == "Vertical" else "x = 0"
        print(f"  ({x/1000:+7.1f},{y/1000:+7.1f}) mm   {kind:10} line across the {seam} seam")

    for orientation in ("Horizontal", "Vertical"):
        layout = pya.Layout()
        layout.dbu = 0.001
        region = pya.Region()
        for box in mark_boxes(layout, orientation):
            region.insert(box)
        if INCLUDE_CENTERED_MARKER and orientation == MARKER_ORIENTATION:
            region += centered_marker(layout)
        region.merge()
        path = OUTPUT_DIR / f"{MASTER_STEM.format(orientation=orientation)}.dxf"
        write_dxf(path, layout, region, f"SeamTest_{orientation}")
        to_mm = layout.dbu / 1000.0
        print(f"\n{orientation}: {region.count()} marks -> {path}")
        for poly in sorted(region.each(), key=lambda p: (p.bbox().bottom, p.bbox().left)):
            b = poly.bbox()
            print(f"    x {b.left*to_mm:8.3f} ..{b.right*to_mm:8.3f} mm   "
                  f"y {b.bottom*to_mm:8.3f} ..{b.top*to_mm:8.3f} mm")


if __name__ == "__main__":
    main()
