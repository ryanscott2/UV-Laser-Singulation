# UV Laser Singulation calibration and sliding-nest notes

Last updated: 2026-08-08

## Coordinate convention

P1-P4 name the jig station, numbered clockwise from the table's top-left (P1
top-left, P2 top-right, P3 bottom-right, P4 bottom-left).

Indexing the jig moves the wafer, not the laser, so both axes invert and each
station exposes the diagonally opposite wafer quadrant.

| Label | Jig station | Exposed wafer area |
| --- | --- | --- |
| `P1` | top-left | bottom-right |
| `P2` | top-right | bottom-left |
| `P3` | bottom-right | top-left |
| `P4` | bottom-left | top-right |

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
- The splitter emits only clipped geometry, so every DXF/GDS job has a
  different content bounding box. Any laser import option that centers or fits
  each drawing/cell independently destroys the intended `(0,0)` registration.
- The splitter coordinate math passed reconstruction validation: the four
  current files reproduce each master with zero XOR area, and the saved project
  files match the validated build byte-for-byte. The failure is therefore most
  consistent with import placement/centering, not the clipping or translation
  calculation.
- Before applying the earlier 10-20 um / 75-100 um fine corrections, run the
  laser (WinLase Pro) with auto-centering off so each job is placed at its true
  coordinates and the DXF origin lands on the field center. The splitter already
  writes every tile with its field center at the origin, so this reproduces the
  wafer exactly.

### Software resolution

- The fix is true-coordinate placement. The four-window splitter writes every
  tile with its field center at the DXF origin, and the laser (WinLase Pro) is
  run with auto-centering off so it places each job at its true coordinates and
  the DXF origin lands on the field center. This reproduces the wafer exactly and
  was confirmed on the machine with a placement probe.
- When this was written there were two splitters, the legacy old-jig profile for
  its 60 mm field and the pin-grid profile for 52 mm. The old-jig profile has
  since been removed and the field widened, so the one remaining splitter targets
  a 54 mm field.
- Cutting geometry remains exclusively on layer `0`.
- The corrected old-jig production set is stored separately as
  `output/DXFs/080726_FourPosDicer_OriginLocked`; the failed-run files were left
  unchanged for traceability.
- KLayout reopened all eight corrected files. Layer-0 horizontal and vertical
  reconstructions each had zero XOR area.

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
- Pickup opening removes only the raised wall; the 3 mm support platform remains
  continuous and uncut.
- The aligner plate carries four engravings raised `0.500 mm` above the platform
  floor (additive prints cleaner than cutting them in).
- Top-left, left-aligned to the outer wall, is the title and centering position:
  `ALIGNER` then `P0 C2 R3` (seat the wafer here and the alignment pin lands in the
  field center, so the whole wafer is addressable in one shot).
- Top-right, right-aligned to the outer wall, is the station map, one hole per
  position: `P1 C1 R4`, `P2 C3 R4`, `P3 C3 R2`, `P4 C1 R2`.
- Bottom-left reads `ALIGNMENT PIN`, naming the outer pin nearest that corner. That
  pin is the one every engraved coordinate refers to. The four-pin pattern is rigid,
  so seating it fixes the other three; it always sits two grid spaces left of and
  two forward of the pin-pattern center.
- Bottom-right is the origin key: two stacked rows `C1=LEFT` / `R1=FRONT`,
  right-aligned to the outer wall.

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
one. Labels are jig stations per the coordinate convention above.

| Folder | Jig station | Pin columns/rows | Engraved hole | Exposed area |
| --- | --- | --- | --- | --- |
| `P1` | top-left | columns `1,5`; rows `4,8` | `C1 R4` | bottom-right |
| `P2` | top-right | columns `3,7`; rows `4,8` | `C3 R4` | bottom-left |
| `P3` | bottom-right | columns `3,7`; rows `2,6` | `C3 R2` | top-left |
| `P4` | bottom-left | columns `1,5`; rows `2,6` | `C1 R2` | top-right |

### Center (P0) pin map

The same four-position plate centers the wafer at laser zero when its four pins are
seated at the center holes (position `P0`), whose pattern center is grid column `4`,
row `5`:

- Pins: columns `2,6`; rows `3,7`. Engraved front-left pin: `C2 R3`, at
  `(38.100,63.500) mm` from the table left/front.
- Pin-pattern center: `(88.900,114.300) mm` from the table left/front.
- Wafer center after the `(+7.290,-4.950) mm` nest offset:
  `(96.190,109.350) mm`, exactly the directly measured laser-zero center.

### Fusion packages

- Four-position workflow (also centers via P0): `fusion/FusionPinGridJig`. The
  separate `FusionPinGridCenterJig` was retired 2026-08-11 once P0 covered centering.

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
- Margin from the declared 54 mm window to each edge of the `60 mm` usable field:
  `3 mm`.
- Placement is by true coordinates: each tile is written with its field center
  at the DXF origin, so the laser (WinLase Pro) run with auto-centering off
  places every job at its true coordinates with the origin on the field center.
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
  both masters, the field-placement self-test confirms every tile's layer-0
  geometry fits within `+/-30 mm` (the usable field) of the origin with the origin
  at the field center, and all eight DXFs are byte-identical to the files they replaced.
- One production splitter only: `python/split_klayout.py`. The
  byte-identical `split_klayout_four_windows_pin_grid.py` duplicate was removed
  on 2026-08-08.

## Print v2 and global-offset calibration (2026-08-11)

Measured on the 081126 alignment test (stations P1-P4, front pins seated in the
4th row of holes, laser auto-centering off): the exposure landed **+3.017 mm in X
and -1.286 mm in Y** off the wafer flats. The left seam line read `12.20 mm` from
the minor (secondary, -X) flat against `9.183 mm` expected; the bottom seam line
read `16.00 mm` from the major (primary, -Y) flat against `17.286 mm` expected.
The usable optical field is a `60 x 60 mm` square -- the galvo's full field is
about `78.485 mm`, but it weakens toward the edges, so only the central 60 mm is
used -- so the corrected geometry (widest marks at `+/-28.5 mm`) stays well inside it.

Re-measured after applying that correction: the left line read `9.35 mm` from the
minor flat (`9.183 mm` expected, `+0.17 mm` residual) and the bottom line
`17.23 mm` from the major flat (`17.286 mm` expected, `-0.06 mm` residual) -- both
below the `0.200 mm` stitch overlap. Both residuals kept the sign of the original
error (an under-correction). Correcting the full residual (`-3186.7 / +1345.7`)
overtuned given the noise, so the difference was split with the first correction and
half applied: X by `85 um` (`-3016.7 -> -3101.7`) and Y by `30 um`
(`+1285.7 -> +1315.7`).

The same offset is corrected two ways, and only ONE may be active at a time:

- **Software (current jig):** `GLOBAL_X_OFFSET_UM = -3101.7`,
  `GLOBAL_Y_OFFSET_UM = +1315.7` in `python/split_klayout.py`, applied
  to every job after it is centered on its field. The `081126_FullDice_v3` set is
  built with these split-difference values; the earlier `081126` and
  `081126_AlignmentTest_v2` sets carry the original `-3016.7 / +1285.7` they were
  measured against.
- **Jig (print v2):** `NEST_CALIBRATION_X/Y = +3.017 / -1.286` in both
  `fusion/FusionPinGrid*Jig` scripts shifts the nest relative to the pins so a
  field-centered exposure lands correctly. This still holds the original
  `+3.017 / -1.286`; to match the split-difference software offset it becomes
  `+3.102 / -1.316` when the jig is next regenerated. **Reset the software offsets to
  0 once a print-v2 jig is in use**, or the two double-correct by ~3 mm.

Print-v2 jig changes to `FusionPinGridJig` (the redundant `FusionPinGridCenterJig`
was retired 2026-08-11; P0 centers the wafer on the four-position plate):

- Pin diameter `4.650 -> 4.700 mm` (tip `4.000 -> 4.050`); fit vs the `4.870 mm`
  hole minor tightens from `0.220` to `0.170 mm` diametral clearance.
- Nest clearances reduced 35%: radial and primary-flat `0.500 -> 0.325 mm`,
  secondary datum `0.300 -> 0.195 mm`.
- Base thickness `2.000 -> 3.000 mm` (pin length and platform follow `BASE_THICKNESS`).
- Engraving text `3.0 -> 3.5 mm` and **additive (raised)** rather than cut.
- Engraving relayout: the title `ALIGNER` and centering line `P0 C2 R3` moved to the
  **top-left** (left-aligned); the `P1-P4` station map stays **top-right**
  (right-aligned). Previously both shared one top-right block. Verify both fit in
  Fusion.

Other 2026-08-11 changes:

- Quadrant outputs renamed `DXF11/12/21/22 -> P1/P2/P3/P4`, clockwise from the
  table top-left (P1 top-left ... P4 bottom-left), and grid labels are now
  **1-indexed** (`C1`/`R1` = first hole). The engraved reference pin moved to the
  front-left of each station.
- Combining orientations into one `Combined.dxf` per station was tried and
  **removed** (it did not expose well); sets are separate `Horizontal.dxf` /
  `Vertical.dxf` per station again.
- Marker-free full dice: `python/generate_100mm_10x30mm_masters_nomarker.py` reuses
  the base 10x30 generator's geometry but omits the centered plus marker, writing
  masters to `dxf/100mm_10x30mm_Masters_NoMarker`. Full-dice test set
  `output/DXFs/081126_FullDice_v3` (10x30 mm production dice, no alignment marker)
  builds and validates clean, carrying the software offset for the current jig.
- The field-placement self-test checks the `60 mm` usable field (`+/-30 mm`), not
  the `54 mm` qualified field.
