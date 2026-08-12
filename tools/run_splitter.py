"""Command-line front end for the four-window splitter.

The splitter reads its overrides out of `globals()`, which is KLayout's `-rd`
mechanism, so `python python/split_klayout_four_windows.py` cannot be
parameterized on its own. This wraps it with ordinary arguments and needs only
the standalone `klayout` wheel.

    python tools/run_splitter.py --input wafer.dxf --layer CUT --cut-width 40

`inspect_layers` is also used by the GUI to populate its layer list.
"""

from __future__ import annotations

import argparse
import runpy
from dataclasses import dataclass
from pathlib import Path

import klayout.db as pya

REPO_ROOT = Path(__file__).resolve().parent.parent
SPLITTER = REPO_ROOT / "python" / "split_klayout_four_windows.py"
DXF_UNIT_UM = 1_000.0


@dataclass(frozen=True)
class LayerInfo:
    """One layer in the source file, with enough detail to choose sensibly."""

    selector: str  # what to pass as --layer
    name: str
    layer: int
    datatype: int
    polygons: int
    paths: int
    widths_um: tuple[float, ...]
    area_mm2: float
    bbox_mm: tuple[float, float, float, float] | None

    def describe(self) -> str:
        label = self.name or f"{self.layer}/{self.datatype}"
        parts = [f"{label:<24}"]
        parts.append(f"{self.polygons:>6} poly")
        parts.append(f"{self.paths:>5} path")
        parts.append(f"{self.area_mm2:>10.4f} mm2")
        if self.widths_um:
            shown = ", ".join(f"{w:g}" for w in self.widths_um[:4])
            more = ", ..." if len(self.widths_um) > 4 else ""
            parts.append(f"widths um: {shown}{more}")
        return "  ".join(parts)


def inspect_layers(path: Path) -> list[LayerInfo]:
    """List every layer in a DXF/GDS/OAS with shape counts and path widths."""
    layout = pya.Layout()
    if path.suffix.lower() == ".dxf":
        options = pya.LoadLayoutOptions()
        options.dxf_unit = DXF_UNIT_UM
        layout.read(str(path), options)
    else:
        layout.read(str(path))

    scale = layout.dbu / 1000.0  # dbu -> mm
    found: list[LayerInfo] = []
    for index in layout.layer_indices():
        info = layout.get_info(index)
        name = str(getattr(info, "name", "") or "")
        polygons = paths = 0
        widths: set[float] = set()
        for cell in layout.each_cell():
            for shape in cell.each_shape(index):
                if shape.is_path():
                    paths += 1
                    widths.add(round(abs(shape.path_width) * layout.dbu, 4))
                else:
                    polygons += 1

        region = pya.Region()
        for top in layout.top_cells():
            region += pya.Region(top.begin_shapes_rec(index))
        region = region.merged()
        box = region.bbox() if not region.is_empty() else None
        found.append(
            LayerInfo(
                # A name is what a DXF user recognises; fall back to the numbers.
                selector=name if name else f"{info.layer}/{info.datatype}",
                name=name,
                layer=info.layer,
                datatype=info.datatype,
                polygons=polygons,
                paths=paths,
                widths_um=tuple(sorted(widths)),
                area_mm2=region.area() * (layout.dbu**2) / 1_000_000.0,
                bbox_mm=None if box is None else (
                    box.left * scale, box.bottom * scale, box.right * scale, box.top * scale
                ),
            )
        )
    return found


def splitter_globals(args: argparse.Namespace) -> dict[str, object]:
    """Build the -rd style overrides the splitter reads out of globals()."""
    values: dict[str, object] = {
        "input": str(args.input),
        "max_cut_width_um": str(args.cut_width),
        "cut_width_mode": args.width_mode,
        "clip_mode": args.clip_mode,
        "global_x_um": str(args.global_x),
        "global_y_um": str(args.global_y),
        "allow_geometry_outside_fields": "1" if args.allow_outside else "0",
        "output_extension": args.extension,
    }
    if args.output is not None:
        values["output_dir"] = str(args.output)
    if args.layer:
        values["source_layer"] = args.layer
    if args.stitch is not None:
        values["stitch_overlap_um"] = str(args.stitch)
    if args.offset:
        values["window_offsets"] = ";".join(
            spec.replace("=", ":") for spec in args.offset
        )
    return values


def run(args: argparse.Namespace) -> None:
    runpy.run_path(str(SPLITTER), init_globals=splitter_globals(args), run_name="__main__")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Split wafer cut geometry into four laser-centered jobs.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--input", type=Path, help="source DXF, GDS, or OAS")
    parser.add_argument("--output", type=Path, default=None,
                        help="output directory (default: beside the input)")
    parser.add_argument("--layer", default="",
                        help="cutline layer: a name like CUT, or 7, or 7/2. "
                             "Blank uses layer 0/0 or a layer named '0'")
    parser.add_argument("--cut-width", type=float, default=50.0,
                        help="cutline width in microns, applied to native paths")
    parser.add_argument("--width-mode", choices=("cap", "force"), default="cap",
                        help="cap narrows wider paths only; force sets every path to the width")
    parser.add_argument("--clip-mode", choices=("partition", "full_window"), default="partition")
    parser.add_argument("--stitch", type=float, default=None,
                        help="total seam overlap in microns; must keep "
                             "field == 2*center + stitch")
    parser.add_argument("--global-x", type=float, default=0.0,
                        help="calibration shift applied to every output, microns")
    parser.add_argument("--global-y", type=float, default=0.0)
    parser.add_argument("--offset", action="append", metavar="LABEL=X,Y", default=[],
                        help="per-station nudge in microns on top of the global offset, "
                             "e.g. --offset P4=0,-18.5 . Repeatable")
    parser.add_argument("--extension", default=".dxf", help=".dxf, .gds, or .oas")
    parser.add_argument("--allow-outside", action="store_true",
                        help="permit discarding geometry outside all four windows")
    parser.add_argument("--list-layers", action="store_true",
                        help="list the layers in --input and exit")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.input is None:
        build_parser().error("--input is required")
    if not args.input.is_file():
        build_parser().error(f"input not found: {args.input}")

    if args.list_layers:
        layers = inspect_layers(args.input)
        if not layers:
            print("No layers found.")
            return 1
        print(f"Layers in {args.input.name}:\n")
        for entry in layers:
            print(f"  --layer {entry.selector:<16} {entry.describe()}")
        return 0

    run(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
