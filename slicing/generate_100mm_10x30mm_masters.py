"""Generate master DXFs for 10 x 30 mm dicing of a standard 100 mm wafer.

Run with KLayout. Dimensions in this file are microns. The primary flat faces
negative Y (table front) and the secondary flat faces negative X (table left).
All 50 um cut polygons are clipped to the `EDGE_BEAD_MM` inward offset from the
circular edge and both flats. The horizontal file also contains one centered
2.5 mm long, 50 um wide plus-style alignment marker.
"""

from __future__ import annotations

import math
from pathlib import Path

try:
    import pya
except ImportError:
    import klayout.db as pya


OUTPUT_DIR = r"C:\path\to\master_output"

WAFER_RADIUS_UM = 50_000.0

# Single edge-bead setting for the circular edge and both flats, in millimeters.
# Command-line `-rd edge_bead_mm=...` overrides this value.
EDGE_BEAD_MM = 2.000

PRIMARY_FLAT_LENGTH_UM = 32_500.0
SECONDARY_FLAT_LENGTH_UM = 18_000.0

CUT_WIDTH_UM = 50.0
X_PITCH_UM = 10_000.0
Y_PITCH_UM = 30_000.0
GRID_PHASE_X_UM = 5_000.0
GRID_PHASE_Y_UM = 15_000.0

MARKER_LENGTH_UM = 2_500.0
MARKER_WIDTH_UM = 50.0
CIRCLE_SEGMENTS = 2048

OUTPUT_LAYER = 0
OUTPUT_DATATYPE = 0
OUTPUT_LAYER_NAME = "0"
DXF_POLYGON_MODE = 1


def runtime_value(name: str, default):
    return globals().get(name, default)


def to_dbu(layout, value_um: float) -> int:
    return int(round(value_um / layout.dbu))


def safe_wafer_region(layout, edge_bead_um):
    safe_radius = WAFER_RADIUS_UM - edge_bead_um
    primary_depth = math.sqrt(
        WAFER_RADIUS_UM**2 - (PRIMARY_FLAT_LENGTH_UM / 2.0) ** 2
    )
    secondary_depth = math.sqrt(
        WAFER_RADIUS_UM**2 - (SECONDARY_FLAT_LENGTH_UM / 2.0) ** 2
    )
    safe_primary_y = -primary_depth + edge_bead_um
    safe_secondary_x = -secondary_depth + edge_bead_um

    radius_dbu = to_dbu(layout, safe_radius)
    circle = pya.Region(
        pya.Polygon(
            [
                pya.Point(
                    int(round(radius_dbu * math.cos(2.0 * math.pi * i / CIRCLE_SEGMENTS))),
                    int(round(radius_dbu * math.sin(2.0 * math.pi * i / CIRCLE_SEGMENTS))),
                )
                for i in range(CIRCLE_SEGMENTS)
            ]
        )
    )
    flat_limits = pya.Region(
        pya.Box(
            to_dbu(layout, safe_secondary_x),
            to_dbu(layout, safe_primary_y),
            to_dbu(layout, safe_radius + 1_000.0),
            to_dbu(layout, safe_radius + 1_000.0),
        )
    )
    return circle & flat_limits, safe_primary_y, safe_secondary_x


def pitch_positions(limit_um: float, pitch_um: float, phase_um: float):
    positions = []
    value = phase_um
    while value < limit_um:
        positions.extend((-value, value))
        value += pitch_um
    return sorted(positions)


def strip_box(layout, orientation: str, coordinate_um: float):
    half_width = CUT_WIDTH_UM / 2.0
    reach = WAFER_RADIUS_UM + 1_000.0
    if orientation == "vertical":
        return pya.Box(
            to_dbu(layout, coordinate_um - half_width),
            to_dbu(layout, -reach),
            to_dbu(layout, coordinate_um + half_width),
            to_dbu(layout, reach),
        )
    return pya.Box(
        to_dbu(layout, -reach),
        to_dbu(layout, coordinate_um - half_width),
        to_dbu(layout, reach),
        to_dbu(layout, coordinate_um + half_width),
    )


def centered_marker(layout):
    half_length = MARKER_LENGTH_UM / 2.0
    half_width = MARKER_WIDTH_UM / 2.0
    horizontal = pya.Region(
        pya.Box(
            to_dbu(layout, -half_length),
            to_dbu(layout, -half_width),
            to_dbu(layout, half_length),
            to_dbu(layout, half_width),
        )
    )
    vertical = pya.Region(
        pya.Box(
            to_dbu(layout, -half_width),
            to_dbu(layout, -half_length),
            to_dbu(layout, half_width),
            to_dbu(layout, half_length),
        )
    )
    return horizontal + vertical


def write_dxf(path: Path, source_layout, region, cell_name: str):
    output = pya.Layout()
    output.dbu = source_layout.dbu
    cell = output.create_cell(cell_name)
    info = pya.LayerInfo(OUTPUT_LAYER, OUTPUT_DATATYPE)
    info.name = OUTPUT_LAYER_NAME
    layer = output.layer(info)
    cell.shapes(layer).insert(region)

    options = pya.SaveLayoutOptions()
    options.set_format_from_filename(str(path))
    options.dxf_polygon_mode = DXF_POLYGON_MODE
    options.scale_factor = 0.001
    output.write(str(path), options)

    generated_name = f"L{OUTPUT_LAYER}D{OUTPUT_DATATYPE}_{OUTPUT_LAYER_NAME}"
    text = path.read_text(encoding="utf-8", errors="strict")
    path.write_text(
        text.replace(generated_name, OUTPUT_LAYER_NAME),
        encoding="utf-8",
        newline="",
    )


def main():
    configured = str(runtime_value("output_dir", OUTPUT_DIR))
    if configured == OUTPUT_DIR and "path\\to" in OUTPUT_DIR:
        # Otherwise the run "succeeds" into a literal C:\path\to\... directory.
        raise ValueError(
            "OUTPUT_DIR is still the placeholder. Edit it near the top of this "
            "script or pass -rd output_dir=<path>. To rebuild the masters in "
            "place, use: -rd output_dir=dxf/100mm_10x30mm_Masters"
        )
    output_dir = Path(configured).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)

    edge_bead_mm = float(runtime_value("edge_bead_mm", EDGE_BEAD_MM))
    if edge_bead_mm < 0 or edge_bead_mm >= WAFER_RADIUS_UM / 1_000.0:
        raise ValueError("EDGE_BEAD_MM must be at least 0 and less than the wafer radius")
    edge_bead_um = edge_bead_mm * 1_000.0

    layout = pya.Layout()
    layout.dbu = 0.001
    safe_wafer, safe_primary_y, safe_secondary_x = safe_wafer_region(layout, edge_bead_um)
    safe_radius = WAFER_RADIUS_UM - edge_bead_um

    vertical = pya.Region()
    x_positions = pitch_positions(safe_radius, X_PITCH_UM, GRID_PHASE_X_UM)
    for x_um in x_positions:
        vertical += pya.Region(strip_box(layout, "vertical", x_um)) & safe_wafer

    horizontal = pya.Region()
    y_positions = pitch_positions(safe_radius, Y_PITCH_UM, GRID_PHASE_Y_UM)
    for y_um in y_positions:
        horizontal += pya.Region(strip_box(layout, "horizontal", y_um)) & safe_wafer
    horizontal += centered_marker(layout)

    vertical_path = output_dir / "100mm_wafer_10x30mm_Vertical_master.dxf"
    horizontal_path = output_dir / "100mm_wafer_10x30mm_Horizontal_master.dxf"
    write_dxf(vertical_path, layout, vertical.merged(), "VERTICAL_MASTER")
    write_dxf(horizontal_path, layout, horizontal.merged(), "HORIZONTAL_MASTER")

    log_path = output_dir / "master_geometry.txt"
    log_path.write_text(
        "\n".join(
            (
                "100 mm wafer, 10 x 30 mm dicing grid",
                f"Edge bead (mm): {edge_bead_mm}",
                f"Edge bead (um): {edge_bead_um}",
                f"Safe circular radius (um): {safe_radius}",
                f"Safe primary-flat Y minimum (um): {safe_primary_y}",
                f"Safe secondary-flat X minimum (um): {safe_secondary_x}",
                f"Cut width (um): {CUT_WIDTH_UM}",
                f"Vertical cut centers (um): {x_positions}",
                f"Horizontal cut centers (um): {y_positions}",
                f"Alignment marker: centered plus, {MARKER_LENGTH_UM} x {MARKER_WIDTH_UM} um",
                f"Vertical polygons: {vertical.count()}",
                f"Horizontal polygons including marker: {horizontal.count()}",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Wrote master DXFs to: {output_dir}")


if __name__ == "__main__":
    main()
