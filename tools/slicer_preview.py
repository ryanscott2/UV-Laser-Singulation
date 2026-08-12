"""Compute what the slicer would emit, without writing any files.

The preview calls the splitter's own `clip_bounds_um`, layer matching and width
handling, so what is drawn cannot drift away from what a
real run produces. The splitter is loaded with a `run_name` other than
`__main__`, which leaves its `main()` unexecuted.
"""

from __future__ import annotations

import runpy
from dataclasses import dataclass, field
from pathlib import Path

import klayout.db as pya

REPO_ROOT = Path(__file__).resolve().parent.parent
SPLITTER = REPO_ROOT / "python" / "split_klayout.py"

Polygon = list[tuple[float, float]]


@dataclass
class TilePreview:
    label: str            # P1_jig_top_left
    folder: str           # P1
    station: str          # top_left
    exposed: str          # bottom_right
    clip_mm: tuple[float, float, float, float]      # in source coordinates
    field_center_mm: tuple[float, float]
    cuts_mm: list[Polygon] = field(default_factory=list)   # already translated
    polygon_count: int = 0
    area_mm2: float = 0.0

    @property
    def is_empty(self) -> bool:
        return self.polygon_count == 0


@dataclass
class Preview:
    source_cuts_mm: list[Polygon]
    tiles: list[TilePreview]
    field_mm: float
    half_mm: float
    stitch_mm: float
    edge_bead_mm: float
    source_bbox_mm: tuple[float, float, float, float] | None
    source_area_mm2: float
    dropped_area_mm2: float
    layers_matched: list[str]
    paths_seen: int
    paths_changed: int
    truncated: bool
    notes: list[str]
    run_mode: str = "four_windows"
    score_diameter_mm: float = 0.0
    score_shape: str = "circle"
    center_cuts_mm: list[Polygon] = field(default_factory=list)


_namespace: dict | None = None


def splitter_namespace() -> dict:
    """Load the splitter's functions and constants without running it."""
    global _namespace
    if _namespace is None:
        _namespace = runpy.run_path(str(SPLITTER), run_name="slicer_preview_host")
    return _namespace


def _polygons_mm(region, dbu: float, limit: int) -> tuple[list[Polygon], bool]:
    out: list[Polygon] = []
    scale = dbu / 1000.0
    truncated = False
    for index, polygon in enumerate(region.each()):
        if index >= limit:
            truncated = True
            break
        out.append([(p.x * scale, p.y * scale) for p in polygon.each_point_hull()])
    return out, truncated


def build_preview(
    input_path: Path,
    layer_spec: str = "",
    cut_width_um: float = 50.0,
    width_mode: str = "cap",
    clip_mode: str = "partition",
    stitch_um: float | None = None,
    global_x_um: float = 0.0,
    global_y_um: float = 0.0,
    window_offsets=None,
    edge_bead_mm: float = 0.0,
    run_mode: str = "four_windows",
    score_diameter_um: float = 75000.0,
    score_shape: str = "circle",
    max_polygons: int = 4000,
) -> Preview:
    ns = splitter_namespace()
    stitch = ns["STITCH_OVERLAP_UM"] if stitch_um is None else float(stitch_um)
    ns["validate_field_geometry"](clip_mode, stitch)
    offsets = ns["parse_window_offsets"](
        ns["WINDOW_OFFSETS_UM"] if window_offsets is None else window_offsets
    )

    layout = pya.Layout()
    if input_path.suffix.lower() == ".dxf":
        options = pya.LoadLayoutOptions()
        options.dxf_unit = ns["INPUT_DXF_UNIT_UM"]
        layout.read(str(input_path), options)
    else:
        layout.read(str(input_path))

    spec = ns["parse_layer_spec"](layer_spec)
    source, matched, width_stats = ns["region_from_source"](
        layout, cut_width_um, spec, width_mode
    )
    source = source.merged()
    if width_mode == "force" and width_stats["paths_seen"] == 0:
        source = ns["set_line_widths"](source, cut_width_um, "force", layout.dbu)
    if edge_bead_mm and edge_bead_mm > 0:
        source = source & ns["safe_wafer_region"](layout, edge_bead_mm * 1000.0)

    notes: list[str] = []
    if width_stats["paths_seen"] == 0:
        notes.append(
            "Selected layer is filled polygons: 'Force to' sets their width, "
            "'Cap at' leaves them as drawn."
        )

    if run_mode == "center_pass":
        score = ns["score_clip_region"](layout, score_shape, score_diameter_um)
        kept = source & score
        source_polys, truncated = _polygons_mm(source, layout.dbu, max_polygons)
        center_polys, kept_truncated = _polygons_mm(kept, layout.dbu, max_polygons)
        scale = layout.dbu / 1000.0
        box = source.bbox()
        return Preview(
            source_cuts_mm=source_polys,
            tiles=[],
            field_mm=score_diameter_um / 1000.0,
            half_mm=score_diameter_um / 2000.0,
            stitch_mm=0.0,
            edge_bead_mm=edge_bead_mm,
            source_bbox_mm=None if source.is_empty() else (
                box.left * scale, box.bottom * scale, box.right * scale, box.top * scale),
            source_area_mm2=ns["dbu_area_to_mm2"](layout, source.area()),
            dropped_area_mm2=ns["dbu_area_to_mm2"](layout, (source - score).area()),
            layers_matched=matched,
            paths_seen=int(width_stats["paths_seen"]),
            paths_changed=int(width_stats["paths_capped"]),
            truncated=truncated or kept_truncated,
            notes=notes,
            run_mode="center_pass",
            score_diameter_mm=score_diameter_um / 1000.0,
            score_shape=score_shape,
            center_cuts_mm=center_polys,
        )

    union = ns["clip_union_region"](layout, clip_mode, stitch)
    dropped = source - union
    dropped_mm2 = ns["dbu_area_to_mm2"](layout, dropped.area())
    if dropped.area() > 0:
        notes.append(
            f"{dropped_mm2:.4f} mm2 lies outside all four windows and would be discarded."
        )

    source_polys, truncated = _polygons_mm(source, layout.dbu, max_polygons)

    tiles: list[TilePreview] = []
    per_tile_limit = max(200, max_polygons // 4)
    for label, x_sign, y_sign in ns["WINDOWS"]:
        center_x = x_sign * ns["WINDOW_CENTER_X_UM"]
        center_y = y_sign * ns["WINDOW_CENTER_Y_UM"]
        bounds = ns["clip_bounds_um"](x_sign, y_sign, clip_mode, stitch)
        ns["assert_window_is_square"](
            label, bounds, center_x, center_y,
            ns["QUALIFIED_FIELD_SIZE_UM"] if clip_mode == "full_window"
            else ns["partition_window_size_um"](stitch),
        )
        left, bottom, right, top = bounds

        clipped = source & pya.Region(
            pya.Box(
                ns["um_to_dbu"](layout, left), ns["um_to_dbu"](layout, bottom),
                ns["um_to_dbu"](layout, right), ns["um_to_dbu"](layout, top),
            )
        )
        nudge_x, nudge_y = offsets[ns["window_folder"](label)]
        clipped.transform(
            pya.Trans(
                ns["um_to_dbu"](layout, -center_x + global_x_um + nudge_x),
                ns["um_to_dbu"](layout, -center_y + global_y_um + nudge_y),
            )
        )
        cuts, tile_truncated = _polygons_mm(clipped, layout.dbu, per_tile_limit)
        truncated = truncated or tile_truncated

        tiles.append(
            TilePreview(
                label=label,
                folder=label.split("_", 1)[0],
                station=ns["quadrant_name"](-x_sign, -y_sign),
                exposed=ns["quadrant_name"](x_sign, y_sign),
                clip_mm=(left / 1000.0, bottom / 1000.0, right / 1000.0, top / 1000.0),
                field_center_mm=(center_x / 1000.0, center_y / 1000.0),
                cuts_mm=cuts,
                polygon_count=clipped.count(),
                area_mm2=ns["dbu_area_to_mm2"](layout, clipped.area()),
            )
        )

    empty = [t.folder for t in tiles if t.is_empty]
    if empty:
        notes.append(f"No cut geometry in {', '.join(empty)}.")
    if truncated:
        notes.append(f"Preview drawing capped at {max_polygons} polygons; output is unaffected.")

    box = source.bbox()
    scale = layout.dbu / 1000.0
    return Preview(
        source_cuts_mm=source_polys,
        tiles=tiles,
        field_mm=ns["QUALIFIED_FIELD_SIZE_UM"] / 1000.0,
        half_mm=ns["QUALIFIED_FIELD_SIZE_UM"] / 2000.0,
        stitch_mm=stitch / 1000.0,
        edge_bead_mm=edge_bead_mm,
        source_bbox_mm=None if source.is_empty() else (
            box.left * scale, box.bottom * scale, box.right * scale, box.top * scale
        ),
        source_area_mm2=ns["dbu_area_to_mm2"](layout, source.area()),
        dropped_area_mm2=dropped_mm2,
        layers_matched=matched,
        paths_seen=int(width_stats["paths_seen"]),
        paths_changed=int(width_stats["paths_capped"]),
        truncated=truncated,
        notes=notes,
    )
