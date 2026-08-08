"""Create one laser-centered score job from wafer-centered layer-0 geometry.

Default behavior keeps geometry inside a 75 mm diameter circle centered in the
78.485 mm usable galvo field. Configuration distances are microns; DXF files use mm.
"""

from __future__ import annotations

import math
from pathlib import Path

try:
    import pya
except ImportError:
    import klayout.db as pya


# =============================================================================
# USER SETTINGS - distances in microns unless explicitly marked otherwise
# =============================================================================

INPUT_FILE = r"C:\path\to\wafer_cutlines.dxf"
OUTPUT_DIR = r""  # Blank writes beside the input in a `<name>_center_pass` folder.

# Positive X moves output geometry right; positive Y moves it up.
GLOBAL_X_OFFSET_UM = 0.0
GLOBAL_Y_OFFSET_UM = 0.0

# Native KLayout/DXF path widths larger than this are reduced about their
# existing centerlines before clipping. Filled polygons are geometry rather
# than paths and are intentionally left unchanged.
MAX_CUT_WIDTH_UM = 50.0

FULL_FIELD_SIZE_UM = 78_485.0
SCORE_DIAMETER_UM = 75_000.0
SCORE_SHAPE = "circle"  # `circle` recommended; `square` is also supported.
CIRCLE_SEGMENTS = 256

SOURCE_LAYER = 0
SOURCE_DATATYPE = 0
OUTPUT_LAYER = 0
OUTPUT_DATATYPE = 0
OUTPUT_LAYER_NAME = "0"

INPUT_DXF_UNIT_UM = 1_000.0  # Supplied DXFs use 1 unit = 1 mm.
OUTPUT_EXTENSION = ".dxf"
DXF_POLYGON_MODE = 1  # Closed LWPOLYLINE entities.


def runtime_value(name: str, default):
    return globals().get(name, default)


def as_float(name: str, default: float) -> float:
    return float(runtime_value(name, default))


def layer_matches(info) -> bool:
    numeric_match = info.layer == SOURCE_LAYER and info.datatype == SOURCE_DATATYPE
    name = str(getattr(info, "name", "") or "")
    return numeric_match or name == str(SOURCE_LAYER) or name == OUTPUT_LAYER_NAME


def cap_source_path_widths(layout, layer_indices, max_width_um: float):
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
        "widest_original_um": widest_original_dbu * layout.dbu,
    }


def source_region(layout, max_width_um: float):
    indices = [
        index
        for index in layout.layer_indices()
        if layer_matches(layout.get_info(index))
    ]
    if not indices:
        available = ", ".join(str(layout.get_info(i)) for i in layout.layer_indices())
        raise RuntimeError(f"Layer 0 not found. Available layers: {available or '<none>'}")

    width_stats = cap_source_path_widths(layout, indices, max_width_um)

    region = pya.Region()
    for top_cell in layout.top_cells():
        for index in indices:
            region += pya.Region(top_cell.begin_shapes_rec(index))
    if region.is_empty():
        raise RuntimeError("Layer 0 contains no polygonal cut geometry")
    return region, width_stats


def um_to_dbu(layout, value_um: float) -> int:
    return int(round(value_um / layout.dbu))


def bbox_um(layout, region):
    if region.is_empty():
        return None
    box = region.bbox()
    return tuple(value * layout.dbu for value in (box.left, box.bottom, box.right, box.top))


def score_clip_region(layout, shape: str, diameter_um: float):
    radius_dbu = um_to_dbu(layout, diameter_um / 2.0)
    if shape == "square":
        return pya.Region(pya.Box(-radius_dbu, -radius_dbu, radius_dbu, radius_dbu))
    if shape != "circle":
        raise ValueError("SCORE_SHAPE must be 'circle' or 'square'")

    points = [
        pya.Point(
            int(round(radius_dbu * math.cos(2.0 * math.pi * i / CIRCLE_SEGMENTS))),
            int(round(radius_dbu * math.sin(2.0 * math.pi * i / CIRCLE_SEGMENTS))),
        )
        for i in range(CIRCLE_SEGMENTS)
    ]
    return pya.Region(pya.Polygon(points))


def write_output(path: Path, source_layout, region) -> None:
    layout = pya.Layout()
    layout.dbu = source_layout.dbu
    cell = layout.create_cell("CENTER_PASS")
    info = pya.LayerInfo(OUTPUT_LAYER, OUTPUT_DATATYPE)
    info.name = OUTPUT_LAYER_NAME
    layer = layout.layer(info)
    cell.shapes(layer).insert(region)

    options = pya.SaveLayoutOptions()
    options.set_format_from_filename(str(path))
    if path.suffix.lower() == ".dxf":
        options.dxf_polygon_mode = DXF_POLYGON_MODE
        options.scale_factor = 0.001  # KLayout microns back to millimeter DXF units.
    layout.write(str(path), options)

    if path.suffix.lower() == ".dxf":
        generated = f"L{OUTPUT_LAYER}D{OUTPUT_DATATYPE}_{OUTPUT_LAYER_NAME}"
        text = path.read_text(encoding="utf-8", errors="strict")
        path.write_text(
            text.replace(generated, OUTPUT_LAYER_NAME),
            encoding="utf-8",
            newline="",
        )


def main() -> None:
    input_path = Path(str(runtime_value("input", INPUT_FILE))).expanduser()
    if not input_path.is_file():
        raise FileNotFoundError(
            f"Input file not found: {input_path}\n"
            "Edit INPUT_FILE or pass -rd input=<path>."
        )

    output_setting = str(runtime_value("output_dir", OUTPUT_DIR)).strip()
    output_dir = (
        Path(output_setting).expanduser()
        if output_setting
        else input_path.with_name(f"{input_path.stem}_center_pass")
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    global_x = as_float("global_x_um", GLOBAL_X_OFFSET_UM)
    global_y = as_float("global_y_um", GLOBAL_Y_OFFSET_UM)
    max_cut_width_um = as_float("max_cut_width_um", MAX_CUT_WIDTH_UM)
    diameter = as_float("score_diameter_um", SCORE_DIAMETER_UM)
    shape = str(runtime_value("score_shape", SCORE_SHAPE)).strip().lower()
    extension = str(runtime_value("output_extension", OUTPUT_EXTENSION)).strip().lower()
    if not extension.startswith("."):
        extension = "." + extension
    if diameter <= 0 or diameter > FULL_FIELD_SIZE_UM:
        raise ValueError(
            f"SCORE_DIAMETER_UM must be > 0 and <= {FULL_FIELD_SIZE_UM} um"
        )
    if max_cut_width_um <= 0:
        raise ValueError("MAX_CUT_WIDTH_UM must be greater than zero")

    layout = pya.Layout()
    if input_path.suffix.lower() == ".dxf":
        load_options = pya.LoadLayoutOptions()
        load_options.dxf_unit = INPUT_DXF_UNIT_UM
        layout.read(str(input_path), load_options)
    else:
        layout.read(str(input_path))

    original, width_stats = source_region(layout, max_cut_width_um)
    clipped = original & score_clip_region(layout, shape, diameter)
    clipped.transform(
        pya.Trans(um_to_dbu(layout, global_x), um_to_dbu(layout, global_y))
    )

    output_path = output_dir / f"{input_path.stem}_center_pass{extension}"
    write_output(output_path, layout, clipped)

    log_path = output_dir / f"{input_path.stem}_center_pass_log.txt"
    log_path.write_text(
        "\n".join(
            (
                f"Input: {input_path}",
                f"Output: {output_path}",
                f"Score shape: {shape}",
                f"Score diameter (um): {diameter}",
                f"Full field (um): {FULL_FIELD_SIZE_UM}",
                f"Global offset (um): X={global_x}, Y={global_y}",
                f"Maximum native path width (um): {max_cut_width_um}",
                f"Source native paths seen: {width_stats['paths_seen']}",
                f"Source native paths capped: {width_stats['paths_capped']}",
                f"Widest original native path (um): {width_stats['widest_original_um']}",
                f"Source polygons: {original.count()}",
                f"Output polygons: {clipped.count()}",
                f"Output bbox (um): {bbox_um(layout, clipped)}",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Wrote center-pass job: {output_path}")


if __name__ == "__main__":
    main()
