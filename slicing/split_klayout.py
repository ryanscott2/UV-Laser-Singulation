"""Split wafer-centered layer-0 cut geometry into laser jobs, in one of two modes.

`mode=four_windows` (default) is the pin-grid production profile: a 54 mm declared
field at the four `+/-25.4 mm` centers reached by the four-pin grid jig, one output
per station. `mode=center_pass` instead clips a single centered score job. Both
share the GLOBAL_*_OFFSET_UM calibration and every helper in this file.

Run inside KLayout or from its command line. DXF input is assumed to use
millimeter drawing units; GDS/OAS input uses the units stored in the file.
Each output job is translated so its physical laser-window center is (0, 0).

Four-window outputs are named for the JIG STATION that produces them, not for the
wafer area they expose. See `WINDOWS` for the mapping.
"""

from __future__ import annotations

import csv
import math
import os
from pathlib import Path

try:
    import pya
except ImportError:  # Standalone Python when the `klayout` wheel is installed.
    import klayout.db as pya


# =============================================================================
# USER SETTINGS - distances in microns unless explicitly marked otherwise
# =============================================================================

# Edit this path for normal GUI/macro use. Command-line `-rd input=...` wins.
INPUT_FILE = r"C:\path\to\wafer_cutlines.dxf"

# Blank means a `<source_name>_four_windows` folder beside the input file.
OUTPUT_DIR = r""

# Calibration applied to every output after it is centered on its laser field.
# Positive X moves all output geometry right; positive Y moves it up.
# 2026-08-14 RESET TO 0 for the stage-based method: the OptiScan III stage now moves
# the wafer under a fixed field, so the pinned-jig calibration (the +185.3/+438.0 um
# global residual and the per-station stitch nudges below) no longer applies. Fresh
# 2026-08-14 stage-method calibration from the 081326 v1 radial seam test (zero-offset
# cut, mark-from-flat 3000 um). Expected line-to-flat: major(-Y) 3.000 mm, minor(-X)
# 4.898 mm. Measured: major 3.69 mm, minor 1.32 mm. So the pattern landed +0.690 mm in
# +Y and -3.578 mm in X; correct by shifting the geometry back the other way (+X moves
# right / away from the -X minor flat; -Y moves down / toward the -Y major flat):
#   X = 4.898 - 1.320 = +3.578 mm ;  Y = 3.000 - 3.690 = -0.690 mm.
# 2026-08-14 iteration 2, from the calibrated 081326 v2 cut (radius 42.786, expected
# minor(-X) line 6.398 mm). Top half measured 6.16 mm, i.e. 0.238 mm too close to the
# minor flat, so global X += 237.6 -> 3815.2. Y left at -690 (not re-measured this round).
# 2026-08-14 iteration 3, from the calibrated 081326 v3 cut (radius 41.286, expected
# minor(-X) line 7.898 mm). Top half measured 7.99 mm, i.e. 0.092 mm too FAR from the
# minor flat, so global X -= 92.4 -> 3722.8. Global Y stepped 50 um further toward the
# major flat (-Y): -690 -> -740.
# 2026-08-14 iteration 4, from the calibrated 081426 v4 cut (radius 39.786, expected
# minor 9.398 / major 7.500 mm). Major measured 7.50 = spot on (Y converged, unchanged).
# Minor measured 9.45 = 0.052 mm too far, so global X -= 52.4 -> 3670.4.
# 2026-08-14 iteration 5, from the calibrated 081426 v5 cut (radius 38.286, expected
# minor 10.898 / major 9.000 mm). Major measured 9.00 = spot on (Y stays -740). Minor
# measured 10.83 = 0.068 mm too close, so global X += 67.6 -> 3738.0. Global-X residual
# is now bouncing in a ~+/-70 um band (-3578 -> -238 -> +92 -> +52 -> -68 across v1..v5),
# i.e. near the rig's cut-to-cut scatter; further global-X nudges are chasing that noise.
# History: 2026-08-13 pinned-jig recal was +185.3/+438.0 um; 2026-08-12 reset to 0 for
# the baked-offset jig; 2026-08-11 the 081126 test sat +3.017/-1.286 mm off. See
# CALIBRATION_AND_SLIDING_NEST_NOTES.md.
# 2026-08-14 zeroed for the stage method; then 2026-08-15 re-opened from BACK-SIDE
# (inverted wafer, secondary flat on the RIGHT) reads of the v6 seam test. Targets:
# major(-Y) 10.500, minor 12.397 mm.
#   iter1 (zero offset):   8.95 minor / 9.94 major -> both too close to their flats:
#          X = -(12.397-8.95)  = -3447 (LEFT; sign flipped vs usual convention, wafer inverted)
#          Y =  (10.500-9.94)  =  +560 (UP, away from the -Y major flat)
#   iter2 (at -3447/+560): 11.99 minor / 10.61 major:
#          X += -(12.397-11.99) = -407  -> -3854 (still a touch too close to the right minor flat)
#          Y +=  (10.500-10.61) = -110  ->  +450 (overshot; ease back toward the major flat)
#   iter3 (v5 read): the flat said add -598 -> -4452, but the ROUND-EDGE (OD) reads then showed the
#          flat was lying -- at X=-3447 (v6) the right mark is only +6 um off its nominal OD distance
#          (X centered), vs +276 um at -3854 (v5). The minor flat mis-references by ~370 um on this
#          wafer (flat ~18.4 mm), which drove -3854/-4452 the wrong way.
#   RECONCILED 2026-08-15: X reverts to -3447 (OD-correct); calibrate X on the round edge, not the
#          flat. Y held at +460 (the stabler major-flat value) pending a top+bottom OD read.
GLOBAL_X_OFFSET_UM = -3447.0
GLOBAL_Y_OFFSET_UM = 460.0

# Per-station nudge in microns, added on top of the global offset, keyed by folder
# label. Corrects one station measured off from its neighbours without disturbing
# the others. Override with -rd window_offsets="P1:0,-15;P4:2.5,-18".
#
# Stage-method stitch nudges. P1 (jig top-left -> bottom-right wafer tile) and P2 (jig
# top-right -> bottom-left) are the two BOTTOM-wafer tiles; P3/P4 are the TOP reference.
# 2026-08-14 v2 cut: bottom tiles ~10 um too far +X -> P1/P2 x = -10.
# 2026-08-14 v3 cut: bottom tiles a further ~10 um too far +X -> P1/P2 x = -20; and the
# bottom-right tile (P1) also ~10 um too far from the major flat -> P1 y = -10 (toward -Y).
# 2026-08-14 v4 cut: bottom tiles ~10 um too far +X -> P1/P2 x = -30. (A P2 y=-10 nudge
# was tried and then reverted, so P2 y stays 0; only P1 keeps a y nudge.)
# 2026-08-14 v5 cut: seams improving but sub-unity per nudge, so keep stepping: P1/P2
# x = -40; and P1 dropped a further 10 um toward the major flat -> P1 y = -20.
# Sign: nudge feeds the output translate directly (+x = right, +y = up), so negatives
# pull left / toward the major flat.
# 2026-08-15 back-side seam nudges (on top of the global), cumulative. Latest (v4 read; the
# global is converged -- X on the round edge, Y on the major flat -- so these are pure seam tuning):
#   P1 left 5 (-112.5 -> -117.5); P2 left+down 15 (-90,0 -> -105,-15); P4 up 15 (-25 -> -10);
#   P3 unchanged.
#   2026-08-14: P1 up 10 um net (-62.5 -> -47.5 -> -52.5).
WINDOW_OFFSETS_UM = {
    "P1": (-117.5, -52.5),
    "P2": (-105.0, -15.0),
    "P3": (0.0, -10.0),
    "P4": (0.0, -10.0),
}

# Optional edge bead: inset the cut geometry from the wafer edge before windowing,
# the same safe region the 10x30 master generator uses. 0 mm keeps the historical
# behaviour (no clip). Assumes a 100 mm wafer with the primary (major) flat facing
# -Y and the secondary (minor) flat facing -X. Override with -rd edge_bead_mm=2.0
EDGE_BEAD_MM = 0.0
WAFER_RADIUS_UM = 50_000.0
PRIMARY_FLAT_LENGTH_UM = 32_500.0
SECONDARY_FLAT_LENGTH_UM = 18_000.0
EDGE_BEAD_CIRCLE_SEGMENTS = 2048

# Which job this run produces. `four_windows` is the production four-station split;
# `center_pass` clips one centered score job instead. Both share the calibration
# GLOBAL_*_OFFSET_UM above and every helper below. Override with -rd mode=center_pass.
RUN_MODE = "four_windows"

# Center-pass mode only. The score fits the galvo's full max field; only the
# central 60 mm is qualified as usable (weaker at the edges).
FULL_FIELD_SIZE_UM = 78_485.0
SCORE_DIAMETER_UM = 75_000.0
SCORE_SHAPE = "circle"  # `circle` recommended; `square` also supported.
SCORE_CIRCLE_SEGMENTS = 256

# Native KLayout/DXF path widths larger than this are reduced about their
# existing centerlines before clipping. Filled polygons are geometry rather
# than paths and are intentionally left unchanged.
MAX_CUT_WIDTH_UM = 50.0

# Pin-grid production geometry. The jig moves exactly two 1 inch grid spaces
# (50.8 mm) between positions, which fixes the window centers. The field is the
# declared exposure window: 54 mm keeps 3 mm margin to every edge of the 60 mm
# usable field and leaves headroom above the 51 mm a partition window actually
# needs, so the stitch can be changed without resizing the field.
QUALIFIED_FIELD_SIZE_UM = 54_000.0
WINDOW_CENTER_X_UM = 25_400.0
WINDOW_CENTER_Y_UM = 25_400.0

# `partition` gives each quadrant one owner and adds the stitch overlap at the
# seams, so a window is only as large as its own half of the pitch plus the
# overlap. `full_window` takes the whole declared field instead, which at a 54 mm
# field means neighbours overlap by 3.2 mm and that whole band is exposed twice.
CLIP_MODE = "partition"  # `partition` or `full_window`

# Total overlap across the X=0 and Y=0 stitch lines in partition mode. 400 um
# extends each neighbouring job 200 um past the nominal seam -- doubled from 200 um
# to give the tiles more overlap against jig re-seat error, and it still covers the
# 75-100 um seam mismatch recorded in CALIBRATION_AND_SLIDING_NEST_NOTES.md.
# Scoring partway through the wafer makes a small double-exposed band harmless.
STITCH_OVERLAP_UM = 400.0

# Source and output layer. DXF layer "0" normally imports as layer 0/datatype 0.
SOURCE_LAYER = 0
SOURCE_DATATYPE = 0

# Which layer holds the cutlines. Blank keeps the historical behaviour: numeric
# layer 0/0, or a layer literally named "0". Otherwise accepts "7", "7/2", or a
# layer name such as "CUT". Override with -rd source_layer=...
SOURCE_LAYER_SPEC = ""

# `cap` reduces paths wider than the width below and leaves narrower ones alone.
# `force` sets every path to exactly that width, widening as well as narrowing.
# Neither touches filled polygons, which carry their drawn size as geometry.
CUT_WIDTH_MODE = "cap"  # `cap` or `force`
OUTPUT_LAYER = 0
OUTPUT_DATATYPE = 0
OUTPUT_LAYER_NAME = "0"

# The laser places drawings at their true coordinates with auto-centering OFF, so
# each job's DXF origin lands on the field center. The splitter writes every tile
# with its field center at the origin, so this reproduces the wafer exactly;
# validate_pin_grid_set.py carries a field-placement self-test that proves it.

# Geometry lying outside all four windows would be dropped without a trace, so
# the run stops instead. Set true only when clipping the pattern is intended.
ALLOW_GEOMETRY_OUTSIDE_FIELDS = False

# Comparison tolerance for the field/window geometry checks, in microns.
GEOMETRY_TOLERANCE_UM = 1e-6

# DXF drawing units: the supplied references use 1 unit = 1 mm = 1000 um.
INPUT_DXF_UNIT_UM = 1_000.0
OUTPUT_EXTENSION = ".dxf"  # `.dxf`, `.gds`, or `.oas`

# DXF writer mode 1 produces closed LWPOLYLINE entities.
DXF_POLYGON_MODE = 1


# =============================================================================
# IMPLEMENTATION
# =============================================================================

# Output labels name the jig station and read like a matrix: the first digit is
# the row from the table rear ("top"), the second the column from the table left.
# Indexing the jig moves the wafer, not the laser, so a station exposes the
# OPPOSITE wafer quadrant - the top-left station exposes the wafer's
# bottom-right. Both axes invert; do not drop the sign flip in either one.
WINDOWS = (
    # Output label, then the exposed-field X/Y ownership signs in wafer coordinates.
    ("P1_jig_top_left", +1, -1),
    ("P2_jig_top_right", -1, -1),
    ("P3_jig_bottom_right", -1, +1),
    ("P4_jig_bottom_left", +1, +1),
)


def quadrant_name(x_sign: int, y_sign: int) -> str:
    """Name the quadrant a sign pair points at, in `<row>_<column>` order."""
    return f"{'top' if y_sign > 0 else 'bottom'}_{'right' if x_sign > 0 else 'left'}"


def runtime_value(name: str, default):
    """Read a KLayout `-rd name=value` variable when one was supplied."""
    return globals().get(name, default)


def as_float(name: str, default: float) -> float:
    return float(runtime_value(name, default))


def as_bool(name: str, default: bool) -> bool:
    value = runtime_value(name, default)
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true/false or 1/0, got {value!r}")


def window_folder(name: str) -> str:
    """`P1_jig_top_left` -> `P1`, the folder the operator sees."""
    return name.split("_", 1)[0]


def parse_window_offsets(spec) -> dict[str, tuple[float, float]]:
    """Read `P1:0,-15;P4:2.5,-18` into per-folder micron offsets.

    A mapping is accepted unchanged, so the module default passes straight
    through. Unknown labels are rejected rather than silently ignored, because a
    typo would otherwise leave a station un-nudged with no symptom.
    """
    known = {window_folder(name) for name, _, _ in WINDOWS}
    if isinstance(spec, dict):
        pairs = {str(k): tuple(v) for k, v in spec.items()}
    else:
        pairs = {}
        for chunk in str(spec).replace(",", ",").split(";"):
            chunk = chunk.strip()
            if not chunk:
                continue
            label, _, values = chunk.partition(":")
            parts = [p for p in values.split(",") if p.strip() != ""]
            if len(parts) != 2:
                raise ValueError(
                    f"window_offsets entry {chunk!r} must look like P1:<x_um>,<y_um>"
                )
            pairs[label.strip()] = (float(parts[0]), float(parts[1]))

    unknown = sorted(set(pairs) - known)
    if unknown:
        raise ValueError(
            f"window_offsets names unknown station(s) {unknown}; expected any of {sorted(known)}"
        )
    return {folder: tuple(float(v) for v in pairs.get(folder, (0.0, 0.0)))
            for folder in sorted(known)}


def parse_layer_spec(spec) -> tuple[int | None, int | None, str | None]:
    """Read a layer selector: blank, `7`, `7/2`, or a layer name like `CUT`."""
    text = str(spec).strip()
    if not text:
        return None, None, None
    if "/" in text:
        layer_part, datatype_part = text.split("/", 1)
        try:
            return int(layer_part), int(datatype_part), None
        except ValueError:
            return None, None, text
    try:
        return int(text), 0, None
    except ValueError:
        return None, None, text


def describe_layer_spec(spec) -> str:
    layer, datatype, name = spec
    if name is not None:
        return f"name {name!r}"
    if layer is None:
        return f"default ({SOURCE_LAYER}/{SOURCE_DATATYPE} or a layer named '{SOURCE_LAYER}')"
    return f"{layer}/{datatype}"


def layer_matches(info, spec) -> bool:
    layer, datatype, name = spec
    info_name = str(getattr(info, "name", "") or "")
    if name is not None:
        return info_name == name
    if layer is None:
        # Historical default: numeric 0/0, or a layer literally named "0".
        numeric = info.layer == SOURCE_LAYER and info.datatype == SOURCE_DATATYPE
        return numeric or info_name in {str(SOURCE_LAYER), OUTPUT_LAYER_NAME}
    return (info.layer == layer and info.datatype == datatype) or info_name == str(layer)


def apply_source_path_widths(
    layout, layer_indices, width_um: float, mode: str
) -> dict[str, float | int | str]:
    """Set native path widths in-place, preserving each path's centerline.

    `cap` only narrows paths wider than `width_um`. `force` sets every path to
    exactly that width. Filled polygons are geometry rather than paths and carry
    their drawn size, so neither mode can change them; `paths_seen` is reported so
    a caller can tell the width control had nothing to act on.
    """
    if mode not in {"cap", "force"}:
        raise ValueError("CUT_WIDTH_MODE must be 'cap' or 'force'")
    target_dbu = um_to_dbu(layout, width_um)
    if target_dbu < 1:
        raise ValueError(
            f"cut width {width_um} um is smaller than the {layout.dbu} um layout grid"
        )

    to_change = []
    paths_seen = 0
    widest_original_dbu = 0
    for cell in layout.each_cell():
        for layer_index in layer_indices:
            for shape in cell.each_shape(layer_index):
                if not shape.is_path():
                    continue
                width_dbu = abs(int(shape.path_width))
                paths_seen += 1
                widest_original_dbu = max(widest_original_dbu, width_dbu)
                if width_dbu > target_dbu or (mode == "force" and width_dbu != target_dbu):
                    to_change.append(shape)

    # Changing a shape can invalidate its container iterator, so widths are
    # updated only after all iterators have finished.
    for shape in to_change:
        shape.path_width = target_dbu

    return {
        "paths_seen": paths_seen,
        "paths_capped": len(to_change),
        "width_mode": mode,
        "widest_original_um": dbu_to_um(layout, widest_original_dbu),
    }


def region_from_source(
    layout, max_width_um: float, spec, width_mode: str
) -> tuple[object, list[str], dict[str, float | int | str]]:
    matching_indices = []
    matching_names = []
    for layer_index in layout.layer_indices():
        info = layout.get_info(layer_index)
        if layer_matches(info, spec):
            matching_indices.append(layer_index)
            matching_names.append(str(info))

    if not matching_indices:
        available = ", ".join(str(layout.get_info(i)) for i in layout.layer_indices())
        raise RuntimeError(
            f"No source layer matching {describe_layer_spec(spec)} found. "
            f"Available layers: {available or '<none>'}"
        )

    width_stats = apply_source_path_widths(layout, matching_indices, max_width_um, width_mode)

    result = pya.Region()
    for top_cell in layout.top_cells():
        for layer_index in matching_indices:
            result += pya.Region(top_cell.begin_shapes_rec(layer_index))
    if result.is_empty():
        raise RuntimeError("The selected layer exists but contains no polygonal cut geometry")
    return result, matching_names, width_stats


def um_to_dbu(layout, value_um: float) -> int:
    return int(round(value_um / layout.dbu))


def dbu_to_um(layout, value_dbu: int) -> float:
    return value_dbu * layout.dbu


def region_bbox_um(layout, region) -> tuple[float, float, float, float] | None:
    if region.is_empty():
        return None
    box = region.bbox()
    return tuple(dbu_to_um(layout, value) for value in (box.left, box.bottom, box.right, box.top))


def safe_wafer_region(layout, edge_bead_um: float):
    """Circle inset by the bead and clipped by both flats -- the same safe region
    the master generator builds, so an entered edge bead removes cut geometry
    inside the bead of the wafer edge. Shared with the preview via the namespace."""
    safe_radius = WAFER_RADIUS_UM - edge_bead_um
    primary_depth = math.sqrt(WAFER_RADIUS_UM**2 - (PRIMARY_FLAT_LENGTH_UM / 2.0) ** 2)
    secondary_depth = math.sqrt(WAFER_RADIUS_UM**2 - (SECONDARY_FLAT_LENGTH_UM / 2.0) ** 2)
    safe_primary_y = -primary_depth + edge_bead_um
    safe_secondary_x = -secondary_depth + edge_bead_um
    n = EDGE_BEAD_CIRCLE_SEGMENTS
    radius_dbu = um_to_dbu(layout, safe_radius)
    circle = pya.Region(pya.Polygon([
        pya.Point(int(round(radius_dbu * math.cos(2.0 * math.pi * i / n))),
                  int(round(radius_dbu * math.sin(2.0 * math.pi * i / n))))
        for i in range(n)
    ]))
    flat_limits = pya.Region(pya.Box(
        um_to_dbu(layout, safe_secondary_x), um_to_dbu(layout, safe_primary_y),
        um_to_dbu(layout, safe_radius + 1_000.0), um_to_dbu(layout, safe_radius + 1_000.0),
    ))
    return circle & flat_limits


def set_line_widths(region, width_um, mode, dbu):
    """Resize filled Manhattan cut polygons so each run is `width_um` wide.

    Filled polygons carry no path width to cap or force, so this sets the width
    geometrically: split the region into horizontal and vertical runs (crossings
    shared, so nothing breaks), then set each run's short side, keeping its
    centerline and long axis. `mode` 'force' sets every run; otherwise only runs
    already wider are narrowed. Assumes axis-aligned cuts."""
    target = int(round(width_um / dbu))
    aspect = 1.25
    horizontal = pya.Region()
    vertical = pya.Region()
    for shape in region.decompose_trapezoids():
        box = shape.bbox()
        w, h = box.width(), box.height()
        if w == 0 or h == 0:
            continue
        poly = shape.polygon
        if poly is None:
            poly = pya.Polygon(box)
        if w >= h * aspect:
            horizontal.insert(poly)
        elif h >= w * aspect:
            vertical.insert(poly)
        else:
            horizontal.insert(poly)
            vertical.insert(poly)
    horizontal.merge()
    vertical.merge()

    out = pya.Region()
    for shape in horizontal.decompose_trapezoids():
        box = shape.bbox()
        new = box.height() if (mode != "force" and box.height() <= target) else target
        low = int(round((box.bottom + box.top) / 2.0 - new / 2.0))
        out.insert(pya.Box(box.left, low, box.right, low + new))
    for shape in vertical.decompose_trapezoids():
        box = shape.bbox()
        new = box.width() if (mode != "force" and box.width() <= target) else target
        low = int(round((box.left + box.right) / 2.0 - new / 2.0))
        out.insert(pya.Box(low, box.bottom, low + new, box.top))
    out.merge()
    return out


def score_clip_region(layout, shape: str, diameter_um: float):
    """Center-pass clip: a centered circle (or square) of the score diameter."""
    radius_dbu = um_to_dbu(layout, diameter_um / 2.0)
    if shape == "square":
        return pya.Region(pya.Box(-radius_dbu, -radius_dbu, radius_dbu, radius_dbu))
    if shape != "circle":
        raise ValueError("SCORE_SHAPE must be 'circle' or 'square'")
    n = SCORE_CIRCLE_SEGMENTS
    return pya.Region(pya.Polygon([
        pya.Point(int(round(radius_dbu * math.cos(2.0 * math.pi * i / n))),
                  int(round(radius_dbu * math.sin(2.0 * math.pi * i / n))))
        for i in range(n)
    ]))


def partition_window_size_um(stitch_um: float) -> float:
    """How wide a partition window is: its own half of the pitch, plus the overlap.

    A window reaches from `stitch/2` across the seam out to the same distance on
    the far side of its center, so its span is `2 * WINDOW_CENTER + stitch`. This
    is deliberately independent of the declared field: the field only has to be
    large enough to contain it, which lets the stitch be retuned without resizing
    the exposure window or moving anything off center.
    """
    return 2.0 * WINDOW_CENTER_X_UM + stitch_um


def clip_bounds_um(x_sign: int, y_sign: int, mode: str, stitch_um: float):
    half_field = QUALIFIED_FIELD_SIZE_UM / 2.0
    center_x = x_sign * WINDOW_CENTER_X_UM
    center_y = y_sign * WINDOW_CENTER_Y_UM

    if mode == "full_window":
        return (center_x - half_field, center_y - half_field,
                center_x + half_field, center_y + half_field)
    if mode != "partition":
        raise ValueError("CLIP_MODE must be 'partition' or 'full_window'")

    # Symmetric about the window center by construction, so the geometry always
    # lands centered in the field no matter what the stitch is set to.
    half_window = partition_window_size_um(stitch_um) / 2.0
    return (center_x - half_window, center_y - half_window,
            center_x + half_window, center_y + half_window)


def validate_field_geometry(mode: str, stitch_um: float) -> None:
    """Check the window fits the declared field, and that the tiling is symmetric.

    The window centers are set by the jig's two-grid-space move, so a partition
    window spans `2 * WINDOW_CENTER + stitch`. The declared field has to be at
    least that wide or the geometry would reach outside the window the laser is
    told to expose - at 54 mm of field the stitch can go up to 3200 um before that
    happens. Both axes must share a center, otherwise the four windows are not a
    symmetric 2 x 2 tiling of one square field.
    """
    if WINDOW_CENTER_X_UM != WINDOW_CENTER_Y_UM:
        raise ValueError(
            "WINDOW_CENTER_X_UM and WINDOW_CENTER_Y_UM differ, so the four windows "
            "cannot be a symmetric 2 x 2 tiling of one square field"
        )
    if stitch_um < 0:
        raise ValueError("STITCH_OVERLAP_UM cannot be negative")
    if mode != "partition":
        return
    needed = partition_window_size_um(stitch_um)
    if needed > QUALIFIED_FIELD_SIZE_UM + GEOMETRY_TOLERANCE_UM:
        raise ValueError(
            f"a partition window is {needed} um wide "
            f"(2 * {WINDOW_CENTER_X_UM} + {stitch_um}) but QUALIFIED_FIELD_SIZE_UM is "
            f"{QUALIFIED_FIELD_SIZE_UM}, so geometry would fall outside the declared "
            f"exposure window. Raise the field to at least {needed}, or drop the "
            f"stitch to at most {QUALIFIED_FIELD_SIZE_UM - 2.0 * WINDOW_CENTER_X_UM}."
        )


def assert_window_is_square(name: str, bounds, center_x: float, center_y: float,
                            expected_size_um: float) -> None:
    """Every emitted window must be square and centered on its own field center."""
    left, bottom, right, top = bounds
    width, height = right - left, top - bottom
    if abs(width - height) > GEOMETRY_TOLERANCE_UM:
        raise RuntimeError(f"{name}: window {width} x {height} um is not square")
    if abs(width - expected_size_um) > GEOMETRY_TOLERANCE_UM:
        raise RuntimeError(
            f"{name}: window is {width} um wide, expected {expected_size_um} um"
        )
    if width > QUALIFIED_FIELD_SIZE_UM + GEOMETRY_TOLERANCE_UM:
        raise RuntimeError(
            f"{name}: window {width} um exceeds the declared field "
            f"{QUALIFIED_FIELD_SIZE_UM} um"
        )
    # After translation the window must straddle the laser origin symmetrically.
    local_left, local_right = left - center_x, right - center_x
    local_bottom, local_top = bottom - center_y, top - center_y
    if (abs(local_left + local_right) > GEOMETRY_TOLERANCE_UM
            or abs(local_bottom + local_top) > GEOMETRY_TOLERANCE_UM):
        raise RuntimeError(
            f"{name}: window is not concentric with its field; after centering it "
            f"spans X {local_left}..{local_right}, Y {local_bottom}..{local_top} um"
        )


def clip_union_region(layout, mode: str, stitch_um: float):
    """The union of all four windows: everything the four jobs can reach."""
    union = pya.Region()
    for _, x_sign, y_sign in WINDOWS:
        left, bottom, right, top = clip_bounds_um(x_sign, y_sign, mode, stitch_um)
        union.insert(
            pya.Box(
                um_to_dbu(layout, left),
                um_to_dbu(layout, bottom),
                um_to_dbu(layout, right),
                um_to_dbu(layout, top),
            )
        )
    return union.merged()


def dbu_area_to_mm2(layout, area_dbu: int) -> float:
    return area_dbu * (layout.dbu**2) / 1_000_000.0


def write_dxf_r2010(output_path: Path, region, dbu: float) -> None:
    """Write the cut polygons as the DXF the laser tools expect: AutoCAD 2010
    (R2010), millimeter units ($INSUNITS = 4), closed LWPOLYLINEs on layer '0'.

    KLayout's DXF writer cannot set the version or the units header, so ezdxf does
    it. Coordinates are emitted in millimeters (1 DXF unit = 1 mm), matching the
    source convention.
    """
    import ezdxf  # lazy: only DXF output needs it

    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 4  # 4 = millimeters
    msp = doc.modelspace()
    scale = dbu / 1000.0  # database units -> mm
    for poly in region.each():
        rings = [poly.each_point_hull()]
        for hole in range(poly.holes()):
            rings.append(poly.each_point_hole(hole))
        for ring in rings:
            points = [(p.x * scale, p.y * scale) for p in ring]
            if points:
                msp.add_lwpolyline(
                    points, close=True, dxfattribs={"layer": OUTPUT_LAYER_NAME}
                )
    doc.saveas(str(output_path))


def write_layout(
    output_path: Path,
    source_layout,
    region,
    cell_name: str,
) -> None:
    if output_path.suffix.lower() == ".dxf":
        # DXF is the laser format: write it as AutoCAD 2010 with mm units via ezdxf,
        # which KLayout's DXF writer cannot do. GDS/OAS still go through KLayout.
        write_dxf_r2010(output_path, region, source_layout.dbu)
        return

    output_layout = pya.Layout()
    output_layout.dbu = source_layout.dbu
    cell = output_layout.create_cell(cell_name)
    layer_info = pya.LayerInfo(OUTPUT_LAYER, OUTPUT_DATATYPE)
    layer_info.name = OUTPUT_LAYER_NAME
    output_layer = output_layout.layer(layer_info)
    cell.shapes(output_layer).insert(region)

    options = pya.SaveLayoutOptions()
    options.set_format_from_filename(str(output_path))
    output_layout.write(str(output_path), options)


def run_center_pass(layout, source_region, source_layers, width_stats, input_file,
                    output_dir, extension, global_x_um, global_y_um,
                    max_cut_width_um, edge_bead_mm) -> None:
    """`mode=center_pass`: clip the source to one centered score job, offset it by
    the shared calibration, and write a single output plus a log."""
    diameter = as_float("score_diameter_um", SCORE_DIAMETER_UM)
    shape = str(runtime_value("score_shape", SCORE_SHAPE)).strip().lower()
    if diameter <= 0 or diameter > FULL_FIELD_SIZE_UM:
        raise ValueError(f"score_diameter_um must be > 0 and <= {FULL_FIELD_SIZE_UM} um")

    clipped = source_region & score_clip_region(layout, shape, diameter)
    clipped.transform(pya.Trans(um_to_dbu(layout, global_x_um), um_to_dbu(layout, global_y_um)))

    output_path = output_dir / f"{input_file.stem}_center_pass{extension}"
    write_layout(output_path, layout, clipped, "CENTER_PASS")

    log_path = output_dir / f"{input_file.stem}_center_pass_log.txt"
    log_path.write_text(
        "\n".join((
            f"Input: {input_file}",
            f"Input layers: {', '.join(source_layers)}",
            f"Output: {output_path}",
            "Mode: center_pass",
            f"Score shape: {shape}",
            f"Score diameter (um): {diameter}",
            f"Full field (um): {FULL_FIELD_SIZE_UM} (only the central 60 mm is qualified as usable)",
            f"Global offset (um): X={global_x_um}, Y={global_y_um}",
            f"Edge bead (mm): {edge_bead_mm}",
            f"Cut width (um): {max_cut_width_um}, mode={width_stats['width_mode']}",
            "Source native paths: "
            f"seen={width_stats['paths_seen']}, changed={width_stats['paths_capped']}",
            f"Source polygons: {source_region.count()}",
            f"Output polygons: {clipped.count()}",
            f"Output bbox (um): {region_bbox_um(layout, clipped)}",
        )) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote center-pass job: {output_path}")


def main() -> None:
    run_mode = str(runtime_value("mode", RUN_MODE)).strip().lower()
    input_file = Path(str(runtime_value("input", INPUT_FILE))).expanduser()
    if not input_file.is_file():
        raise FileNotFoundError(
            f"Input file not found: {input_file}\n"
            "Edit INPUT_FILE near the top of this script or pass -rd input=<path>."
        )

    configured_output = str(runtime_value("output_dir", OUTPUT_DIR)).strip()
    default_suffix = "_center_pass" if run_mode == "center_pass" else "_four_windows"
    output_dir = (
        Path(configured_output).expanduser()
        if configured_output
        else input_file.with_name(f"{input_file.stem}{default_suffix}")
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    global_x_um = as_float("global_x_um", GLOBAL_X_OFFSET_UM)
    global_y_um = as_float("global_y_um", GLOBAL_Y_OFFSET_UM)
    max_cut_width_um = as_float("max_cut_width_um", MAX_CUT_WIDTH_UM)
    source_spec = parse_layer_spec(runtime_value("source_layer", SOURCE_LAYER_SPEC))
    width_mode = str(runtime_value("cut_width_mode", CUT_WIDTH_MODE)).strip().lower()
    extension = str(runtime_value("output_extension", OUTPUT_EXTENSION)).strip().lower()
    if not extension.startswith("."):
        extension = "." + extension
    if max_cut_width_um <= 0:
        raise ValueError("MAX_CUT_WIDTH_UM must be greater than zero")

    layout = pya.Layout()
    if input_file.suffix.lower() == ".dxf":
        load_options = pya.LoadLayoutOptions()
        load_options.dxf_unit = INPUT_DXF_UNIT_UM
        layout.read(str(input_file), load_options)
    else:
        layout.read(str(input_file))

    source_region, source_layers, width_stats = region_from_source(
        layout, max_cut_width_um, source_spec, width_mode
    )
    # Paths carry a width to cap or force; filled polygons do not, so `force`
    # resizes them geometrically to the requested width. `cap` leaves polygons as
    # drawn, which keeps the combined front end and the 50 um masters untouched.
    if width_mode == "force" and width_stats["paths_seen"] == 0:
        source_region = set_line_widths(source_region, max_cut_width_um, "force", layout.dbu)
    edge_bead_mm = as_float("edge_bead_mm", EDGE_BEAD_MM)
    if edge_bead_mm > 0:
        source_region = source_region & safe_wafer_region(layout, edge_bead_mm * 1000.0)

    if run_mode == "center_pass":
        run_center_pass(layout, source_region, source_layers, width_stats, input_file,
                        output_dir, extension, global_x_um, global_y_um,
                        max_cut_width_um, edge_bead_mm)
        return

    # ----------------------------------------------------------- four-window mode
    stitch_um = as_float("stitch_overlap_um", STITCH_OVERLAP_UM)
    mode = str(runtime_value("clip_mode", CLIP_MODE)).strip().lower()
    window_offsets = parse_window_offsets(runtime_value("window_offsets", WINDOW_OFFSETS_UM))
    allow_outside = as_bool("allow_geometry_outside_fields", ALLOW_GEOMETRY_OUTSIDE_FIELDS)
    validate_field_geometry(mode, stitch_um)
    source_bbox = region_bbox_um(layout, source_region)
    manifest_rows = []

    # Anything outside every window is silently discarded by the clip below, so
    # measure it first. A pattern larger than the four fields loses geometry with
    # no other symptom: four healthy-looking square files and a zero exit code.
    windows_union = clip_union_region(layout, mode, stitch_um)
    dropped = source_region.merged() - windows_union
    dropped_area_dbu = dropped.area()
    dropped_bbox = region_bbox_um(layout, dropped)
    dropped_area_mm2 = dbu_area_to_mm2(layout, dropped_area_dbu)
    source_area_mm2 = dbu_area_to_mm2(layout, source_region.merged().area())
    if dropped_area_dbu > 0 and not allow_outside:
        union_bbox = region_bbox_um(layout, windows_union)
        raise RuntimeError(
            f"{dropped_area_mm2:.6f} mm^2 of cut geometry "
            f"({100.0 * dropped_area_dbu / max(source_region.merged().area(), 1):.2f}% "
            "of the source) lies outside all four windows and would be discarded.\n"
            f"  source bounds (um):  {source_bbox}\n"
            f"  window union (um):   {union_bbox}\n"
            f"  dropped bounds (um): {dropped_bbox}\n"
            "The four windows cannot reach this pattern. Either enlarge "
            "QUALIFIED_FIELD_SIZE_UM and WINDOW_CENTER_*_UM to cover it, or pass "
            "-rd allow_geometry_outside_fields=1 if clipping it away is intended."
        )

    empty_jobs: list[str] = []
    for name, x_sign, y_sign in WINDOWS:
        field_center_x = x_sign * WINDOW_CENTER_X_UM
        field_center_y = y_sign * WINDOW_CENTER_Y_UM
        bounds = clip_bounds_um(x_sign, y_sign, mode, stitch_um)
        assert_window_is_square(
            name, bounds, field_center_x, field_center_y,
            QUALIFIED_FIELD_SIZE_UM if mode == "full_window"
            else partition_window_size_um(stitch_um),
        )
        left, bottom, right, top = bounds
        clip_box = pya.Box(
            um_to_dbu(layout, left),
            um_to_dbu(layout, bottom),
            um_to_dbu(layout, right),
            um_to_dbu(layout, top),
        )
        clipped = source_region & pya.Region(clip_box)

        nudge_x, nudge_y = window_offsets[window_folder(name)]
        translate_x_um = -field_center_x + global_x_um + nudge_x
        translate_y_um = -field_center_y + global_y_um + nudge_y
        clipped.transform(
            pya.Trans(
                um_to_dbu(layout, translate_x_um),
                um_to_dbu(layout, translate_y_um),
            )
        )

        # A job with no cut geometry still writes a placed, correctly sized file,
        # which looks identical to a real one at the machine. Say so out loud.
        if clipped.is_empty():
            empty_jobs.append(name)

        output_path = output_dir / f"{input_file.stem}_{name}{extension}"
        write_layout(
            output_path,
            layout,
            clipped,
            name.upper(),
        )
        bbox = region_bbox_um(layout, clipped)
        manifest_rows.append(
            {
                "job": name,
                "output_file": output_path.name,
                # The jig moves opposite the area it exposes.
                "jig_station": quadrant_name(-x_sign, -y_sign),
                "exposed_wafer_area": quadrant_name(x_sign, y_sign),
                "field_center_x_wafer_um": field_center_x,
                "field_center_y_wafer_um": field_center_y,
                "clip_left_um": left,
                "clip_bottom_um": bottom,
                "clip_right_um": right,
                "clip_top_um": top,
                "output_translate_x_um": translate_x_um,
                "output_translate_y_um": translate_y_um,
                "max_cut_width_um": max_cut_width_um,
                "cut_width_mode": width_stats["width_mode"],
                "station_offset_x_um": nudge_x,
                "station_offset_y_um": nudge_y,
                "source_layer_selector": describe_layer_spec(source_spec),
                "source_paths_capped": width_stats["paths_capped"],
                "output_bbox_um": "" if bbox is None else ";".join(f"{v:.3f}" for v in bbox),
                "polygon_count": clipped.count(),
                "has_cut_geometry": not clipped.is_empty(),
            }
        )

    manifest_path = output_dir / f"{input_file.stem}_window_manifest.csv"
    with manifest_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=manifest_rows[0].keys())
        writer.writeheader()
        writer.writerows(manifest_rows)

    log_path = output_dir / f"{input_file.stem}_split_log.txt"
    with log_path.open("w", encoding="utf-8") as stream:
        stream.write(f"Input: {input_file}\n")
        stream.write(f"Input layers: {', '.join(source_layers)}\n")
        stream.write(f"Layout DBU: {layout.dbu} um\n")
        stream.write(f"Source bbox (um): {source_bbox}\n")
        stream.write(f"Mode: {mode}\n")
        stream.write(f"Global offset (um): X={global_x_um}, Y={global_y_um}\n")
        stream.write(
            "Per-station offsets (um): "
            + ", ".join(f"{label}=({x:g},{y:g})"
                        for label, (x, y) in sorted(window_offsets.items()))
            + "\n"
        )
        stream.write(f"Source layer selector: {describe_layer_spec(source_spec)}\n")
        stream.write(
            f"Cut width (um): {max_cut_width_um}, mode={width_stats['width_mode']}\n"
        )
        stream.write(
            "Source native paths: "
            f"seen={width_stats['paths_seen']}, changed={width_stats['paths_capped']}, "
            f"widest_original_um={width_stats['widest_original_um']}\n"
        )
        stream.write(f"Stitch overlap (um): {stitch_um}\n")
        window_size_um = (QUALIFIED_FIELD_SIZE_UM if mode == "full_window"
                          else partition_window_size_um(stitch_um))
        stream.write(
            f"Declared field (mm): {QUALIFIED_FIELD_SIZE_UM / 1000.0:.3f}; "
            f"window per job (mm): {window_size_um / 1000.0:.3f}; "
            "verified square and concentric with its field\n"
        )
        stream.write(
            f"Jobs with no cut geometry: {', '.join(empty_jobs) if empty_jobs else 'none'}\n"
        )
        stream.write(
            "Coverage: source "
            f"{source_area_mm2:.6f} mm^2, dropped outside all windows "
            f"{dropped_area_mm2:.6f} mm^2"
            + (f" (ALLOWED, bounds_um={dropped_bbox})" if dropped_area_dbu > 0 else "")
            + "\n"
        )
        stream.write(f"Output directory: {output_dir}\n")
        stream.write("Labels name the jig station; each exposes the opposite quadrant\n")
        for row in manifest_rows:
            stream.write(
                f"{row['job']}: jig={row['jig_station']}, "
                f"exposes={row['exposed_wafer_area']}, "
                f"polygons={row['polygon_count']}, "
                f"bbox_um={row['output_bbox_um']}\n"
            )

    if empty_jobs:
        print(
            f"WARNING: {len(empty_jobs)} of {len(WINDOWS)} jobs contain no cut geometry: "
            f"{', '.join(empty_jobs)}.\n"
            "         Those files are still placed and correctly sized, so they look "
            "like the others at the machine.\n"
            "         Check the source covers all four quadrants before exposing."
        )
    print(f"Wrote four window jobs and manifest to: {output_dir}")


if __name__ == "__main__":
    main()
