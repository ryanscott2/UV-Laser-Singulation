"""Split a combined cut-lines layer into horizontal and vertical cut regions.

Customer layouts often carry every dicing/boundary cut on one layer as connected
Manhattan polygons -- street networks, die-outline frames -- so a single shape
holds both orientations and per-shape classification fails. This decomposes the
layer into axis-aligned rectangles and classifies each by its long axis. Crossing
"junction" squares go to BOTH passes, so every cut line stays continuous. The
split is lossless: `(H | V)` reconstructs the input region exactly.

It also carries the optional edge-bead clip (the same inset-circle-and-flats safe
region the 10x30 master generator uses), so the front end and the interactive
slicer can share one definition of both operations.

Standalone `klayout` wheel; no KLayout application needed.
"""

from __future__ import annotations

import math

try:
    import pya
except ImportError:
    import klayout.db as pya

# A rectangle whose long side is at least this many times its short side is an
# unambiguous line; anything squarer is treated as a crossing junction.
JUNCTION_ASPECT = 1.25

# 100 mm wafer, primary (major) flat facing -Y, secondary (minor) flat facing -X,
# matching make_figures and the 10x30 master generator. Microns.
WAFER_RADIUS_UM = 50_000.0
PRIMARY_FLAT_LENGTH_UM = 32_500.0
SECONDARY_FLAT_LENGTH_UM = 18_000.0
CIRCLE_SEGMENTS = 2048

OUTPUT_LAYER = 0
OUTPUT_DATATYPE = 0
OUTPUT_LAYER_NAME = "0"
DXF_POLYGON_MODE = 1


def _to_dbu(layout, value_um: float) -> int:
    return int(round(value_um / layout.dbu))


def read_layer_region(layout, layer: int, datatype: int = 0):
    """Union of every shape on one GDS/OASIS layer, flattened to the top cell."""
    region = pya.Region()
    found = False
    for index in layout.layer_indices():
        info = layout.get_info(index)
        if info.layer == layer and info.datatype == datatype:
            found = True
            for top in layout.top_cells():
                region += pya.Region(top.begin_shapes_rec(index))
    if not found:
        available = ", ".join(
            f"{layout.get_info(i).layer}/{layout.get_info(i).datatype}"
            for i in layout.layer_indices()
        )
        raise ValueError(f"No layer {layer}/{datatype} in the source. Present: {available or '<none>'}")
    return region


def safe_wafer_region(layout, edge_bead_um: float):
    """Circle inset by the bead, clipped by both flats, as the generator builds it."""
    safe_radius = WAFER_RADIUS_UM - edge_bead_um
    primary_depth = math.sqrt(WAFER_RADIUS_UM**2 - (PRIMARY_FLAT_LENGTH_UM / 2.0) ** 2)
    secondary_depth = math.sqrt(WAFER_RADIUS_UM**2 - (SECONDARY_FLAT_LENGTH_UM / 2.0) ** 2)
    safe_primary_y = -primary_depth + edge_bead_um
    safe_secondary_x = -secondary_depth + edge_bead_um

    radius_dbu = _to_dbu(layout, safe_radius)
    circle = pya.Region(pya.Polygon([
        pya.Point(
            int(round(radius_dbu * math.cos(2.0 * math.pi * i / CIRCLE_SEGMENTS))),
            int(round(radius_dbu * math.sin(2.0 * math.pi * i / CIRCLE_SEGMENTS))),
        )
        for i in range(CIRCLE_SEGMENTS)
    ]))
    flat_limits = pya.Region(pya.Box(
        _to_dbu(layout, safe_secondary_x),
        _to_dbu(layout, safe_primary_y),
        _to_dbu(layout, safe_radius + 1_000.0),
        _to_dbu(layout, safe_radius + 1_000.0),
    ))
    return circle & flat_limits


def split_horizontal_vertical(region):
    """Return (horizontal_region, vertical_region) from a combined cut region.

    Decomposes into rectangles and sorts each by its long axis; junction squares
    (crossings) join both so no line is broken. `(H | V)` equals the input.
    """
    horizontal = pya.Region()
    vertical = pya.Region()
    for shape in region.decompose_trapezoids():
        poly = shape.polygon
        if poly is None:
            poly = pya.Polygon(shape.bbox())
        box = shape.bbox()
        w, h = box.width(), box.height()
        if w == 0 or h == 0:
            continue
        if w >= h * JUNCTION_ASPECT:
            horizontal.insert(poly)
        elif h >= w * JUNCTION_ASPECT:
            vertical.insert(poly)
        else:  # crossing: belongs to both passes so each line stays continuous
            horizontal.insert(poly)
            vertical.insert(poly)
    horizontal.merge()
    vertical.merge()
    return horizontal, vertical


def write_master_dxf(path, dbu: float, region, cell_name: str = "MASTER") -> None:
    """Write one region to a layer-0 DXF the four-window splitter can read, the
    same way the 10x30 master generator writes its masters."""
    output = pya.Layout()
    output.dbu = dbu
    cell = output.create_cell(cell_name)
    info = pya.LayerInfo(OUTPUT_LAYER, OUTPUT_DATATYPE)
    info.name = OUTPUT_LAYER_NAME
    cell.shapes(output.layer(info)).insert(region)

    options = pya.SaveLayoutOptions()
    options.set_format_from_filename(str(path))
    options.dxf_polygon_mode = DXF_POLYGON_MODE
    options.scale_factor = 0.001
    output.write(str(path), options)

    generated = f"L{OUTPUT_LAYER}D{OUTPUT_DATATYPE}_{OUTPUT_LAYER_NAME}"
    with open(path, encoding="utf-8", errors="strict") as stream:
        text = stream.read()
    with open(path, "w", encoding="utf-8", newline="") as stream:
        stream.write(text.replace(generated, OUTPUT_LAYER_NAME))


def lossless(original, horizontal, vertical) -> bool:
    """True when H | V reconstructs the original region with zero XOR area."""
    combined = horizontal + vertical
    combined.merge()
    return (original.dup().merge() ^ combined).area() == 0
