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

    Retained only for the docs-figure generator (make_figures.py); the production
    pipeline uses split_by_angle.
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


def _polygon_angle_deg(poly) -> float:
    """Angle of the polygon's longest edge, folded to (-90, +90]."""
    best_len2 = -1
    best = 0.0
    for edge in poly.each_edge():
        dx, dy = edge.dx(), edge.dy()
        length2 = dx * dx + dy * dy
        if length2 > best_len2:
            best_len2 = length2
            best = math.degrees(math.atan2(dy, dx))
    a = best % 180.0
    if a > 90.0:
        a -= 180.0
    return a


def _is_manhattan(poly) -> bool:
    """True when every edge is axis-aligned (a rectilinear cut / street network)."""
    return all(edge.dx() == 0 or edge.dy() == 0 for edge in poly.each_edge())


def split_by_angle(region, junction_aspect: float = JUNCTION_ASPECT,
                   quantum_deg: float = 0.5) -> dict:
    """Group a combined cut region by pass angle in [-90, +90]. Returns {angle: Region}.

    Generalizes split_horizontal_vertical to ANY cut angle. Each connected shape:
      * rectilinear (Manhattan) -> decomposed into rectangles, classified by long axis
        into 0 / 90 deg with crossing squares going to BOTH (identical to the H/V split,
        so street networks are unchanged); contributes to the 0.0 and/or 90.0 groups.
      * otherwise (a rotated line) -> assigned WHOLE to its longest-edge angle, quantized
        to `quantum_deg`, so a diagonal cut keeps its true angle.
    `(union of all groups)` reconstructs the input exactly -- see lossless_multi.
    """
    from collections import defaultdict
    groups = defaultdict(pya.Region)
    work = region.dup()
    work.merge()
    for poly in work.each():
        if _is_manhattan(poly):
            piece = pya.Region()
            piece.insert(poly)
            for shape in piece.decompose_trapezoids():
                rect = shape.polygon
                if rect is None:
                    rect = pya.Polygon(shape.bbox())
                box = shape.bbox()
                w, h = box.width(), box.height()
                if w == 0 or h == 0:
                    continue
                if w >= h * junction_aspect:
                    groups[0.0].insert(rect)
                elif h >= w * junction_aspect:
                    groups[90.0].insert(rect)
                else:                          # crossing -> both, so no line breaks
                    groups[0.0].insert(rect)
                    groups[90.0].insert(rect)
        else:
            key = round(_polygon_angle_deg(poly) / quantum_deg) * quantum_deg
            key = key + 0.0                    # normalize -0.0 -> 0.0
            if key == -90.0:
                key = 90.0                     # -90 and +90 are the same line direction
            groups[key].insert(poly)
    for reg in groups.values():
        reg.merge()
    return dict(groups)


def lossless_multi(original, regions) -> bool:
    """True when the union of `regions` reconstructs `original` with zero XOR area."""
    combined = pya.Region()
    for reg in regions:
        combined += reg
    combined.merge()
    return (original.dup().merge() ^ combined).area() == 0


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
