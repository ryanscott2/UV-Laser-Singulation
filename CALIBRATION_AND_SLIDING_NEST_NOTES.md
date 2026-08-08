# UV Dice calibration and sliding-nest notes

Last updated: 2026-08-08

## Coordinate convention

Position labels name the **jig station**, read like a matrix: the first digit is
the row from the table rear (`1` = top/rear, `2` = bottom/front) and the second
is the column from the table left (`1` = left, `2` = right).

Indexing the jig moves the wafer, not the laser, so both axes invert and each
station exposes the diagonally opposite wafer quadrant.

| Label | Jig station | Exposed wafer area |
| --- | --- | --- |
| `DXF11` | top-left | bottom-right |
| `DXF12` | top-right | bottom-left |
| `DXF21` | bottom-left | top-right |
| `DXF22` | bottom-right | top-left |

Adopted 2026-08-08. The previous scheme labeled by exposed wafer quadrant
(`DXF11` = wafer top-left). Converting between them swaps `11` and `22` and
leaves `12` and `21` unchanged, which makes a mislabeled file easy to miss:
always confirm against the jig station, not the digits alone. Measurements
recorded below under the earlier heading dates use the old scheme where noted.

## Preliminary four-position seam measurements

Labels in this section and the next use the **superseded wafer-quadrant scheme**,
matching the archived old-jig output folders they describe. They are left as
recorded; do not renumber them.

These observations came from the first partial test image and must be checked
again after the full sample is run. No software correction has been applied yet.

- Approximate cut width used as the visual scale: `50 um`.
- Top-right (`DXF21`) appears approximately `10-20 um` higher than top-left
  (`DXF11`). Candidate correction: move `DXF21` down by the measured amount,
  after confirming the image and machine Y directions.
- The lines appear not to meet at the middle seam by approximately `75-100 um`.
- Candidate gap treatment after full-sample measurements: add approximately
  `75-100 um` total stitch overlap, or distribute approximately `37.5-50 um`
  extension to each neighboring exposure.
- Measure several locations along every seam before correcting. A constant
  error indicates translation; a changing error along a seam indicates rotation
  or skew and should not be treated as translation alone.

## Full-wafer bottom-right failure (2026-08-07)

- The full-wafer photograph shows the bottom-right horizontal pass (`DXF22`)
  displaced downward by approximately `8 mm` relative to the bottom-left pass
  (`DXF12`). This is roughly `160` nominal 50 um cut widths. Allow about
  `+/-1 mm` uncertainty from perspective, glare, and the photographed line bloom.
- Do **not** treat this as an 8 mm jig correction. The generated bottom-row
  horizontal cut occupies exactly the same local Y range in both files:
  `8.297 to 8.347 mm`.
- The likely cause is per-file automatic centering during import. The
  `DXF12/Horizontal.dxf` bounding-box center is `Y=-6.678 mm`; the centered
  alignment marker expands `DXF22/Horizontal.dxf` so its bounding-box center is
  `Y=+1.4345 mm`. Centering each file independently therefore produces an
  `8.1125 mm` relative Y error, matching the photographed bottom-right step in
  both magnitude and direction.
- The raw DXFs contain entity coordinates but no common `$INSBASE`, `$EXTMIN`,
  or `$EXTMAX` header. The splitter also emits only clipped geometry, so every
  DXF/GDS job has a different content bounding box. Any laser import option that
  centers or fits each drawing/cell independently destroys the intended `(0,0)`
  registration.
- The splitter coordinate math passed reconstruction validation: the four
  current files reproduce each master with zero XOR area, and the saved project
  files match the validated build byte-for-byte. The failure is therefore most
  consistent with import placement/centering, not the clipping or translation
  calculation.
- Before applying the earlier 10-20 um / 75-100 um fine corrections, lock the
  laser import to the DXF/GDS origin and disable per-file centering/fit. If the
  controller cannot preserve origin, add an identical non-exposed registration
  frame on a disabled layer to every output file.

### Software resolution

- Both four-window splitters add four 50 um corner anchors on the separate
  `REGISTRATION_DO_NOT_EXPOSE` layer, sized to half the profile's field so the
  asymmetric alignment marker cannot change automatic centering. The legacy
  old-jig profile has a 60 mm field and so anchors at `+/-30 mm`; the current
  pin-grid production profile has a 52 mm field and anchors at `+/-26 mm`. Each
  is exact in every tile and orientation.
- Cutting geometry remains exclusively on layer `0`. The laser must assign no
  marking / zero power to `REGISTRATION_DO_NOT_EXPOSE`; never expose that layer.
- The corrected old-jig production set is stored separately as
  `output/DXFs/080726_FourPosDicer_OriginLocked`; the failed-run files were left
  unchanged for traceability.
- KLayout reopened all eight corrected files. Layer-0 horizontal and vertical
  reconstructions each had zero XOR area, and every registration-layer bounding
  box was exactly `+/-30.000 mm`.

## Single sliding nest concept

Goal: move the seated wafer between the two Y positions without lifting or
prying it out of the nest.

- Replace the two fixed, overlapping wafer nests with one nest on a Y carriage.
- Carriage travel: exactly `50.000 mm` between front and rear indexed positions.
- Retain the existing outer-frame X indexing: the full jig still shifts `50 mm`
  left/right against the table side stops.
- Use two parallel Y guides so the carriage cannot rotate.
- Define both Y positions with hard stops or dowel-pin index holes rather than
  relying on printed friction alone.
- Preload the carriage against one guide and against the selected hard stop so
  every position approaches the same datums.
- Lock the carriage downward at each position to preserve wafer focus and
  prevent rocking. A spring plunger, removable index pin, or small toggle clamp
  is preferable to a loose printed detent.
- Add an accessible handle outside the laser field so the wafer can be shifted
  while remaining fully seated against its primary- and secondary-flat datums.
- Keep the track below the wafer support plane and keep rails/hardware outside
  the exposed wafer area where practical.

For a PLA prototype, a broad keyed slide can demonstrate the motion, but the
final repeatable version should use hard mechanical datums (for example dowel
pins or shoulder bolts) because sliding PLA clearance and wear are unlikely to
hold tens-of-microns repeatability by themselves.

## Eight-pin grid-indexed nest

The sliding concept was superseded by a lift-and-index fixture using the table's
1 inch (`25.400 mm`) threaded-hole grid.

### Table and coordinate dimensions

- Grid pitch: `25.400 mm` (`1.000 inch`) center to center.
- First hole-center inset from the front and side edges: `12.700 mm`
  (`0.500 inch`). Table width is not used as a fixture datum.
- Measured hole/thread major opening: `6.000 mm`.
- Measured threaded minor diameter: `4.870 mm`.
- Directly measured laser-zero center from table left/front:
  `X=96.190 mm`, `Y=109.350 mm`.
- Two-grid-space indexing move in either axis: `50.800 mm`.
- Four-pass exposure centers on the wafer: `X,Y=+/-25.400 mm`.
- Nest center relative to the shared pin-pattern center:
  `X=+7.290 mm`, `Y=-4.950 mm`.

### Pin dimensions and tolerance

- Total pins: `8`, printed downward as an integral part of the platform.
- Nominal pin diameter: `4.700 mm` for all eight pins.
- Nominal diametral clearance against the measured 4.870 mm thread minor:
  `0.170 mm`; nominal radial clearance: `0.085 mm`.
- Total pin length below the platform: `5.000 mm`, of which the last
  `1.000 mm` is the entry taper, leaving `4.000 mm` straight.
- Entry taper height: `1.000 mm`, included in the 5.000 mm above.
- Tip diameter: `4.000 mm`, increasing to `4.700 mm` over the taper.
- Inner four pins: corners of a `50.800 x 50.800 mm` square (`2 x 2` spaces).
- Outer four pins: corners of a `101.600 x 101.600 mm` square (`4 x 4` spaces).
- Both pin squares are concentric. The outer set provides rotational leverage;
  the inner set supports the center and adds redundancy.
- PLA prototype dimensions are nominal. Verify a pin coupon before printing the
  full jig because extrusion width, shrinkage, and thread crests affect fit.

### Platform and nest dimensions

- Platform overall size: `128.000 x 128.000 mm`.
- Platform/wafer-support base thickness: `2.000 mm`.
- Continuous outside reinforcement bar: `4.000 mm` wide x `4.000 mm` high
  above the platform; total platform-plus-bar height is `6.000 mm`.
- Wafer diameter: `100.000 mm`.
- Primary-flat nominal length: `32.500 mm`; faces front (`-Y`).
- Secondary-flat nominal length: `18.000 mm`; faces left (`-X`) and sets
  rotation.
- Raised sidewall height above the 2 mm platform: `1.500 mm`.
- Sidewall thickness: `3.000 mm`.
- Radial wafer-pocket clearance: `0.500 mm` per side (`1.000 mm` diametral).
- Primary-flat clearance: `0.500 mm`.
- Secondary-flat rotational-datum clearance: `0.100 mm`.
- Primary-flat pickup opening: `20.000 mm` wide with a 45 degree bevel.
- The outside reinforcement bar has a centered tweezer notch aligned to the
  primary-flat opening: `20.000 mm` wide at platform level and `28.400 mm` at
  the top, producing 45 degree side slopes through the 4 mm bar height.
- Pickup opening removes only the raised wall; the 2 mm support platform remains
  continuous and uncut.
- Both pin-grid jigs carry three engravings cut `0.500 mm` into the platform
  floor, in the same three places on each plate.
- Top-left is the station map. The four-position plate reads
  `2x2 SINGULATION ALIGNER` then one hole per station in rear-first order,
  `11 C4 R3`, `12 C6 R3`, `21 C4 R1`, `22 C6 R1`, so the engraved rows match the
  plate's orientation on the table. The center-field plate reads
  `CENTER FIELD ALIGNER` then `C5 R2`.
- Front-left reads `C0=LEFT R0=FRONT`, preserving the counting convention.
- Front-right reads `ALIGNMENT PIN`, naming the outer pin nearest that corner.
  That pin is the one every engraved coordinate refers to. The eight-pin
  pattern is rigid, so seating it fixes the other seven; it always sits two grid
  spaces right of and two forward of the pin-pattern center.
- The two long lines used to sit at the bottom of the top-left block, where the
  wafer-pocket wall curves in and clipped them. Splitting them to the front edge
  keeps roughly `5 mm` of clearance to the pocket wall.

### Four-position pin map

Grid columns are numbered from the left and rows from the front, starting at
zero. Labels are jig stations per the coordinate convention above.

| Folder | Jig station | Outer pin columns/rows | Inner pin columns/rows | Exposed area |
| --- | --- | --- | --- | --- |
| `DXF11` | top-left | columns `0,4`; rows `3,7` | columns `1,3`; rows `4,6` | bottom-right |
| `DXF12` | top-right | columns `2,6`; rows `3,7` | columns `3,5`; rows `4,6` | bottom-left |
| `DXF21` | bottom-left | columns `0,4`; rows `1,5` | columns `1,3`; rows `2,4` | top-right |
| `DXF22` | bottom-right | columns `2,6`; rows `1,5` | columns `3,5`; rows `2,4` | top-left |

### Center-field pin map

The same physical geometry centers the wafer at laser zero when the common pin
pattern center is at grid column `3`, row `4`:

- Outer pins: columns `1,5`; rows `2,6`. Engraved front-right pin: `C5 R2`.
- Inner pins: columns `2,4`; rows `3,5`.
- Pin-pattern center: `(88.900,114.300) mm` from the table left/front.
- Wafer center after the `(+7.290,-4.950) mm` nest offset:
  `(96.190,109.350) mm`, exactly the directly measured laser-zero center.

### Fusion packages

- Four-position workflow: `fusion/FusionPinGridJig`.
- Center-field workflow: `fusion/FusionPinGridCenterJig`.

## Pin-grid DXF/GDS production profile

- Qualified exposure/file bounds: `52.000 x 52.000 mm`.
- Four field centers on the wafer: `X,Y=+/-25.400 mm`.
- Neighboring-center spacing: `50.800 mm`, matching the two-hole grid move.
- Total stitch overlap: `1.200 mm`; each job extends `0.600 mm` across the
  nominal X=0 and Y=0 seam.
- Margin from the exposure boundary to each edge of the maximum usable
  `78.485 mm` optical field: `13.2425 mm`.
- Registration anchors: four 50 um corner polygons on
  `REGISTRATION_DO_NOT_EXPOSE`, fixing all content bounds at
  `(-26,-26) to (+26,+26) mm`. Never expose this layer.
- Cutting geometry remains on layer `0`, with a maximum width of `50 um`.
- Master-generator edge bead is controlled by the single top-level
  `EDGE_BEAD_MM` variable in `generate_100mm_10x30mm_masters.py`; units are
  millimeters. Current production value: `2.000 mm`.
- Validated production output:
  `output/DXFs/080726_FourPosDicer_PinGrid52mm`. Relabeled to jig-station names
  on 2026-08-08 and revalidated: layer-0 reconstruction XOR area is zero against
  both masters, every registration bounding box is exactly `+/-26.000 mm`, and
  all eight DXFs are byte-identical to the files they replaced.
- One production splitter only: `python/split_klayout_four_windows.py`. The
  byte-identical `split_klayout_four_windows_pin_grid.py` duplicate was removed
  on 2026-08-08.
