"""Generate marker-free master DXFs for 10 x 30 mm dicing of a 100 mm wafer.

Same geometry as generate_100mm_10x30mm_masters.py but WITHOUT the centered
plus-style alignment marker, for a full production dice that needs no alignment
feature. This reuses that module's geometry (edge bead, pitch, flats, DXF
formatting), so the only difference between the two master sets is the marker.

Run with KLayout or the standalone klayout wheel. Dimensions are microns. Set
the output directory the same way as the base generator -- either KLayout's
`-rd output_dir=...` or, driven from Python, runpy `init_globals`:

    python -c "import runpy; runpy.run_path('python/generate_100mm_10x30mm_masters_nomarker.py', \\
        init_globals={'output_dir': 'dxf/100mm_10x30mm_Masters_NoMarker'}, run_name='__main__')"
"""

from __future__ import annotations

import sys
from pathlib import Path

# Import the base generator whether launched directly, via runpy, or in KLayout:
# only direct invocation puts this file's directory on sys.path automatically.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import generate_100mm_10x30mm_masters as base

pya = base.pya


def runtime_value(name: str, default):
    return globals().get(name, default)


def main():
    configured = str(runtime_value("output_dir", base.OUTPUT_DIR))
    if configured == base.OUTPUT_DIR and "path\\to" in base.OUTPUT_DIR:
        # Otherwise the run "succeeds" into a literal C:\path\to\... directory.
        raise ValueError(
            "output_dir is still the placeholder. Pass -rd output_dir=<path> or "
            "runpy init_globals. Suggested: dxf/100mm_10x30mm_Masters_NoMarker"
        )
    output_dir = Path(configured).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)

    edge_bead_mm = float(runtime_value("edge_bead_mm", base.EDGE_BEAD_MM))
    if edge_bead_mm < 0 or edge_bead_mm >= base.WAFER_RADIUS_UM / 1_000.0:
        raise ValueError("edge_bead_mm must be at least 0 and less than the wafer radius")
    edge_bead_um = edge_bead_mm * 1_000.0

    layout = pya.Layout()
    layout.dbu = 0.001
    safe_wafer, safe_primary_y, safe_secondary_x = base.safe_wafer_region(layout, edge_bead_um)
    safe_radius = base.WAFER_RADIUS_UM - edge_bead_um

    vertical = pya.Region()
    x_positions = base.pitch_positions(safe_radius, base.X_PITCH_UM, base.GRID_PHASE_X_UM)
    for x_um in x_positions:
        vertical += pya.Region(base.strip_box(layout, "vertical", x_um)) & safe_wafer

    horizontal = pya.Region()
    y_positions = base.pitch_positions(safe_radius, base.Y_PITCH_UM, base.GRID_PHASE_Y_UM)
    for y_um in y_positions:
        horizontal += pya.Region(base.strip_box(layout, "horizontal", y_um)) & safe_wafer
    # No centered marker: this is the marker-free full-dice master.

    vertical_path = output_dir / "100mm_wafer_10x30mm_Vertical_master.dxf"
    horizontal_path = output_dir / "100mm_wafer_10x30mm_Horizontal_master.dxf"
    base.write_dxf(vertical_path, layout, vertical.merged(), "VERTICAL_MASTER")
    base.write_dxf(horizontal_path, layout, horizontal.merged(), "HORIZONTAL_MASTER")

    log_path = output_dir / "master_geometry.txt"
    log_path.write_text(
        "\n".join(
            (
                "100 mm wafer, 10 x 30 mm dicing grid (marker-free)",
                f"Edge bead (mm): {edge_bead_mm}",
                f"Edge bead (um): {edge_bead_um}",
                f"Safe circular radius (um): {safe_radius}",
                f"Safe primary-flat Y minimum (um): {safe_primary_y}",
                f"Safe secondary-flat X minimum (um): {safe_secondary_x}",
                f"Cut width (um): {base.CUT_WIDTH_UM}",
                f"Vertical cut centers (um): {x_positions}",
                f"Horizontal cut centers (um): {y_positions}",
                "Alignment marker: none",
                f"Vertical polygons: {vertical.count()}",
                f"Horizontal polygons: {horizontal.count()}",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Wrote marker-free master DXFs to: {output_dir}")


if __name__ == "__main__":
    main()
