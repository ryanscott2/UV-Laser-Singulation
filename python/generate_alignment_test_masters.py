"""Generate a minimal alignment-test master pair for a settings-check exposure.

Instead of dicing the wafer, this writes four short witness marks around the
outermost 10 x 30 mm cell in each quadrant: a 5 mm segment lying on each of that
cell's four boundary lines, centered on that edge's midpoint. Sixteen marks in
all, 50 um wide, exactly where the real cut lines would run.

Each cell sits entirely inside one exposure field, so a station's file carries
exactly one cell's marks and nothing straddles a seam. Measuring a printed mark
against its nominal coordinate therefore reads out that station's placement
error directly, without a full wafer of cuts to interpret.

Cells are picked as the furthest-out 10 x 30 cell that is wholly on the safe
wafer area and wholly within one quadrant, which is (+/-10, +/-30).

Writes the same two filenames the production masters use, so the existing build
and validate tools work against this directory unchanged:

    python python/generate_alignment_test_masters.py
    python tools/build_pin_grid_set.py --masters dxf/AlignmentTest_5mm_Marks \\
        --set output/DXFs/<date>_AlignmentTest
    python tools/validate_pin_grid_set.py --masters dxf/AlignmentTest_5mm_Marks \\
        --set output/DXFs/<date>_AlignmentTest
"""

from __future__ import annotations

import math
from pathlib import Path

import klayout.db as pya

OUTPUT_DIR = Path("dxf/AlignmentTest_5mm_Marks")

# Must match the production grid, or the marks will not sit on real cut lines.
WAFER_RADIUS_UM = 50_000.0
EDGE_BEAD_MM = 2.000
X_PITCH_UM = 10_000.0
Y_PITCH_UM = 30_000.0
CUT_WIDTH_UM = 50.0

MARK_LENGTH_UM = 5_000.0

OUTPUT_LAYER = 0
OUTPUT_DATATYPE = 0
OUTPUT_LAYER_NAME = "0"
DXF_POLYGON_MODE = 1
MASTER_STEM = "100mm_wafer_10x30mm_{orientation}_master"


def to_dbu(layout, value_um: float) -> int:
    return int(round(value_um / layout.dbu))


def quadrant_cells() -> list[tuple[float, float]]:
    """The furthest-out cell wholly on the wafer and wholly within one quadrant.

    A cell centered on y = 0 straddles the x axis and so belongs to no single
    station, which is why the answer is (+/-10, +/-30) and not the (+/-40, 0)
    pair that sit further from center.
    """
    safe_um = WAFER_RADIUS_UM - EDGE_BEAD_MM * 1000.0
    half_x, half_y = X_PITCH_UM / 2.0, Y_PITCH_UM / 2.0
    best: dict[tuple[int, int], tuple[float, float, float]] = {}
    for ix in range(-6, 7):
        for iy in range(-3, 4):
            cx, cy = ix * X_PITCH_UM, iy * Y_PITCH_UM
            if cx == 0.0 or cy == 0.0:
                continue                      # straddles a field seam
            corners = [(cx + sx * half_x, cy + sy * half_y)
                       for sx in (-1, 1) for sy in (-1, 1)]
            if any(math.hypot(x, y) > safe_um for x, y in corners):
                continue
            key = (1 if cx > 0 else -1, 1 if cy > 0 else -1)
            reach = math.hypot(cx, cy)
            if key not in best or reach > best[key][0]:
                best[key] = (reach, cx, cy)
    return [(cx, cy) for _, cx, cy in sorted(best.values())]


def mark_boxes(layout, orientation: str):
    """The 5 mm witness marks for one orientation, as KLayout boxes."""
    half_cut = CUT_WIDTH_UM / 2.0
    half_mark = MARK_LENGTH_UM / 2.0
    half_x, half_y = X_PITCH_UM / 2.0, Y_PITCH_UM / 2.0
    boxes = []
    for cx, cy in quadrant_cells():
        if orientation == "Vertical":
            # Left and right cell edges are vertical lines; center each mark on
            # the edge midpoint, which is the cell's own y.
            for edge_x in (cx - half_x, cx + half_x):
                boxes.append(pya.Box(
                    to_dbu(layout, edge_x - half_cut), to_dbu(layout, cy - half_mark),
                    to_dbu(layout, edge_x + half_cut), to_dbu(layout, cy + half_mark)))
        else:
            for edge_y in (cy - half_y, cy + half_y):
                boxes.append(pya.Box(
                    to_dbu(layout, cx - half_mark), to_dbu(layout, edge_y - half_cut),
                    to_dbu(layout, cx + half_mark), to_dbu(layout, edge_y + half_cut)))
    return boxes


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
    cells = quadrant_cells()
    print("Outermost fully-on-wafer cell per quadrant:")
    for cx, cy in cells:
        print(f"  centre ({cx/1000:7.2f},{cy/1000:7.2f}) mm   "
              f"spans x {(cx-X_PITCH_UM/2)/1000:6.1f} ..{(cx+X_PITCH_UM/2)/1000:6.1f}, "
              f"y {(cy-Y_PITCH_UM/2)/1000:6.1f} ..{(cy+Y_PITCH_UM/2)/1000:6.1f}")

    for orientation in ("Horizontal", "Vertical"):
        layout = pya.Layout()
        layout.dbu = 0.001
        region = pya.Region()
        for box in mark_boxes(layout, orientation):
            region.insert(box)
        region.merge()
        path = OUTPUT_DIR / f"{MASTER_STEM.format(orientation=orientation)}.dxf"
        write_dxf(path, layout, region, f"AlignmentTest_{orientation}")
        print(f"\n{orientation}: {region.count()} marks -> {path}")
        # bbox is in dbu; at dbu = 0.001 um that is 1e6 dbu per mm.
        to_mm = layout.dbu / 1000.0
        for poly in sorted(region.each(), key=lambda p: (p.bbox().bottom, p.bbox().left)):
            b = poly.bbox()
            print(f"    x {b.left*to_mm:8.3f} ..{b.right*to_mm:8.3f} mm   "
                  f"y {b.bottom*to_mm:8.3f} ..{b.top*to_mm:8.3f} mm")


if __name__ == "__main__":
    main()
