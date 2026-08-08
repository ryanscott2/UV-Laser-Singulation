"""OLD-JIG TEST: split wafer cut geometry into four laser-window jobs.

Run inside KLayout or from its command line. DXF input is assumed to use
millimeter drawing units; GDS/OAS input uses the units stored in the file.
Each output job is translated so its physical laser-window center is (0, 0).

This profile compensates the original jig, which was built around the
edge-derived table field center (100.172, 107.672) mm rather than the directly
measured zero-cross center (96.190, 109.350) mm. Do not use this profile with
the corrected jig.
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

# Qualified field and four-position jig geometry.
QUALIFIED_FIELD_SIZE_UM = 60_000.0
WINDOW_CENTER_X_UM = 25_000.0
WINDOW_CENTER_Y_UM = 25_000.0

# Old-jig physical laser-window centers in wafer coordinates are the nominal
# +/-25 mm grid shifted by (-3.982, +1.678) mm. Moving the clip grid as well as
# the translations keeps every output inside the centered 60 mm optical area.
WINDOW_PATTERN_X_OFFSET_UM = -3_982.0
WINDOW_PATTERN_Y_OFFSET_UM = +1_678.0

# `partition` avoids double exposure in the 10 mm physical window overlaps.
# `full_window` copies everything visible in every 60 mm field and therefore
# intentionally duplicates geometry in the overlap zones.
CLIP_MODE = "partition"  # `partition` or `full_window`

# Total overlap across the X=0 and Y=0 stitch lines in partition mode.
# Leave at zero initially. Example: 100 gives 50 um extra on each side.
STITCH_OVERLAP_UM = 0.0

# Source and output layer. DXF layer "0" normally imports as layer 0/datatype 0.
SOURCE_LAYER = 0
SOURCE_DATATYPE = 0
OUTPUT_LAYER = 0
OUTPUT_DATATYPE = 0
OUTPUT_LAYER_NAME = "0"

# Keep every exported job registered to the same 60 x 60 mm canvas even when
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

# DXF drawing units: the supplied references use 1 unit = 1 mm = 1000 um.
INPUT_DXF_UNIT_UM = 1_000.0
OUTPUT_EXTENSION = ".dxf"  # `.dxf`, `.gds`, or `.oas`

# DXF writer mode 1 produces closed LWPOLYLINE entities.
DXF_POLYGON_MODE = 1


# =============================================================================
# IMPLEMENTATION
# =============================================================================

WINDOWS = (
    # Name, field-center X/Y in wafer coordinates, X/Y ownership signs.
    ("P1_right_top", +1, +1),
    ("P2_left_top", -1, +1),
    ("P3_right_bottom", +1, -1),
    ("P4_left_bottom", -1, -1),
)


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
    """Four non-exposed anchors whose combined bbox is exactly +/-30 mm."""
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


def clip_bounds_um(
    x_sign: int,
    y_sign: int,
    mode: str,
    stitch_um: float,
    pattern_x_um: float,
    pattern_y_um: float,
):
    half_field = QUALIFIED_FIELD_SIZE_UM / 2.0
    center_x = x_sign * WINDOW_CENTER_X_UM + pattern_x_um
    center_y = y_sign * WINDOW_CENTER_Y_UM + pattern_y_um
    field_left = center_x - half_field
    field_right = center_x + half_field
    field_bottom = center_y - half_field
    field_top = center_y + half_field

    if mode == "full_window":
        return field_left, field_bottom, field_right, field_top
    if mode != "partition":
        raise ValueError("CLIP_MODE must be 'partition' or 'full_window'")

    seam_half = stitch_um / 2.0
    seam_x = pattern_x_um
    seam_y = pattern_y_um
    left = seam_x - seam_half if x_sign > 0 else field_left
    right = field_right if x_sign > 0 else seam_x + seam_half
    bottom = seam_y - seam_half if y_sign > 0 else field_bottom
    top = field_top if y_sign > 0 else seam_y + seam_half
    return left, bottom, right, top


def write_layout(
    output_path: Path,
    source_layout,
    region,
    cell_name: str,
    add_registration_envelope: bool,
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
    pattern_x_um = as_float("window_pattern_x_offset_um", WINDOW_PATTERN_X_OFFSET_UM)
    pattern_y_um = as_float("window_pattern_y_offset_um", WINDOW_PATTERN_Y_OFFSET_UM)
    max_cut_width_um = as_float("max_cut_width_um", MAX_CUT_WIDTH_UM)
    stitch_um = as_float("stitch_overlap_um", STITCH_OVERLAP_UM)
    mode = str(runtime_value("clip_mode", CLIP_MODE)).strip().lower()
    add_registration_envelope = as_bool(
        "add_registration_envelope", ADD_IMPORT_REGISTRATION_ENVELOPE
    )
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

    source_region, source_layers, width_stats = region_from_source(layout, max_cut_width_um)
    source_bbox = region_bbox_um(layout, source_region)
    manifest_rows = []

    for name, x_sign, y_sign in WINDOWS:
        field_center_x = x_sign * WINDOW_CENTER_X_UM + pattern_x_um
        field_center_y = y_sign * WINDOW_CENTER_Y_UM + pattern_y_um
        left, bottom, right, top = clip_bounds_um(
            x_sign,
            y_sign,
            mode,
            stitch_um,
            pattern_x_um,
            pattern_y_um,
        )
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

        output_path = output_dir / f"{input_file.stem}_{name}{extension}"
        write_layout(
            output_path,
            layout,
            clipped,
            name.upper(),
            add_registration_envelope,
        )
        bbox = region_bbox_um(layout, clipped)
        manifest_rows.append(
            {
                "job": name,
                "output_file": output_path.name,
                "field_center_x_wafer_um": field_center_x,
                "field_center_y_wafer_um": field_center_y,
                "old_jig_pattern_x_offset_um": pattern_x_um,
                "old_jig_pattern_y_offset_um": pattern_y_um,
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
                "import_registration_envelope": add_registration_envelope,
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
        stream.write(
            f"OLD JIG window-pattern offset (um): X={pattern_x_um}, Y={pattern_y_um}\n"
        )
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
        stream.write(f"Output directory: {output_dir}\n")
        for row in manifest_rows:
            stream.write(
                f"{row['job']}: polygons={row['polygon_count']}, "
                f"bbox_um={row['output_bbox_um']}\n"
            )

    print(f"Wrote four window jobs and manifest to: {output_dir}")


if __name__ == "__main__":
    main()
