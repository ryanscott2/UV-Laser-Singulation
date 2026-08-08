"""Generate the explanatory SVG figures for the slicer documentation.

Every coordinate is derived from the constants the production scripts use, and
the cut geometry and content bounds are read out of the real DXFs, so the figures
cannot drift away from what the toolchain actually emits.

    python tools/make_figures.py

Writes docs/figures/*.svg. Figures are drawn in millimetres with Y up and the
viewBox is fitted to the content, so nothing can fall outside the canvas. Cut
features are 50 um wide against a 100 mm wafer, so they carry an added stroke to
stay visible; every other dimension is to scale unless a caption says otherwise.
"""

from __future__ import annotations

import math
import os
from pathlib import Path

import klayout.db as pya

from pin_grid_layout import (
    LASER_ZERO,
    QUALIFIED_FIELD_SIZE_MM,
    REGISTRATION_HALF_SIZE_MM,
    STATIONS,
    STITCH_OVERLAP_MM,
    hole_coordinate_mm,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
FIGURE_DIR = Path("docs/figures")
MASTERS = Path("dxf/100mm_10x30mm_Masters")
FAILED_SET = Path("output/DXFs/080726_FourPosDicer")
LOCKED_SET = Path("output/DXFs/080726_FourPosDicer_OriginLocked")

WAFER_RADIUS = 50.0
PRIMARY_FLAT_LENGTH = 32.500
SECONDARY_FLAT_LENGTH = 18.000
EDGE_BEAD = 2.000
HALF_FIELD = QUALIFIED_FIELD_SIZE_MM / 2.0
SEAM_HALF = STITCH_OVERLAP_MM / 2.0

STATION_COLORS = {
    "DXF11": "#1f6feb",
    "DXF12": "#bf8700",
    "DXF21": "#1a7f37",
    "DXF22": "#8250df",
}

STYLE = """  <style>
    .bg { fill: #ffffff; }
    text { font-family: ui-sans-serif, -apple-system, "Segoe UI", Helvetica, sans-serif; }
    .ink { fill: #1f2328; }
    .muted { fill: #59636e; }
    .warn { fill: #cf222e; }
    .s-ink { stroke: #1f2328; fill: none; }
    .s-muted { stroke: #59636e; fill: none; }
    .s-warn { stroke: #cf222e; fill: none; }
    .wafer { fill: #f6f8fa; stroke: #59636e; }
    .safe { fill: none; stroke: #59636e; stroke-dasharray: 1.6 1.6; }
    .cut { fill: #1f2328; stroke: #1f2328; }
    .overlap { fill: #cf222e; opacity: 0.18; stroke: none; }
    .anchor { fill: #cf222e; }
    .hole { fill: #ffffff; stroke: #8c959f; }
    .plate { fill: #1f6feb; opacity: 0.09; stroke: #1f6feb; }
    @media (prefers-color-scheme: dark) {
      .bg { fill: #0d1117; }
      .ink { fill: #e6edf3; }
      .muted { fill: #9198a1; }
      .warn { fill: #ff7b72; }
      .s-ink { stroke: #e6edf3; }
      .s-muted { stroke: #9198a1; }
      .s-warn { stroke: #ff7b72; }
      .wafer { fill: #161b22; stroke: #9198a1; }
      .safe { stroke: #9198a1; }
      .cut { fill: #e6edf3; stroke: #e6edf3; }
      .hole { fill: #0d1117; stroke: #6e7681; }
      .anchor { fill: #ff7b72; }
    }
  </style>"""

ARROW_DEF = (
    '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" '
    'markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" '
    'class="ink"/></marker></defs>'
)


class Fig:
    """Millimetre canvas with Y up. Tracks content so the viewBox always fits."""

    def __init__(self, margin: float = 4.0):
        self.margin = margin
        self.shapes: list[str] = []  # mm space, wrapped in a Y flip
        self.texts: list[str] = []  # already in screen space
        self._x: list[float] = []
        self._y: list[float] = []

    def _track(self, *points: tuple[float, float]) -> None:
        for x, y in points:
            self._x.append(x)
            self._y.append(y)

    def poly(self, points, cls: str = "", extra: str = "") -> None:
        self._track(*points)
        pts = " ".join(f"{x:.4f},{y:.4f}" for x, y in points)
        self.shapes.append(f'<polygon class="{cls}" points="{pts}" {extra}/>')

    def rect(self, x0, y0, x1, y1, cls: str = "", extra: str = "") -> None:
        self._track((x0, y0), (x1, y1))
        self.shapes.append(
            f'<rect class="{cls}" x="{min(x0,x1):.4f}" y="{min(y0,y1):.4f}" '
            f'width="{abs(x1-x0):.4f}" height="{abs(y1-y0):.4f}" {extra}/>'
        )

    def circle(self, x, y, r, cls: str = "", extra: str = "") -> None:
        self._track((x - r, y - r), (x + r, y + r))
        self.shapes.append(f'<circle class="{cls}" cx="{x:.4f}" cy="{y:.4f}" r="{r:.4f}" {extra}/>')

    def line(self, x0, y0, x1, y1, cls: str = "s-muted", extra: str = "") -> None:
        self._track((x0, y0), (x1, y1))
        self.shapes.append(
            f'<line class="{cls}" x1="{x0:.4f}" y1="{y0:.4f}" x2="{x1:.4f}" y2="{y1:.4f}" {extra}/>'
        )

    def text(self, x, y, body: str, cls: str = "ink", size: float = 2.8,
             anchor: str = "middle", weight: str = "", fill: str = "") -> None:
        # Roughly reserve the glyph box so long labels cannot escape the canvas.
        width = len(body) * size * 0.55
        left = {"middle": x - width / 2, "start": x, "end": x - width}[anchor]
        self._track((left, y - size * 0.85), (left + width, y + size * 0.4))
        attrs = f' font-weight="{weight}"' if weight else ""
        attrs += f' fill="{fill}"' if fill else ""
        self.texts.append(
            f'<text class="{cls}" x="{x:.3f}" y="{-y:.3f}" font-size="{size}" '
            f'text-anchor="{anchor}"{attrs}>{body}</text>'
        )

    def render(self, width_px: int = 900) -> str:
        x0 = min(self._x) - self.margin
        x1 = max(self._x) + self.margin
        y0 = min(self._y) - self.margin
        y1 = max(self._y) + self.margin
        w, h = x1 - x0, y1 - y0
        height_px = max(1, round(width_px * h / w))
        return "\n".join(
            [
                f'<svg xmlns="http://www.w3.org/2000/svg" width="{width_px}" '
                f'height="{height_px}" viewBox="{x0:.3f} {-y1:.3f} {w:.3f} {h:.3f}" role="img">',
                STYLE,
                ARROW_DEF,
                f'<rect class="bg" x="{x0:.3f}" y="{-y1:.3f}" width="{w:.3f}" height="{h:.3f}"/>',
                f'<g transform="scale(1,-1)">{"".join(self.shapes)}</g>',
                *self.texts,
                "</svg>",
            ]
        )


# ------------------------------------------------------------------- geometry


def wafer_outline(radius: float, primary_trim: float = 0.0, secondary_trim: float = 0.0):
    """Circle clipped by both flats, the same way the generator does it."""
    primary_depth = math.sqrt(WAFER_RADIUS**2 - (PRIMARY_FLAT_LENGTH / 2.0) ** 2)
    secondary_depth = math.sqrt(WAFER_RADIUS**2 - (SECONDARY_FLAT_LENGTH / 2.0) ** 2)
    points = [
        (radius * math.cos(i * 2 * math.pi / 720), radius * math.sin(i * 2 * math.pi / 720))
        for i in range(720)
    ]
    for axis, threshold in ((1, -primary_depth + primary_trim), (0, -secondary_depth + secondary_trim)):
        clipped, previous = [], points[-1]
        inside_prev = previous[axis] >= threshold
        for current in points:
            inside = current[axis] >= threshold
            if inside != inside_prev:
                ratio = (threshold - previous[axis]) / (current[axis] - previous[axis])
                clipped.append((previous[0] + ratio * (current[0] - previous[0]),
                                previous[1] + ratio * (current[1] - previous[1])))
            if inside:
                clipped.append(current)
            previous, inside_prev = current, inside
        points = clipped
    return points


_LAYOUTS: list = []


def read_layer(path: Path, layer_name: str | None = None):
    layout = pya.Layout()
    _LAYOUTS.append(layout)
    options = pya.LoadLayoutOptions()
    options.dxf_unit = 1_000.0
    layout.read(str(path), options)
    region = pya.Region()
    for index in layout.layer_indices():
        info = layout.get_info(index)
        name = str(getattr(info, "name", "") or "")
        hit = name == layer_name if layer_name else (
            (info.layer == 0 and info.datatype == 0) or name == "0"
        )
        if hit:
            for top in layout.top_cells():
                region += pya.Region(top.begin_shapes_rec(index))
    return region, layout.dbu / 1000.0


def polygons_mm(path: Path):
    region, scale = read_layer(path)
    return [
        [(p.x * scale, p.y * scale) for p in poly.each_point_hull()]
        for poly in region.each()
    ]


def bbox_mm(path: Path, layer_name: str | None = None):
    region, scale = read_layer(path, layer_name)
    box = region.bbox()
    return (box.left * scale, box.bottom * scale, box.right * scale, box.top * scale)


def master_cuts():
    result = []
    for orientation in ("Horizontal", "Vertical"):
        result.extend(polygons_mm(MASTERS / f"100mm_wafer_10x30mm_{orientation}_master.dxf"))
    return result


def add_cuts(fig: Fig, polys, fatten: float = 0.2, offset=(0.0, 0.0)) -> None:
    for poly in polys:
        fig.poly([(x + offset[0], y + offset[1]) for x, y in poly], "cut",
                 f'stroke-width="{fatten}"')


# -------------------------------------------------------------------- figures


def fig_wafer_and_fields():
    fig = Fig(margin=5)
    fig.poly(wafer_outline(WAFER_RADIUS), "wafer", 'stroke-width="0.4"')
    fig.poly(wafer_outline(WAFER_RADIUS - EDGE_BEAD, EDGE_BEAD, EDGE_BEAD), "safe",
             'stroke-width="0.32"')
    add_cuts(fig, master_cuts())

    reach = 25.4 + HALF_FIELD
    fig.rect(-SEAM_HALF, -reach, SEAM_HALF, reach, "overlap")
    fig.rect(-reach, -SEAM_HALF, reach, SEAM_HALF, "overlap")

    for station in STATIONS:
        cx, cy = station.field_center_mm
        color = STATION_COLORS[station.label]
        fig.rect(cx - HALF_FIELD, cy - HALF_FIELD, cx + HALF_FIELD, cy + HALF_FIELD,
                 "", f'fill="none" stroke="{color}" stroke-width="0.55" rx="0.8"')
        fig.circle(cx, cy, 0.9, "", f'fill="{color}"')

    for station in STATIONS:
        cx, cy = station.field_center_mm
        color = STATION_COLORS[station.label]
        lx = cx + (HALF_FIELD - 9) * (1 if cx > 0 else -1)
        ly = cy + (HALF_FIELD - 4.5) * (1 if cy > 0 else -1)
        fig.text(lx, ly, station.label, size=3.6, weight="600", fill=color)
        fig.text(lx, ly - 3.8, f"jig {station.jig_station.replace('_', '-')}", "muted", 2.5)
        fig.text(cx, cy + 2.4, f"({cx:+.1f}, {cy:+.1f})", "muted", 2.3)

    fig.text(0, 64, "One 100 mm wafer, four 52 mm exposures", size=4.6, weight="600")
    fig.text(0, 59.5,
             "field centers at X,Y = +/-25.4 mm   .   1.2 mm total overlap at every seam",
             "muted", 2.9)
    fig.text(0, -59, "primary flat faces the operator (-Y);  dashed ring is the 2 mm edge bead",
             "muted", 2.6)
    fig.text(reach + 1, 14, "overlap", "warn", 2.6, anchor="start")
    fig.text(reach + 1, 10.6, "bands", "warn", 2.6, anchor="start")
    return "wafer_and_fields.svg", fig.render(900)


def fig_partition():
    fig = Fig(margin=5)
    cuts = master_cuts()

    def clip_box(station):
        cx, cy = station.field_center_mm
        sx, sy = (1 if cx > 0 else -1), (1 if cy > 0 else -1)
        return (
            -SEAM_HALF if sx > 0 else cx - HALF_FIELD,
            -SEAM_HALF if sy > 0 else cy - HALF_FIELD,
            cx + HALF_FIELD if sx > 0 else SEAM_HALF,
            cy + HALF_FIELD if sy > 0 else SEAM_HALF,
        )

    for station in STATIONS:
        left, bottom, right, top = clip_box(station)
        color = STATION_COLORS[station.label]
        fig.rect(left, bottom, right, top, "", f'fill="{color}" opacity="0.14" stroke="none"')
        fig.rect(left, bottom, right, top, "",
                 f'fill="none" stroke="{color}" stroke-width="0.45" stroke-dasharray="1.4 1.1"')
    add_cuts(fig, cuts, 0.18)
    fig.line(-52, 0, 52, 0, "s-ink", 'stroke-width="0.22"')
    fig.line(0, -52, 0, 52, "s-ink", 'stroke-width="0.22"')

    for station in STATIONS:
        cx, cy = station.field_center_mm
        fig.text(cx, cy - 1.2, station.label, size=3.8, weight="600",
                 fill=STATION_COLORS[station.label])

    # 8x zoom on the seam crossing, where the 1.2 mm overlap actually lives.
    zoom, window, ox, oy = 8.0, 3.2, 96.0, 0.0
    fig.rect(ox - window * zoom, oy - window * zoom, ox + window * zoom, oy + window * zoom,
             "s-muted", 'fill="none" stroke-width="0.4"')
    for station in STATIONS:
        left, bottom, right, top = clip_box(station)
        left, bottom = max(left, -window), max(bottom, -window)
        right, top = min(right, window), min(top, window)
        if right <= left or top <= bottom:
            continue
        color = STATION_COLORS[station.label]
        fig.rect(ox + left * zoom, oy + bottom * zoom, ox + right * zoom, oy + top * zoom,
                 "", f'fill="{color}" opacity="0.20" stroke="{color}" stroke-width="0.5"')
    fig.line(ox - window * zoom, oy, ox + window * zoom, oy, "s-ink", 'stroke-width="0.25"')
    fig.line(ox, oy - window * zoom, ox, oy + window * zoom, "s-ink", 'stroke-width="0.25"')
    fig.rect(ox - SEAM_HALF * zoom, oy - window * zoom, ox + SEAM_HALF * zoom, oy + window * zoom,
             "overlap")
    fig.rect(ox - window * zoom, oy - SEAM_HALF * zoom, ox + window * zoom, oy + SEAM_HALF * zoom,
             "overlap")
    fig.line(ox - SEAM_HALF * zoom, oy - window * zoom - 2, ox + SEAM_HALF * zoom,
             oy - window * zoom - 2, "s-warn", 'stroke-width="0.4"')
    fig.text(ox, oy - window * zoom - 5.5, "1.2 mm", "warn", 2.8)
    fig.text(ox, oy + window * zoom + 2.2, "seam crossing at 8x", "muted", 2.7)
    fig.text(ox, oy + window * zoom + 6.0, "each job reaches 0.6 mm past X=0 and Y=0", "muted", 2.5)

    fig.text(22, 62, "partition mode: one owner per quadrant", size=4.4, weight="600")
    fig.text(22, 57.6, "geometry is cut once, not twice, except inside the deliberate overlap",
             "muted", 2.8)
    fig.text(-52, -58, "X = 0 and Y = 0 are the nominal seams", "muted", 2.6, anchor="start")
    return "partition_ownership.svg", fig.render(1000)


def fig_translation():
    station = STATIONS[0]  # DXF11, the jig top-left station
    cx, cy = station.field_center_mm
    color = STATION_COLORS[station.label]
    fig = Fig(margin=5)

    left, right = -SEAM_HALF, cx + HALF_FIELD
    bottom, top = cy - HALF_FIELD, SEAM_HALF

    fig.poly(wafer_outline(WAFER_RADIUS), "wafer", 'stroke-width="0.4"')
    add_cuts(fig, master_cuts(), 0.18)
    fig.rect(left, bottom, right, top, "", f'fill="{color}" opacity="0.17" stroke="none"')
    fig.rect(left, bottom, right, top, "",
             f'fill="none" stroke="{color}" stroke-width="0.55"')
    fig.circle(cx, cy, 1.1, "", f'fill="{color}"')
    fig.line(-52, 0, 52, 0, "s-muted", 'stroke-width="0.2"')
    fig.line(0, -52, 0, 52, "s-muted", 'stroke-width="0.2"')
    fig.text(0, 58, "1.  clip in wafer coordinates", size=3.8, weight="600")
    fig.text(cx, cy + 2.4, f"field center ({cx:+.1f}, {cy:+.1f})", "muted", 2.5)
    fig.text(0, -58, f"{station.label} owns the wafer's {station.exposed_wafer_area.replace('_','-')}",
             "muted", 2.6)

    # Second panel: the same tile after the splitter's translation.
    shift = 122.0
    fig.rect(shift - HALF_FIELD, -HALF_FIELD, shift + HALF_FIELD, HALF_FIELD,
             "", f'fill="{color}" opacity="0.17" stroke="none"')
    fig.rect(shift - HALF_FIELD, -HALF_FIELD, shift + HALF_FIELD, HALF_FIELD,
             "", f'fill="none" stroke="{color}" stroke-width="0.55"')
    kept = []
    for poly in master_cuts():
        moved = [(x - cx, y - cy) for x, y in poly]
        if all(-HALF_FIELD <= x <= HALF_FIELD and -HALF_FIELD <= y <= HALF_FIELD for x, y in moved):
            kept.append(moved)
    add_cuts(fig, kept, 0.18, offset=(shift, 0.0))
    fig.line(shift - 29, 0, shift + 29, 0, "s-muted", 'stroke-width="0.2"')
    fig.line(shift, -29, shift, 29, "s-muted", 'stroke-width="0.2"')
    fig.circle(shift, 0, 1.1, "", f'fill="{color}"')

    size = 0.6  # 50 um anchors, drawn 12x oversized so they are visible at all
    for sx in (-1, 1):
        for sy in (-1, 1):
            ax = shift + (-REGISTRATION_HALF_SIZE_MM if sx < 0 else REGISTRATION_HALF_SIZE_MM - size)
            ay = -REGISTRATION_HALF_SIZE_MM if sy < 0 else REGISTRATION_HALF_SIZE_MM - size
            fig.rect(ax, ay, ax + size, ay + size, "anchor")

    fig.text(shift, 58, "2.  translate so the field center is (0,0)", size=3.8, weight="600")
    fig.text(shift, -58, f"four anchors lock content bounds to +/-{REGISTRATION_HALF_SIZE_MM:.0f} mm",
             "warn", 2.6)
    fig.text(shift, -61.8, "on REGISTRATION_DO_NOT_EXPOSE  (never exposed)", "muted", 2.4)

    mid = (right + shift - HALF_FIELD) / 2.0
    fig.line(mid - 9, 0, mid + 9, 0, "s-ink", 'stroke-width="0.7" marker-end="url(#arrow)"')
    fig.text(mid, 3.4, f"{-cx:+.1f}, {-cy:+.1f} mm", "muted", 2.6)
    return "tile_translation.svg", fig.render(1050)


def fig_jig_inversion():
    station = STATIONS[0]
    color = STATION_COLORS[station.label]
    fig = Fig(margin=6)

    for column in range(8):
        for row in range(8):
            hx, hy = hole_coordinate_mm(column, row)
            fig.circle(hx, hy, 3.0, "hole", 'stroke-width="0.45"')

    wx, wy = station.wafer_center_mm
    fig.rect(wx - 64, wy - 64, wx + 64, wy + 64, "plate", 'stroke-width="0.7" rx="2"')
    # Absolute coordinates, not a nested translate, so every point in the file
    # can be checked against the viewBox directly.
    fig.poly([(x + wx, y + wy) for x, y in wafer_outline(WAFER_RADIUS)], "wafer",
             'stroke-width="0.55"')
    for columns, rows in ((station.outer_columns, station.outer_rows),
                          (station.inner_columns, station.inner_rows)):
        for column in columns:
            for row in rows:
                hx, hy = hole_coordinate_mm(column, row)
                fig.circle(hx, hy, 2.4, "", f'fill="{color}"')

    column, row = station.outer_front_right_pin
    hx, hy = hole_coordinate_mm(column, row)
    fig.circle(hx, hy, 5.8, "s-warn", 'stroke-width="0.8"')

    lx, ly = LASER_ZERO
    fig.rect(lx - HALF_FIELD, ly - HALF_FIELD, lx + HALF_FIELD, ly + HALF_FIELD, "s-warn",
             'stroke-width="0.9" stroke-dasharray="2.4 1.6"')
    fig.circle(lx, ly, 1.5, "warn")

    fig.text(100, 214, "the top-left jig station exposes the wafer's bottom-right",
             size=5.0, weight="600")
    fig.text(100, 208, "the laser field never moves; the wafer moves under it", "muted", 3.0)
    fig.text(hx + 8, hy - 1, f"engraved hole  C{column} R{row}", "warn", 3.0, anchor="start")
    fig.text(lx, ly + HALF_FIELD + 2.6, "52 mm field at laser zero (96.19, 109.35)", "warn", 3.0)
    fig.text(wx, wy + 67, f"plate at station {station.jig_station.replace('_', '-')} "
                          f"({station.label})", "muted", 3.0, fill=color)
    fig.text(2, 2, "C0 = table left,  R0 = table front", "muted", 2.9, anchor="start")
    fig.text(198, 6, "jig moves left and rearward", "muted", 2.9, anchor="end")
    fig.text(198, 1.8, "so the exposed area moves right and forward", "muted", 2.9, anchor="end")
    return "jig_inversion.svg", fig.render(900)


def fig_registration():
    """The real failure, using the real content bounds of the two shipped sets."""
    fig = Fig(margin=6)
    pair = ("DXF12", "DXF22")
    width, gap = 16.0, 26.0

    def panel(ox: float, base: Path, layer, title: str, subtitle: str, good: bool):
        centers = []
        for index, label in enumerate(pair):
            _, bottom, _, top = bbox_mm(base / label / "Horizontal.dxf", layer)
            x = ox + index * gap
            color = STATION_COLORS[label]
            fig.rect(x, bottom, x + width, top, "",
                     f'fill="{color}" opacity="0.16" stroke="{color}" stroke-width="0.5"')
            middle = (bottom + top) / 2.0
            centers.append(middle)
            fig.line(x - 2.5, middle, x + width + 2.5, middle,
                     "s-muted" if good else "s-warn", 'stroke-width="0.45" stroke-dasharray="2 1.4"')
            fig.text(x + width / 2, top + 1.6, label, size=3.2, weight="600", fill=color)
            fig.text(x + width / 2, bottom - 4.2, f"Y {bottom:.3f}", "muted", 2.4)
            fig.text(x + width / 2, bottom - 7.4, f"to {top:.3f}", "muted", 2.4)
            fig.text(x + width + 3.5, middle - 0.9, f"center {middle:+.4f}",
                     "muted" if good else "warn", 2.5, anchor="start")

        delta = abs(centers[1] - centers[0])
        span = ox + gap + width + 22
        fig.text(ox + (gap + width) / 2, 44, title, size=3.8, weight="600",
                 fill="" if good else "#cf222e")
        fig.text(ox + (gap + width) / 2, 39.6, subtitle, "muted", 2.7)
        if delta > 0.0005:
            fig.line(span, centers[0], span, centers[1], "s-warn",
                     'stroke-width="0.7" marker-start="url(#arrow)" marker-end="url(#arrow)"')
            fig.text(span + 2, (centers[0] + centers[1]) / 2 - 1, f"{delta:.4f} mm", "warn",
                     3.0, anchor="start", weight="600")
            fig.text(span + 2, (centers[0] + centers[1]) / 2 - 4.6, "relative Y error", "warn",
                     2.5, anchor="start")
        else:
            fig.text(span + 2, centers[0] - 1, "0 mm error", "muted", 3.0, anchor="start",
                     weight="600")
        return delta

    panel(0, FAILED_SET, None, "layer 0 only", "content bounds differ per file", good=False)
    panel(118, LOCKED_SET, "REGISTRATION_DO_NOT_EXPOSE",
          "with registration anchors", "bounds identical in every file", good=True)

    fig.text(88, 56, "why the anchors exist", size=5.0, weight="600")
    fig.text(88, 50.5, "measured from the two sets in this repository, horizontal pass",
             "muted", 2.9)
    fig.text(88, -36, "dashed line is the bounding-box center an auto-centering importer "
                      "would align to", "muted", 2.7)
    fig.text(88, -40.5, "bars show each file's content bounds in Y, the axis the failure "
                        "appeared on", "muted", 2.7)
    return "registration_envelope.svg", fig.render(1050)


def main() -> int:
    os.chdir(REPO_ROOT)
    FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    for builder in (fig_wafer_and_fields, fig_partition, fig_translation,
                    fig_jig_inversion, fig_registration):
        name, svg = builder()
        path = FIGURE_DIR / name
        path.write_text(svg + "\n", encoding="utf-8")
        head = svg.split("\n", 1)[0]
        size = head.split('viewBox="')[1].split('"')[0]
        print(f"wrote {path.as_posix():44} {path.stat().st_size / 1024:6.1f} kB  viewBox {size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
