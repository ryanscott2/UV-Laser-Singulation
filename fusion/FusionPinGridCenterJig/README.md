# Fusion four-pin center-field wafer jig

This Fusion script creates a 100 mm wafer nest that centers the wafer at the
directly measured laser-zero location using four pins in the table's 1 inch
hole grid. Its mechanical geometry matches `FusionPinGridJig`; the separate
package provides center-field filenames and an unambiguous center placement
map.

## Center placement

Number grid columns from the left and rows from the front, starting at zero.
Place the pins as follows:

- Four pins: columns `1 and 5`, rows `2 and 6`.
- Side pickup tabs: one centered on the left and right edges, `10.000 mm` out
  by `24.000 mm` long, spanning z `2.000` to `6.000 mm`. The `2.000 mm` undercut
  beneath each is what a fingernail or tweezer tip hooks into to lift the plate
  off its pins. Overall width including both tabs: `148.000 mm`
- Common pin-pattern center: grid column `3`, row `4`.
- Pattern-center table coordinate: `(88.900,114.300) mm`.
- Nest offset from pattern center: `X=+7.290 mm`, `Y=-4.950 mm`.
- Resulting wafer center: `(96.190,109.350) mm`, matching measured laser zero.
- Engraved outer front-right pin: `C5 R2`, at table `(139.700,63.500) mm`.
- Three floor engravings, each cut `0.500 mm` into the baseplate:
  `CENTER FIELD ALIGNER` and `C5 R2` at top-left, `C0=LEFT R0=FRONT` at
  front-left, and `ALIGNMENT PIN` at front-right.

### Reading the plate

The engraving gives **one hole**: the outer front-right pin, the one to the right
of the wafer's primary flat. The four-pin pattern is rigid, so seating that
single pin fixes the other three. It sits two grid spaces right and two spaces
forward of the pin-pattern center, the same convention the four-position plate
uses.

The `ALIGNMENT PIN` label is engraved at the front-right of the plate, next to the
pin it names. With the inner 2 x 2 set removed there is only one front-right pin,
out near the platform corner, so the reference is unambiguous.

## Dimensions and tolerances

- Grid pitch: `25.400 mm`; first hole inset: `12.700 mm`.
- Measured hole opening: `6.000 mm`; threaded minor diameter: `4.870 mm`.
- Four pins, each `4.650 mm` diameter.
- Nominal thread-minor clearance: `0.220 mm` diametral, `0.110 mm` radial.
- Pin engagement: `5.000 mm`; final `1.000 mm` tapers from 4.0 to 4.65 mm.
- Outer pin square: `101.600 x 101.600 mm` (`4 x 4` grid spaces).
- Platform: `128.000 x 128.000 x 2.000 mm`.
- Perimeter reinforcement: `4.000 mm` wide x `4.000 mm` high above the
  platform.
- Wafer: `100.000 mm`; primary flat `32.500 mm`; secondary flat `18.000 mm`.
- Sidewall: `3.000 mm` thick and `1.500 mm` above the platform.
- Radial clearance: `0.500 mm` per side.
- Primary-flat clearance: `0.500 mm`.
- Secondary-flat datum clearance: `0.100 mm`.
- Pickup opening: `15.000 mm` with a 45 degree bevel; the 2 mm base remains
  continuous.
- Rear tape gap: `15.000 mm`, same bevel, opposite the primary flat.
- Perimeter-bar tweezer notch: `15.000 mm` at the base and `23.400 mm` at the
  top, with 45 degree sides aligned to the wafer pickup opening.

## Run

1. In Fusion, press **Shift+S**.
2. On the Scripts tab, click **+** and select this folder.
3. Select `FusionPinGridCenterJig` and click **Run**.

The script exports `pin_grid_center_wafer_jig.f3d` and
`pin_grid_center_wafer_jig.step` beside itself, plus a high-quality binary
`pin_grid_center_wafer_jig.stl` in the shared `fusion/print-files` folder.

Print with the platform upward and apply local support only beneath the eight
downward pins. Verify a pin-fit coupon and table seating before using a wafer.
