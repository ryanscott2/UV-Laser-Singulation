# Four-window KLayout cutline splitter

`split_klayout_four_windows.py` reads wafer-centered cut geometry from layer 0
and writes four laser-centered jobs. It supports DXF, GDS, and OAS input through
KLayout. DXF input and output use millimeters; configuration values use microns.

This is the single production splitter and carries the 52 mm pin-grid profile.
An identical copy previously existed as `split_klayout_four_windows_pin_grid.py`;
it has been removed, so edit this file only.

## Important variables

Edit these near the top of the script:

- `INPUT_FILE`
- `OUTPUT_DIR`
- `GLOBAL_X_OFFSET_UM`
- `GLOBAL_Y_OFFSET_UM`
- `MAX_CUT_WIDTH_UM` (default `50.0`)
- `STITCH_OVERLAP_UM`
- `CLIP_MODE`
- `WRITE_DXF_HEADER_EXTENTS` (default `True`)
- `ALLOW_GEOMETRY_OUTSIDE_FIELDS` (default `False`)

Positive global X moves cut geometry right in every output. Positive global Y
moves it up. The global offsets do not alter the source file.

Native DXF/KLayout paths wider than `MAX_CUT_WIDTH_UM` are narrowed around
their existing centerlines before the four jobs are clipped. The default cap is
`50 um`; thinner paths are unchanged. Closed filled contours are polygons, not
paths, so their dimensions are preserved. The split log and manifest record how
many native paths were capped.

The default pin-grid `partition` mode uses `200 um` total stitch overlap: each
neighboring job extends `100 um` across X=0 and Y=0, which covers the 75-100 um
seam mismatch in the calibration notes.

`CLIP_MODE` matters at the production settings. `partition` gives each quadrant one
owner and adds the stitch, so a window is `2 x 25,400 + 200 = 51,000 um`.
`full_window` takes the whole `54,000 um` declared field instead, which overlaps
neighbours by `3,200 um` and exposes that entire band twice.

## Enforced window geometry

The window size is derived from the pitch and the stitch, not from the field, so
the declared field is free to be larger than the window. Every run checks:

1. The declared field must be at least as wide as a partition window,
   `2 * WINDOW_CENTER_UM + STITCH_OVERLAP_UM`, or geometry would fall outside the
   window the laser is told to expose. At a 54,000 um field the stitch may go up to
   `3,200 um`. Both window centers must also match, or the four windows are not a
   symmetric 2 x 2 tiling.
2. Each emitted window is asserted square, of the expected size, symmetric about
   its own field center once translated, and within the declared field.
3. Geometry outside all four windows is measured before clipping and stops the
   run, reporting the lost area and its bounds. Override with
   `-rd allow_geometry_outside_fields=1` when clipping it away is intended.

The split log and manifest record all three, plus any job that came out empty.

## Window mapping

Jobs are named for the **jig station** that produces them, read like a matrix:
the first digit is the row from the table rear (`1` = top/rear, `2` =
bottom/front) and the second is the column from the table left (`1` = left,
`2` = right).

Indexing the jig moves the wafer, not the laser, so both axes invert and each
station exposes the diagonally opposite wafer quadrant:

| Job | Jig station | Window center in wafer coordinates | Owned quadrant |
| --- | --- | ---: | --- |
| `DXF11_jig_top_left` | top-left | +25,400 um X; -25,400 um Y | right / bottom |
| `DXF12_jig_top_right` | top-right | -25,400 um X; -25,400 um Y | left / bottom |
| `DXF21_jig_bottom_left` | bottom-left | +25,400 um X; +25,400 um Y | right / top |
| `DXF22_jig_bottom_right` | bottom-right | -25,400 um X; +25,400 um Y | left / top |

Each output is translated so its own laser-field center is `(0, 0)`. A manifest
CSV records the jig station, exposed wafer area, clip box, translation, polygon
count, and output bounding box for every job.

## Run from PowerShell

Use KLayout's headless executable:

```powershell
& "$env:APPDATA\KLayout\klayout_vo_app.exe" -zz -rx -r .\python\split_klayout_four_windows.py -rd "input=.\dxf\100mm_10x30mm_Masters\100mm_wafer_10x30mm_Horizontal_master.dxf" -rd "output_dir=.\output\four_window_output" -rd "global_x_um=0" -rd "global_y_um=0" -rd "max_cut_width_um=50"
```

Run it from the repository root. The `-rd` values override the editable defaults
without modifying the script.

This script has no `argv` parsing of its own: overrides arrive through
`globals()`, which is KLayout's `-rd` mechanism. To drive it from plain Python
with the standalone `klayout` wheel, use the build tool, which injects those
same values and then assembles the labeled folder structure:

```bash
python tools/build_pin_grid_set.py
```

## Generated 100 mm dicing masters

`generate_100mm_10x30mm_masters.py` uses one top-level edge-bead setting in
millimeters:

```python
EDGE_BEAD_MM = 2.000
```

The same value is applied inward from the circular edge, primary flat, and
secondary flat. It can also be overridden with `-rd edge_bead_mm=...`.

## Outputs

- Four files named `DXF11_jig_top_left` through `DXF22_jig_bottom_right`
- A `window_manifest.csv`
- A `split_log.txt`

DXF outputs contain closed `LWPOLYLINE` cut polygons on literal layer `0` and
retain the source convention of 1 drawing unit = 1 mm.

Every DXF output declares its window twice.

The header carries `$EXTMIN` and `$EXTMAX` at exactly `+/-27.000 mm`, plus
`$INSBASE` at the origin and `$LIMMIN`/`$LIMMAX`. KLayout writes a header holding
only `$ACADVER`, leaving importers to infer the extent from entities; a declared
extent removes that inference and does not depend on layer visibility. Disable
with `-rd write_dxf_header_extents=0`.

Every output also contains four 50 um import-registration anchors on
`REGISTRATION_DO_NOT_EXPOSE` with the same `(-27,-27) to (+27,+27) mm` bounds, so
automatic drawing centering cannot shift jobs differently. The laser must be
configured to ignore this layer. Never expose the registration anchors.

The anchors are not sufficient on their own: an importer that computes extents
from marking layers only would skip a layer set to no marking. On a sparse
pattern, layer 0 alone yields `3 x 3 mm` boxes at four unrelated centers and two
files with no layer-0 geometry at all, while all four report the full declared
window about the origin once the anchors count. Hence both mechanisms.

The production field is `54 x 54 mm` and each job occupies `51 x 51 mm` of it,
centred, leaving `1.5 mm` of clear field on every side. A centred 54 mm job retains
`12.2425 mm` margin to every edge of the `78.485 mm` maximum usable field.

If the laser importer reliably preserves the drawing origin, the anchors can
be disabled with `-rd add_registration_envelope=0`.

## Original-jig calibration test

Use `split_klayout_four_windows_old_jig_test.py` only with the original printed
four-position jig. The directly measured `(0, 0)` cross showed that its four
physical laser-window centers are the nominal `+/-25 mm` grid shifted in wafer
coordinates by:

- X: `-3.982 mm` (`-3982 um`)
- Y: `+1.678 mm` (`+1678 um`)

The test profile moves both the clipping windows and their output translations.
Each output therefore remains within `-30 to +30 mm` about galvo zero, retaining
the full `(78.485 - 60) / 2 = 9.2425 mm` margin to every usable-field edge.
Do not use this profile with the corrected jig.

That legacy profile still emits the superseded `P1_right_top` .. `P4_left_bottom`
names, which are keyed to the exposed wafer quadrant rather than the jig station.
Those names appear in the archived old-jig build logs under `output/`, whose
delivered folders were renamed to `DXF11` .. `DXF22` by hand at the time.
