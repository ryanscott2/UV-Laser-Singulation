# UV Laser Singulation calibration and sliding-nest notes

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

- The four-window splitter adds four 50 um corner anchors on the separate
  `REGISTRATION_DO_NOT_EXPOSE` layer, sized to half the profile's field so the
  asymmetric alignment marker cannot change automatic centering. They are exact
  in every tile and orientation. When this was written there were two splitters,
  the legacy old-jig profile anchoring at `+/-30 mm` for its 60 mm field and the
  pin-grid profile at `+/-26 mm` for 52 mm. The old-jig profile has since been
  removed and the field widened, so the one remaining splitter anchors at
  `+/-27 mm` for a 54 mm field.
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

## Four-pin grid-indexed nest

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

- Total pins: `4`, printed downward as an integral part of the platform. The
  inner 2 x 2 set was removed on 2026-08-08: the outer square alone fixes position
  and rotation, and four pins are far easier to line up when seating the plate.
- Nominal pin diameter: `4.650 mm` for all four pins, reduced from `4.700 mm`
  on 2026-08-08 after the tighter fit needed sanding to seat.
- Nominal diametral clearance against the measured 4.870 mm thread minor:
  `0.220 mm`; nominal radial clearance: `0.110 mm`.
- That clearance is spent against the `0.200 mm` stitch overlap. Plate shift is
  the radial clearance itself; plate rotation is that clearance over the
  `71.842 mm` pin-circle radius, which is `0.088 deg` and a further `0.041 mm`
  at the 27 mm field edge. Total `0.151 mm`, inside the overlap. A `4.600 mm`
  pin would reach `0.186 mm` and a `4.465 mm` pin `0.279 mm`, which exceeds it:
  do not open the pins further without widening the overlap to match.
- Total pin length below the platform: `5.000 mm`, of which the last
  `1.000 mm` is the entry taper, leaving `4.000 mm` straight.
- Entry taper height: `1.000 mm`, included in the 5.000 mm above.
- Tip diameter: `4.000 mm`, increasing to `4.650 mm` over the taper.
- The four pins are the corners of a `101.600 x 101.600 mm` square
  (`4 x 4` spaces), which gives the most rotational leverage available on the grid.
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
- Secondary-flat rotational-datum clearance: `0.300 mm`, opened from `0.100 mm`
  on 2026-08-08. A standard secondary flat is `18.000 +/- 2.000 mm`, and a
  *short* flat cuts a shallower chord, so it sits further out: at `16.000 mm`
  the flat is `0.173 mm` proud of nominal. The old `0.100 mm` therefore
  interfered by `0.073 mm` on a spec-compliant wafer before any print error,
  which is what forced the sanding. `0.300 mm` clears the whole band.
- Primary-flat pickup opening: `15.000 mm` wide with a 45 degree bevel.
- Rear tape gap: `15.000 mm` wide with the same 45 degree bevel, on the plain
  arc directly opposite the primary flat. The pair gives a Kapton tab a run
  from platform to wafer at both ends without bridging the 1.5 mm lip. Like
  the pickup opening it cuts the raised wall only; the 2 mm platform stays
  continuous beneath the wafer.
- Side pickup tabs: one centered on the left and right edges,
  `10.000 mm` out by `24.000 mm` long, spanning z `2.000` to `6.000 mm`. Starting
  them at the top of the 2 mm platform leaves a `2.000 mm` undercut to hook a
  fingernail or tweezer tip under, so the plate lifts straight off its pins
  instead of being pried against the wafer or the nest wall. Overall plate width
  including both tabs is `148.000 mm`.
- The outside reinforcement bar has two centered notches, one aligned to the
  primary-flat opening and one to the rear tape gap, so a finger or tab can
  reach the wafer edge from outside the plate at either end. Each is
  `15.000 mm` wide at platform level and `23.400 mm` at
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
  That pin is the one every engraved coordinate refers to. The four-pin
  pattern is rigid, so seating it fixes the other three; it always sits two grid
  spaces right of and two forward of the pin-pattern center.
- The two long lines used to sit at the bottom of the top-left block, where the
  wafer-pocket wall curves in and clipped them. Splitting them to the front edge
  keeps roughly `5 mm` of clearance to the pocket wall.

### Wafer retention

The pocket locates the wafer; it does not hold it. Clearance cannot do both jobs
at once, and trying to make it do both is what produced the sanding:

- Tight enough to control rotation means tight enough to interfere with a
  spec-compliant wafer. Even the old `0.100 mm` secondary datum only limited
  rotation to `+/-0.637 deg`, which is `0.300 mm` at the 27 mm field edge, still
  larger than the `0.200 mm` stitch overlap. It was too tight to seat and too
  loose to locate.
- The `0.500 mm` radial clearance is a free-play envelope `2.5x` the stitch
  overlap. It only matters if the wafer moves relative to the nest, but nothing
  in the plate prevents that across the four re-seatings.

**Decision (2026-08-08): tape the wafer, do not print a spring.** Printed
cantilever preload fingers were considered and rejected. The nest wall is only
`1.500 mm` tall and `3.000 mm` thick, so a finger extruded from the platform is
fused to the floor along its length and behaves as a rib, not a beam; freeing it
would mean cutting a relief slot down through the 2 mm platform. Useful spring
force needs roughly a `1.400 mm` beam behind a `0.700 mm` slot, and that slot is
under two extrusion widths on a 0.4 mm nozzle, so it tends to fuse closed or
print ragged. PLA also creeps under sustained deflection, so the printed preload
decays.

Kapton tabs over the top, bridging nest wall to wafer at the extreme perimeter,
remove the movement entirely rather than reducing it, and cost nothing to undo.
Tape on top, never underneath: `0.060` to `0.090 mm` of tape below a `0.525 mm`
wafer rocks it and moves focus. Polyimide absorbs UV strongly, so keep the tabs
clear of the scanned area.

### Four-position pin map

Grid columns are numbered from the left and rows from the front, starting at
zero. Labels are jig stations per the coordinate convention above.

| Folder | Jig station | Pin columns/rows | Engraved hole | Exposed area |
| --- | --- | --- | --- | --- |
| `DXF11` | top-left | columns `0,4`; rows `3,7` | `C4 R3` | bottom-right |
| `DXF12` | top-right | columns `2,6`; rows `3,7` | `C6 R3` | bottom-left |
| `DXF21` | bottom-left | columns `0,4`; rows `1,5` | `C4 R1` | top-right |
| `DXF22` | bottom-right | columns `2,6`; rows `1,5` | `C6 R1` | top-left |

### Center-field pin map

The same physical geometry centers the wafer at laser zero when the common pin
pattern center is at grid column `3`, row `4`:

- Pins: columns `1,5`; rows `2,6`. Engraved front-right pin: `C5 R2`.
- Pin-pattern center: `(88.900,114.300) mm` from the table left/front.
- Wafer center after the `(+7.290,-4.950) mm` nest offset:
  `(96.190,109.350) mm`, exactly the directly measured laser-zero center.

### Fusion packages

- Four-position workflow: `fusion/FusionPinGridJig`.
- Center-field workflow: `fusion/FusionPinGridCenterJig`.

## Pin-grid DXF/GDS production profile

Revised 2026-08-08. The window a job occupies is now derived from the pitch and the
stitch alone, so the declared field is free to be larger than the window.

- Declared exposure/file bounds: `54.000 x 54.000 mm`.
- Window occupied per job: `51.000 mm`, its own half of the `50.800 mm` pitch plus
  the stitch, centred in the 54 mm field with `1.500 mm` clear on every side.
- Four field centers on the wafer: `X,Y=+/-25.400 mm`.
- Neighboring-center spacing: `50.800 mm`, matching the two-hole grid move.
- Total stitch overlap: `0.200 mm`; each job extends `0.100 mm` across the nominal
  X=0 and Y=0 seam, which covers the 75-100 um mismatch measured above. Raising it
  past `3.200 mm` would push a window outside the declared field, and the splitter
  refuses that.
- Margin from the declared window to each edge of the maximum usable `78.485 mm`
  optical field: `12.2425 mm`.
- Registration anchors: four 50 um corner polygons on
  `REGISTRATION_DO_NOT_EXPOSE`, fixing all content bounds at
  `(-27,-27) to (+27,+27) mm`. Every DXF also declares `$EXTMIN`/`$EXTMAX` at the
  same bounds. Never expose the anchor layer.
- Double-exposed area per wafer: `0.4925 mm2` of `49.1333 mm2`, about `1.00%`. Of
  that, `0.0700 mm2` is the 28 grid crossings where the horizontal and vertical
  files meet and `0.4225 mm2` is the deliberate seam stitch. Acceptable because the
  wafer is scored partway through rather than cut.
- `CLIP_MODE` now matters: at the old 52 mm field `partition` and `full_window`
  produced identical boxes, but with a 54 mm field `full_window` overlaps
  neighbours by `3.200 mm` and exposes that whole band twice.
- Cutting geometry remains on layer `0`, with a maximum width of `50 um`.
- Master-generator edge bead is controlled by the single top-level
  `EDGE_BEAD_MM` variable in `generate_100mm_10x30mm_masters.py`; units are
  millimeters. Current production value: `2.000 mm`.
- Validated production output:
  `output/DXFs/080826_FourPosDicer_PinGrid54mm`. The 52 mm set
  `080726_FourPosDicer_PinGrid52mm` is superseded and kept only for traceability. Relabeled to jig-station names
  on 2026-08-08 and revalidated: layer-0 reconstruction XOR area is zero against
  both masters, every registration bounding box is exactly `+/-26.000 mm`, and
  all eight DXFs are byte-identical to the files they replaced.
- One production splitter only: `python/split_klayout_four_windows.py`. The
  byte-identical `split_klayout_four_windows_pin_grid.py` duplicate was removed
  on 2026-08-08.
