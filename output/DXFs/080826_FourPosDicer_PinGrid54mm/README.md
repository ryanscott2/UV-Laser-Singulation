# 100 mm wafer, 10 x 30 mm dice - 54 mm pin-grid production set

Current production set. Built and validated with:

```bash
python tools/build_pin_grid_set.py
```

```bash
python tools/validate_pin_grid_set.py
```

## Optical and stitch geometry

- Declared exposure window: `54.000 x 54.000 mm`. This is what the DXF header
  declares and where the registration anchors sit.
- Window actually occupied by each job: `51.000 mm`, being its own half of the
  `50.800 mm` pitch plus the stitch. It is centred in the 54 mm field, so there is
  `1.500 mm` of clear field on every side.
- Field centers on wafer: `X,Y = +/-25.400 mm`.
- Physical move between neighbouring stations: `50.800 mm`, two 1 inch grid spaces.
- Stitch overlap: `0.200 mm` total, so each job reaches `0.100 mm` past the nominal
  `X=0` and `Y=0` seams. That covers the `75-100 um` seam mismatch recorded in the
  calibration notes.
- Margin from the 54 mm window to every edge of the `60 mm` usable field: `3 mm`
  (the galvo's full `78.485 mm` field is weaker at the edges, so only the central
  60 mm is used).
- The stitch can be raised to `3.200 mm` before a window would exceed the declared
  field; the splitter refuses anything larger.
- All cutting geometry is on DXF layer `0`.
- Every file declares `$EXTMIN`/`$EXTMAX` at `+/-27.000 mm` and carries four
  `50 um` anchors on `REGISTRATION_DO_NOT_EXPOSE` with the same bounds.

Set `REGISTRATION_DO_NOT_EXPOSE` to no marking / zero power. Never expose that
layer and never use fit-to-field scaling.

## Wafer and cut geometry

- Wafer diameter: `100.000 mm`.
- Edge bead/exclusion: `2.000 mm`, from the single `EDGE_BEAD_MM` variable in
  `python/generate_100mm_10x30mm_masters.py`.
- Dice pitch: `10.000 mm` in X and `30.000 mm` in Y.
- Cut width: `50 um`.
- Alignment marker: centered 2.5 mm plus with 50 um arms. Wafer origin sits inside
  all four clip boxes, so every `Horizontal.dxf` carries the fragment of the plus
  that falls in its own box; the four fragments reassemble into the whole marker.

## Double exposure

Measured on this set:

| source | area at 2x dose | share of exposed area |
| --- | ---: | ---: |
| grid crossings, `Horizontal.dxf` meeting `Vertical.dxf` | `0.0700 mm2` in 28 spots | `0.14%` |
| seam overlap between neighbouring jobs | `0.4225 mm2` | `0.86%` |
| total | `0.4925 mm2` of `49.1333 mm2` | `1.00%` |

Acceptable here because the wafer is scored partway through rather than cut, and
the seam overlap is the deliberate stitch.

## Folder and pin mapping

Grid columns count from table left and rows from table front, starting at zero.

Folder labels name the **jig station**, read like a matrix: first digit is the row
from the table rear (`1` = top/rear, `2` = bottom/front), second is the column from
the table left (`1` = left, `2` = right). Indexing the jig moves the wafer, not the
laser, so each station exposes the diagonally opposite wafer quadrant.

Four locating pins per station, on the corners of a 4 x 4 grid-space square.

| Folder | Jig station | Exposure center | Exposed area | Engraved hole | Pin columns/rows |
| --- | --- | ---: | --- | --- | --- |
| `DXF11` | top-left | `(+25.4,-25.4) mm` | bottom-right | `C4 R3` | columns `0,4`; rows `3,7` |
| `DXF12` | top-right | `(-25.4,-25.4) mm` | bottom-left | `C6 R3` | columns `2,6`; rows `3,7` |
| `DXF21` | bottom-left | `(+25.4,+25.4) mm` | top-right | `C4 R1` | columns `0,4`; rows `1,5` |
| `DXF22` | bottom-right | `(-25.4,+25.4) mm` | top-left | `C6 R1` | columns `2,6`; rows `1,5` |

The engraved hole is the outer front-right pin, the single coordinate the jig plate
engraves for that station. Seating it fixes the other three.

Each folder contains `Horizontal.dxf` and `Vertical.dxf`. Keep the jig and wafer
stationary between those two files.

## What changed from the 52 mm set

`080726_FourPosDicer_PinGrid52mm` used a 52 mm field with a `1.200 mm` stitch, and
its window size was pinned to the field. The window size is now derived from the
pitch and the stitch alone, so the field is free to be larger than the window:

- field `52 -> 54 mm`, anchors and declared extents `+/-26 -> +/-27 mm`
- stitch `1.200 -> 0.200 mm`, so double-exposed area drops from `1.3925` to
  `0.4925 mm2`
- `CLIP_MODE` now has a real effect. At the old settings `partition` and
  `full_window` produced identical boxes; with a 54 mm field, `full_window` would
  overlap neighbours by `3.200 mm` and expose that whole band twice.
