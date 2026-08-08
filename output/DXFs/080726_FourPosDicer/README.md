# 100 mm wafer, 10 x 30 mm dice — old-jig test set

> **Superseded, and labeled the old way.** This set predates the 2026-08-08
> convention change. Folders here are named for the **exposed wafer quadrant**,
> so `DXF11` holds the wafer's top-left. Current sets name the **jig station**,
> where `DXF11` is the top-left jig position and holds the wafer's bottom-right.
> Converting swaps `11` and `22` and leaves `12` and `21` alone. Do not mix files
> from this set with a current one, and do not run it on the pin-grid jig.

> This is additionally the run that **failed on the machine**: it carries no
> registration anchors, so the laser importer auto-centered each file on its own
> content bounds and displaced the bottom-right horizontal pass by about `8 mm`.
> Kept only as the record of that failure.

This output was generated with `generate_100mm_10x30mm_masters.py` and split
twice with the since-removed `split_klayout_four_windows_old_jig_test.py`: once for the vertical
master and once for the horizontal master. The same splitter accepts DXF, GDS,
and OAS input through KLayout.

## Folder coordinates

The two digits in `DXFxy` identify the exposed wafer area:

- X1 = wafer left; X2 = wafer right.
- Y1 = wafer rear/top; Y2 = wafer front/bottom.

| Folder | Wafer area | Physical field center in wafer coordinates |
| --- | --- | ---: |
| `DXF11` | left, rear/top | `(-28.982, +26.678) mm` |
| `DXF12` | left, front/bottom | `(-28.982, -23.322) mm` |
| `DXF21` | right, rear/top | `(+21.018, +26.678) mm` |
| `DXF22` | right, front/bottom | `(+21.018, -23.322) mm` |

Each folder contains exactly `Horizontal.dxf` and `Vertical.dxf`. Run both at
that jig position without moving the jig or wafer between files.

## Geometry

- Nominal wafer: 100 mm, primary flat forward and secondary flat left.
- Dice pitch: 10 mm in X and 30 mm in Y.
- Vertical cut centers: `+/-5, +/-15, +/-25, +/-35, +/-45 mm`.
- Horizontal cut centers: `+/-15, +/-45 mm`.
- Cut-feature width: 50 um.
- Protected edge: true 2 mm inward offset from the circular edge and both flats.
- Alignment marker: one centered plus, 2.5 mm long with 50 um arms, included
  only in `DXF22/Horizontal.dxf` by the non-overlapping partition.
- All output geometry is on literal DXF layer `0` with millimeter drawing units.

This set is compensated for the original printed four-position jig using the
window-pattern offset `X=-3.982 mm`, `Y=+1.678 mm`. It keeps each job inside the
centered 60 mm optical area, leaving 9.2425 mm to every 78.485 mm usable-field
edge. Do not use these files with the corrected jig.

Use a low-power sacrificial-wafer pass first and verify both the marker and a
few grid intersections before running the full dicing recipe.
