"""Generate a minimal seam-test master pair for a settings-check exposure.

Instead of dicing the wafer, this writes four short marks that straddle the
field seams, which is where a placement error actually shows up. Each mark is a
5 mm line running perpendicular to its seam, so one station draws the half on
its side and the neighbour draws the other. The two halves have to meet: a
lateral misregistration between those stations appears directly as a step at the
join, and the size of the step is the error.

Where the marks go
------------------
The four exposures meet at x = 0 and y = 0. Each station's geometry is clipped
half a stitch past its seam, so the overlap band is +/-0.100 mm and a mark laid
across the seam is genuinely shared.

Note that the seams do not fall on cell boundaries. With cut lines at
x = +/-5, +/-15, ... and y = +/-15, +/-45, the lines x = 0 and y = 0 run through
the *middle* of a cell. The marks are therefore centred on the outermost cell
whose centre lies on each seam, which is (+/-40, 0) on the horizontal seam and
(0, +/-30) on the vertical one -- furthest out, where any rotation between
stations is largest, and still clear of the 2 mm edge bead.

Those four marks cover all four station pairings:

    (+40,   0)   DXF11 meets DXF21     (0, +30)   DXF21 meets DXF22
    (-40,   0)   DXF12 meets DXF22     (0, -30)   DXF11 meets DXF12

A mark perpendicular to a horizontal seam is a vertical line and belongs in the
Vertical master; the reverse for the other seam.

Writes the same two filenames the production masters use, so the existing build
and validate tools work against this directory unchanged:

    python python/generate_alignment_test_masters.py
    python tools/build_pin_grid_set.py --masters dxf/AlignmentTest_5mm_Marks \\
        --set output/DXFs/081026_AlignmentTest
    python tools/validate_pin_grid_set.py --masters dxf/AlignmentTest_5mm_Marks \\
        --set output/DXFs/081026_AlignmentTest
"""

from __future__ import annotations

import math
from pathlib import Path

import klayout.db as pya

OUTPUT_DIR = Path("dxf/AlignmentTest_5mm_Marks")

# Must match the production grid, or the marks will not sit on real cell centres.
WAFER_RADIUS_UM = 50_000.0
EDGE_BEAD_MM = 2.000
X_PITCH_UM = 10_000.0
Y_PITCH_UM = 30_000.0
CUT_WIDTH_UM = 50.0

MARK_LENGTH_UM = 5_000.0

# The same centred cross the production masters carry, reproduced exactly. It
# straddles both seams at once, so all four stations expose a quadrant of it and
# it reads out the four-way registration in one place, where the pairwise seam
# marks only ever test two stations against each other. Production keeps it in
# the Horizontal master, so this does too.
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

    def cell_fits(cx: float, cy: float) -> bool:
        return all(math.hypot(cx + sx * half_x, cy + sy * half_y) <= safe_um
                   for sx in (-1, 1) for sy in (-1, 1))

    marks: list[tuple[float, float, str]] = []

    # Horizontal seam y = 0: step out along x over cells centred on that seam.
    # A mark across it is vertical, so it lives in the Vertical master.
    best = max((abs(i) * X_PITCH_UM for i in range(-6, 7)
                if i != 0 and cell_fits(i * X_PITCH_UM, 0.0)), default=None)
    if best is not None:
        for sign in (-1, 1):
            marks.append((sign * best, 0.0, "Vertical"))

    # Vertical seam x = 0: step out along y. A mark across it is horizontal.
    best = max((abs(j) * Y_PITCH_UM for j in range(-3, 4)
                if j != 0 and cell_fits(0.0, j * Y_PITCH_UM)), default=None)
    if best is not None:
        for sign in (-1, 1):
            marks.append((0.0, sign * best, "Horizontal"))

    # Every mark must clear the edge bead along its whole length.
    for x, y, orientation in marks:
        far = (math.hypot(x, abs(y) + half_mark) if orientation == "Horizontal"
               else math.hypot(abs(x) + half_mark, y))
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
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
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
        if orientation == MARKER_ORIENTATION:
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
