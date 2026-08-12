# 100 mm wafer, 10 x 30 mm dice - 52 mm pin-grid production set

> **Superseded on 2026-08-08** by
> [080826_FourPosDicer_PinGrid54mm](../080826_FourPosDicer_PinGrid54mm), which
> uses a 54 mm declared field and a 0.200 mm stitch instead of 52 mm and
> 1.200 mm. It also predates the removal of the inner four jig pins. Kept for
> traceability; do not mix its files with the current set.

This set uses the eight-pin grid jig and the production
`split_klayout.py` profile.

## Optical and stitch geometry

- Exposure/file bounds: `52.000 x 52.000 mm`.
- Field centers on wafer: `X,Y=+/-25.400 mm`.
- Physical move between neighboring positions: `50.800 mm` (two 1 inch grid
  spaces).
- Total field overlap: `1.200 mm`.
- Partition stitch overlap: `1.200 mm`, extending each job `0.600 mm` across
  the nominal X=0 and Y=0 seams.
- Margin from the 52 mm exposure to every edge of the `60 mm` usable field: `4 mm`
  (the galvo's full `78.485 mm` field is weaker at the edges, so only the central
  60 mm is used).
- All cutting geometry is on DXF layer `0`.
- Every file has four bounding anchors on `REGISTRATION_DO_NOT_EXPOSE`, fixing
  its content bounds at exactly `(-26,-26) to (+26,+26) mm`.

Set `REGISTRATION_DO_NOT_EXPOSE` to no marking / zero power. Never expose that
layer and never use fit-to-field scaling.

## Wafer and cut geometry

- Wafer diameter: `100.000 mm`.
- Edge bead/exclusion: `2.000 mm`, controlled by the single `EDGE_BEAD_MM`
  variable in `generate_100mm_10x30mm_masters.py`.
- Dice pitch: `10.000 mm` in X and `30.000 mm` in Y.
- Cut width: `50 um`.
- Alignment marker: centered 2.5 mm plus with 50 um arms. Because the `1.200 mm`
  stitch overlap puts wafer origin inside all four clip boxes, every
  `Horizontal.dxf` carries the fragment of the plus that falls in its own box;
  the four fragments reassemble into the whole marker.

## Folder and pin mapping

Grid columns count from table left and rows from table front, starting at zero.

Folder labels name the **jig station**, read like a matrix: the first digit is
the row from the table rear (`1` = top/rear, `2` = bottom/front) and the second
is the column from the table left (`1` = left, `2` = right). Indexing the jig
moves the wafer, not the laser, so each station exposes the diagonally opposite
wafer quadrant.

| Folder | Jig station | Exposure center | Exposed area | Engraved hole | Outer pins | Inner pins |
| --- | --- | ---: | --- | --- | --- | --- |
| `DXF11` | top-left | `(+25.4,-25.4) mm` | bottom-right | `C4 R3` | columns `0,4`; rows `3,7` | columns `1,3`; rows `4,6` |
| `DXF12` | top-right | `(-25.4,-25.4) mm` | bottom-left | `C6 R3` | columns `2,6`; rows `3,7` | columns `3,5`; rows `4,6` |
| `DXF21` | bottom-left | `(+25.4,+25.4) mm` | top-right | `C4 R1` | columns `0,4`; rows `1,5` | columns `1,3`; rows `2,4` |
| `DXF22` | bottom-right | `(-25.4,+25.4) mm` | top-left | `C6 R1` | columns `2,6`; rows `1,5` | columns `3,5`; rows `2,4` |

The engraved hole is the outer front-right pin, the single coordinate the jig
plate engraves for that station. Seating it fixes the other seven pins.

Each folder contains `Horizontal.dxf` and `Vertical.dxf`. Keep the jig and wafer
stationary between those two files.

## Relabeled 2026-08-08

This set originally labeled folders by the exposed wafer quadrant (`DXF11` =
wafer left-top). Labels now name the jig station instead. Only labels changed:
every DXF is byte-identical to the file it replaced, and the swap was exactly
`DXF11` <-> `DXF22`, with `DXF12` and `DXF21` keeping both name and contents.

| Exposed area | Old folder | New folder |
| --- | --- | --- |
| right-bottom | `DXF22` | `DXF11` |
| left-bottom | `DXF12` | `DXF12` |
| right-top | `DXF21` | `DXF21` |
| left-top | `DXF11` | `DXF22` |

The archived old-jig sets `output/DXFs/080726_FourPosDicer` and
`080726_FourPosDicer_OriginLocked` were left on the superseded wafer-quadrant
labeling for traceability.
