"""Split wafer-centered layer-0 cut geometry into four laser-window jobs.

This is the pin-grid production profile: a 52 mm field at the four
`+/-25.4 mm` centers reached by the eight-pin grid jig.

Run inside KLayout or from its command line. DXF input is assumed to use
millimeter drawing units; GDS/OAS input uses the units stored in the file.
Each output job is translated so its physical laser-window center is (0, 0).

Outputs are named for the JIG STATION that produces them, not for the wafer
area they expose. See `WINDOWS` for the mapping.
"""

from __future__ import annotations

import csv
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
GLOBAL_X_OFFSET_UM = 0.0
GLOBAL_Y_OFFSET_UM = 0.0

# Native KLayout/DXF path widths larger than this are reduced about their
# existing centerlines before clipping. Filled polygons are geometry rather
# than paths and are intentionally left unchanged.
MAX_CUT_WIDTH_UM = 50.0

# Pin-grid production geometry. The jig moves exactly two 1 inch grid spaces
# (50.8 mm) between positions. A 52 mm field leaves 1.2 mm total seam overlap
# while retaining 13.2425 mm margin to every edge of the 78.485 mm optical field.
QUALIFIED_FIELD_SIZE_UM = 52_000.0
WINDOW_CENTER_X_UM = 25_400.0
WINDOW_CENTER_Y_UM = 25_400.0

# `partition` gives each quadrant one owner and adds the stitch overlap at the
# seams. `full_window` takes the whole field instead. Note that while the field
# equals 2 * WINDOW_CENTER + STITCH_OVERLAP the two are the SAME box, because the
# fields overlap by exactly the stitch and nothing more; the setting only starts
# to matter if the field is made larger than that.
CLIP_MODE = "partition"  # `partition` or `full_window`

# Total overlap across the X=0 and Y=0 stitch lines in partition mode. The
# default 1200 um extends each neighboring job 600 um across the nominal seam.
STITCH_OVERLAP_UM = 1_200.0

# Source and output layer. DXF layer "0" normally imports as layer 0/datatype 0.
SOURCE_LAYER = 0
SOURCE_DATATYPE = 0
OUTPUT_LAYER = 0
OUTPUT_DATATYPE = 0
OUTPUT_LAYER_NAME = "0"

# Keep every exported job registered to the same 52 x 52 mm canvas even when
# the downstream laser software centers drawings from their content bounds.
# The four small corner anchors are deliberately placed on a separate layer:
# configure the laser to NEVER expose this layer. Cutting geometry remains on
# layer 0. This also stabilizes GDS/OAS cell bounding boxes.
ADD_IMPORT_REGISTRATION_ENVELOPE = True
REGISTRATION_LAYER = 999
REGISTRATION_DATATYPE = 0
REGISTRATION_LAYER_NAME = "REGISTRATION_DO_NOT_EXPOSE"
REGISTRATION_HALF_SIZE_UM = QUALIFIED_FIELD_SIZE_UM / 2.0
REGISTRATION_ANCHOR_SIZE_UM = 50.0

# Declare the window in the DXF header as well, so an importer does not have to
# infer it from entities. This works even where the registration anchors do not,
# because it does not depend on the laser counting a non-marking layer.
WRITE_DXF_HEADER_EXTENTS = True

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
    ("DXF11_jig_top_left", +1, -1),
    ("DXF12_jig_top_right", -1, -1),
    ("DXF21_jig_bottom_left", +1, +1),
    ("DXF22_jig_bottom_right", -1, +1),
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


def layer_matches(info) -> bool:
    numeric_match = info.layer == SOURCE_LAYER and info.datatype == SOURCE_DATATYPE
    name = str(getattr(info, "name", "") or "")
    return numeric_match or name == str(SOURCE_LAYER) or name == OUTPUT_LAYER_NAME


def cap_source_path_widths(layout, layer_indices, max_width_um: float) -> dict[str, float | int]:
    """Cap path widths in-place while preserving each path's centerline."""
    cap_dbu = um_to_dbu(layout, max_width_um)
    if cap_dbu < 1:
        raise ValueError(
            f"MAX_CUT_WIDTH_UM={max_width_um} is smaller than the {layout.dbu} um layout grid"
        )

    paths_to_cap = []
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
                if width_dbu > cap_dbu:
                    paths_to_cap.append(shape)

    # Changing a shape can invalidate its container iterator, so widths are
    # updated only after all iterators have finished.
    for shape in paths_to_cap:
        shape.path_width = cap_dbu

    return {
        "paths_seen": paths_seen,
        "paths_capped": len(paths_to_cap),
        "widest_original_um": dbu_to_um(layout, widest_original_dbu),
    }


def region_from_source(layout, max_width_um: float) -> tuple[object, list[str], dict[str, float | int]]:
    matching_indices = []
    matching_names = []
    for layer_index in layout.layer_indices():
        info = layout.get_info(layer_index)
        if layer_matches(info):
            matching_indices.append(layer_index)
            matching_names.append(str(info))

    if not matching_indices:
        available = ", ".join(str(layout.get_info(i)) for i in layout.layer_indices())
        raise RuntimeError(
            f"No source layer {SOURCE_LAYER}/{SOURCE_DATATYPE} or named layer 0 found. "
            f"Available layers: {available or '<none>'}"
        )

    width_stats = cap_source_path_widths(layout, matching_indices, max_width_um)

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


def registration_envelope_region(layout):
    """Four non-exposed anchors whose combined bbox is exactly the field half
    size, `REGISTRATION_HALF_SIZE_UM`, in every tile and orientation."""
    half = um_to_dbu(layout, REGISTRATION_HALF_SIZE_UM)
    size = um_to_dbu(layout, REGISTRATION_ANCHOR_SIZE_UM)
    if size < 1 or size >= 2 * half:
        raise ValueError("Invalid registration anchor size")
    result = pya.Region()
    for x_sign in (-1, +1):
        for y_sign in (-1, +1):
            left = -half if x_sign < 0 else half - size
            right = -half + size if x_sign < 0 else half
            bottom = -half if y_sign < 0 else half - size
            top = -half + size if y_sign < 0 else half
            result.insert(pya.Box(left, bottom, right, top))
    return result


def clip_bounds_um(x_sign: int, y_sign: int, mode: str, stitch_um: float):
    half_field = QUALIFIED_FIELD_SIZE_UM / 2.0
    center_x = x_sign * WINDOW_CENTER_X_UM
    center_y = y_sign * WINDOW_CENTER_Y_UM
    field_left = center_x - half_field
    field_right = center_x + half_field
    field_bottom = center_y - half_field
    field_top = center_y + half_field

    if mode == "full_window":
        return field_left, field_bottom, field_right, field_top
    if mode != "partition":
        raise ValueError("CLIP_MODE must be 'partition' or 'full_window'")

    seam_half = stitch_um / 2.0
    left = -seam_half if x_sign > 0 else field_left
    right = field_right if x_sign > 0 else seam_half
    bottom = -seam_half if y_sign > 0 else field_bottom
    top = field_top if y_sign > 0 else seam_half
    return left, bottom, right, top


def validate_field_geometry(mode: str, stitch_um: float) -> None:
    """Check the relation that makes every clip box square and concentric.

    In partition mode a window runs from the seam to the far field edge, so its
    span is `WINDOW_CENTER + half_field + stitch/2`. That equals the field size
    only when

        QUALIFIED_FIELD_SIZE_UM == 2 * WINDOW_CENTER_UM + STITCH_OVERLAP_UM

    Change the stitch on its own and the windows silently stop being concentric
    with their fields, and can extend beyond the qualified field: at 4000 um of
    stitch each window becomes 53.4 mm and reaches 1.4 mm outside the 52 mm
    field. That is a placement error no downstream check would catch, so it is
    verified here rather than assumed.

    Note that under this relation `partition` and `full_window` produce
    identical boxes, because the fields overlap by exactly the stitch.
    """
    if WINDOW_CENTER_X_UM != WINDOW_CENTER_Y_UM:
        raise ValueError(
            "WINDOW_CENTER_X_UM and WINDOW_CENTER_Y_UM differ, so the four windows "
            "cannot be a symmetric 2 x 2 tiling of one square field"
        )
    if mode != "partition":
        return
    for axis, center in (("X", WINDOW_CENTER_X_UM), ("Y", WINDOW_CENTER_Y_UM)):
        expected = 2.0 * center + stitch_um
        if abs(QUALIFIED_FIELD_SIZE_UM - expected) > GEOMETRY_TOLERANCE_UM:
            raise ValueError(
                f"{axis} axis: QUALIFIED_FIELD_SIZE_UM={QUALIFIED_FIELD_SIZE_UM} must "
                f"equal 2 * WINDOW_CENTER_{axis}_UM + STITCH_OVERLAP_UM = {expected}. "
                f"Set the field to {expected}, or the stitch to "
                f"{QUALIFIED_FIELD_SIZE_UM - 2.0 * center}, so every window stays "
                "square and concentric with its field."
            )


def assert_window_is_square(name: str, bounds, center_x: float, center_y: float) -> None:
    """Every emitted window must be a square field centered on its own origin."""
    left, bottom, right, top = bounds
    width, height = right - left, top - bottom
    if abs(width - height) > GEOMETRY_TOLERANCE_UM:
        raise RuntimeError(f"{name}: window {width} x {height} um is not square")
    if abs(width - QUALIFIED_FIELD_SIZE_UM) > GEOMETRY_TOLERANCE_UM:
        raise RuntimeError(
            f"{name}: window is {width} um wide, expected the qualified field "
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


def dxf_header_extents(half_size_um: float, newline: str) -> str:
    """DXF HEADER variables declaring the window, in millimeter drawing units.

    KLayout writes a HEADER holding only `$ACADVER`, which leaves every importer
    to infer the drawing extent from the entities it finds. That inference is
    what displaced a job by 8 mm once already, and the registration anchors only
    fix it for importers that count a layer the operator has set to no marking.
    Declaring the extent here does not depend on any layer being counted.
    """
    half_mm = half_size_um / 1000.0
    lines: list[str] = []

    def variable(name: str, x: float, y: float, with_z: bool) -> None:
        lines.extend(("9", name, "10", f"{x:.6f}", "20", f"{y:.6f}"))
        if with_z:
            lines.extend(("30", "0.000000"))

    variable("$INSBASE", 0.0, 0.0, True)
    variable("$EXTMIN", -half_mm, -half_mm, True)
    variable("$EXTMAX", half_mm, half_mm, True)
    variable("$LIMMIN", -half_mm, -half_mm, False)
    variable("$LIMMAX", half_mm, half_mm, False)
    return newline.join(lines) + newline


def inject_dxf_header_extents(path: Path, half_size_um: float) -> None:
    text = path.read_text(encoding="utf-8", errors="strict")
    newline = "\r\n" if "\r\n" in text else "\n"
    header = text.find("HEADER")
    if header < 0:
        raise RuntimeError(f"{path.name}: no DXF HEADER section to declare extents in")
    marker = f"{newline}0{newline}ENDSEC"
    endsec = text.find(marker, header)
    if endsec < 0:
        raise RuntimeError(f"{path.name}: DXF HEADER section is not terminated")
    block = dxf_header_extents(half_size_um, newline)
    path.write_text(
        text[: endsec + len(newline)] + block + text[endsec + len(newline):],
        encoding="utf-8",
        newline="",
    )


def write_layout(
    output_path: Path,
    source_layout,
    region,
    cell_name: str,
    add_registration_envelope: bool,
    write_header_extents: bool,
) -> None:
    output_layout = pya.Layout()
    output_layout.dbu = source_layout.dbu
    cell = output_layout.create_cell(cell_name)
    layer_info = pya.LayerInfo(OUTPUT_LAYER, OUTPUT_DATATYPE)
    layer_info.name = OUTPUT_LAYER_NAME
    output_layer = output_layout.layer(layer_info)
    cell.shapes(output_layer).insert(region)

    if add_registration_envelope:
        registration_info = pya.LayerInfo(REGISTRATION_LAYER, REGISTRATION_DATATYPE)
        registration_info.name = REGISTRATION_LAYER_NAME
        registration_layer = output_layout.layer(registration_info)
        cell.shapes(registration_layer).insert(registration_envelope_region(output_layout))

    options = pya.SaveLayoutOptions()
    options.set_format_from_filename(str(output_path))
    if output_path.suffix.lower() == ".dxf":
        options.dxf_polygon_mode = DXF_POLYGON_MODE
        # KLayout database/display units are microns; restore 1 mm DXF units.
        options.scale_factor = 0.001
    output_layout.write(str(output_path), options)
    if output_path.suffix.lower() == ".dxf":
        # KLayout encodes numeric layers as names such as L0D0_0. Restore the
        # literal DXF layer name requested for the laser workflow.
        generated_name = f"L{OUTPUT_LAYER}D{OUTPUT_DATATYPE}_{OUTPUT_LAYER_NAME}"
        generated_registration_name = (
            f"L{REGISTRATION_LAYER}D{REGISTRATION_DATATYPE}_{REGISTRATION_LAYER_NAME}"
        )
        text = output_path.read_text(encoding="utf-8", errors="strict")
        output_path.write_text(
            text.replace(generated_name, OUTPUT_LAYER_NAME).replace(
                generated_registration_name, REGISTRATION_LAYER_NAME
            ),
            encoding="utf-8",
            newline="",
        )
        if write_header_extents:
            inject_dxf_header_extents(output_path, REGISTRATION_HALF_SIZE_UM)


def main() -> None:
    input_file = Path(str(runtime_value("input", INPUT_FILE))).expanduser()
    if not input_file.is_file():
        raise FileNotFoundError(
            f"Input file not found: {input_file}\n"
            "Edit INPUT_FILE near the top of this script or pass -rd input=<path>."
        )

    configured_output = str(runtime_value("output_dir", OUTPUT_DIR)).strip()
    output_dir = (
        Path(configured_output).expanduser()
        if configured_output
        else input_file.with_name(f"{input_file.stem}_four_windows")
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    global_x_um = as_float("global_x_um", GLOBAL_X_OFFSET_UM)
    global_y_um = as_float("global_y_um", GLOBAL_Y_OFFSET_UM)
    max_cut_width_um = as_float("max_cut_width_um", MAX_CUT_WIDTH_UM)
    stitch_um = as_float("stitch_overlap_um", STITCH_OVERLAP_UM)
    mode = str(runtime_value("clip_mode", CLIP_MODE)).strip().lower()
    add_registration_envelope = as_bool(
        "add_registration_envelope", ADD_IMPORT_REGISTRATION_ENVELOPE
    )
    write_header_extents = as_bool("write_dxf_header_extents", WRITE_DXF_HEADER_EXTENTS)
    allow_outside = as_bool("allow_geometry_outside_fields", ALLOW_GEOMETRY_OUTSIDE_FIELDS)
    extension = str(runtime_value("output_extension", OUTPUT_EXTENSION)).strip().lower()
    if not extension.startswith("."):
        extension = "." + extension
    if max_cut_width_um <= 0:
        raise ValueError("MAX_CUT_WIDTH_UM must be greater than zero")
    validate_field_geometry(mode, stitch_um)

    layout = pya.Layout()
    if input_file.suffix.lower() == ".dxf":
        load_options = pya.LoadLayoutOptions()
        load_options.dxf_unit = INPUT_DXF_UNIT_UM
        layout.read(str(input_file), load_options)
    else:
        layout.read(str(input_file))

    source_region, source_layers, width_stats = region_from_source(layout, max_cut_width_um)
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
        assert_window_is_square(name, bounds, field_center_x, field_center_y)
        left, bottom, right, top = bounds
        clip_box = pya.Box(
            um_to_dbu(layout, left),
            um_to_dbu(layout, bottom),
            um_to_dbu(layout, right),
            um_to_dbu(layout, top),
        )
        clipped = source_region & pya.Region(clip_box)

        translate_x_um = -field_center_x + global_x_um
        translate_y_um = -field_center_y + global_y_um
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
            add_registration_envelope,
            write_header_extents,
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
                "source_paths_capped": width_stats["paths_capped"],
                "output_bbox_um": "" if bbox is None else ";".join(f"{v:.3f}" for v in bbox),
                "polygon_count": clipped.count(),
                "has_cut_geometry": not clipped.is_empty(),
                "import_registration_envelope": add_registration_envelope,
                "declared_window_half_um": REGISTRATION_HALF_SIZE_UM if write_header_extents else "",
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
        stream.write(f"Maximum native path width (um): {max_cut_width_um}\n")
        stream.write(
            "Source native paths: "
            f"seen={width_stats['paths_seen']}, capped={width_stats['paths_capped']}, "
            f"widest_original_um={width_stats['widest_original_um']}\n"
        )
        stream.write(f"Stitch overlap (um): {stitch_um}\n")
        stream.write(
            "Import registration envelope: "
            f"enabled={add_registration_envelope}, "
            f"layer={REGISTRATION_LAYER_NAME}, "
            f"bbox_um=+/-{REGISTRATION_HALF_SIZE_UM}\n"
        )
        stream.write(
            "Declared DXF header extents: "
            f"enabled={write_header_extents}, "
            f"$EXTMIN/$EXTMAX=+/-{REGISTRATION_HALF_SIZE_UM / 1000.0:.3f} mm\n"
        )
        stream.write(
            "Window geometry: every window verified square, "
            f"{QUALIFIED_FIELD_SIZE_UM / 1000.0:.3f} mm, and concentric with its field\n"
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
