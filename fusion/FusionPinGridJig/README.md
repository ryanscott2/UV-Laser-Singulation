# Fusion four-pin grid wafer jig

This Fusion script creates one compact 100 mm wafer nest that indexes directly
into the table's 1 inch hole grid. Four downward pins are underneath the
platform, so neither table width nor a front-edge alignment bar is used.

## Fixed geometry

- Grid pitch: `25.400 mm`
- Indexing move: two grid spaces = `50.800 mm`
- Pin pattern: four corners of a `101.600 x 101.600 mm` square (`4 x 4` spaces)
- Total pins: `4`
- Side pickup tabs: one centered on the left and right edges, `10.000 mm` out
  by `24.000 mm` long, spanning z `2.000` to `6.000 mm`. The `2.000 mm` undercut
  beneath each is what a fingernail or tweezer tip hooks into to lift the plate
  off its pins. Overall width including both tabs: `148.000 mm`
- Pin diameter: `4.650 mm`
- Pin engagement below platform: `5.000 mm`
- Tapered pin tip: `4.000 mm` diameter over the final `1.000 mm`
- Platform: `128.000 x 128.000 x 2.000 mm`
- Perimeter reinforcement: continuous `4.000 mm` wide x `4.000 mm` high bar
  above the platform
- Wafer: standard 100 mm, primary flat forward, secondary flat left
- Nest lip: `1.500 mm` above the platform
- Pickup opening: `15.000 mm`, beveled at 45 degrees, without cutting the base
- Rear tape gap: `15.000 mm`, same 45 degree bevel, opposite the primary flat
- Perimeter-bar notches: `15.000 mm` at the base, flaring to `23.400 mm` at the
  top with 45 degree sides. One aligned with the pickup opening, one with the
  rear tape gap
- Three floor engravings, each cut `0.500 mm` into the `2.000 mm` baseplate:
  `2x2 SINGULATION ALIGNER` plus the four single-hole station coordinates at
  top-left, `C0=LEFT R0=FRONT` at front-left, `ALIGNMENT PIN` at front-right

The measured threaded-hole minor diameter was `4.870 mm`, giving a nominal
`0.220 mm` diametral clearance around each 4.650 mm pin. Print a small pin-fit
coupon first because PLA extrusion and the thread crests can change the actual
fit.

## Hole positions and exposure folders

Number grid columns from the left and rows from the front, starting at zero.
The first hole center is assumed to be 12.7 mm from each edge.

Folder labels name the **jig station**, read like a matrix: the first digit is
the row from the table rear (`1` = top/rear, `2` = bottom/front) and the second
is the column from the table left (`1` = left, `2` = right).

| Folder | Jig station | Engraved front-right pin | Pin columns/rows | Exposed area |
| --- | --- | --- | --- | --- |
| `DXF11` | top-left (rear-left) | `C4 R3` | columns `0,4`; rows `3,7` | bottom-right |
| `DXF12` | top-right (rear-right) | `C6 R3` | columns `2,6`; rows `3,7` | bottom-left |
| `DXF21` | bottom-left (front-left) | `C4 R1` | columns `0,4`; rows `1,5` | top-right |
| `DXF22` | bottom-right (front-right) | `C6 R1` | columns `2,6`; rows `1,5` | top-left |

### Reading the plate

The engraving gives **one hole per station**: the outer front-right pin, the one
to the right of the wafer's primary flat. The four-pin pattern is rigid, so
seating that single pin fixes the other three. It always lands two grid spaces
right and two spaces forward of the pin-pattern center.

Coordinates are abbreviated `C` (column) and `R` (row), so `21 C4 R1` seats the
alignment pin in the hole at column 4, row 1. The heading reads
`2x2 SINGULATION ALIGNER` and the four label rows are listed rear-first so they
match the plate's orientation on the table.

Two further engravings sit along the front edge, where the operator reads them:
`C0=LEFT R0=FRONT` at front-left preserves the counting convention, and
`ALIGNMENT PIN` at front-right names the outer pin nearest that corner, which is
the pin every engraved coordinate refers to. Both are placed forward of the
wafer pocket and outboard of the pickup notch, keeping about `5 mm` to the
pocket wall.

The `ALIGNMENT PIN` label is engraved at the front-right of the plate, next to the
pin it names. With the inner 2 x 2 set removed there is only one front-right pin,
out near the platform corner, so the reference is unambiguous.

The outer square is not centered on the platform, because the nest is offset
from the pin-pattern center by `X=+7.290 mm`, `Y=-4.950 mm`. Measured from the
platform edges the outer pins sit `5.91 mm` from the left, `20.49 mm` from the
right, `18.15 mm` from the front, and `8.25 mm` from the rear.

The nest center is offset from the common pin-pattern center by `X=+7.290 mm`,
`Y=-4.950 mm`. This uses the authoritative laser-zero location
`(96.190,109.350) mm` and produces exposure centers at `+/-25.400 mm` on the
wafer.

Moving the jig right exposes farther left on the wafer; moving it away from the
operator exposes farther toward the wafer's primary flat. Both axes therefore
invert, and each station exposes the diagonally opposite wafer quadrant. This is
why `DXF11`, the top-left station, carries the wafer's bottom-right geometry.

## Wafer fit

- Radial clearance: `0.500 mm` per side
- Primary-flat clearance: `0.500 mm`
- Secondary-flat rotational datum clearance: `0.300 mm`
- Sidewall thickness: `3.000 mm`

## Run

1. In Fusion, press **Shift+S**.
2. On the Scripts tab, click **+** and select this folder.
3. Select `FusionPinGridJig` and click **Run**.

The script creates an editable design and exports `pin_grid_wafer_jig.f3d` and
`pin_grid_wafer_jig.step` beside itself. It also exports a high-quality binary
`pin_grid_wafer_jig.stl` to the shared `fusion/print-files` folder.

Print with the 2 mm wafer platform upward. The downward pins will require local
support; use support blockers everywhere except beneath the four pins. Verify
pin fit and flatness on the table before placing a real wafer in the nest.
