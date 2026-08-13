# Fusion four-dowel pin-grid wafer jig

This Fusion script builds one compact 100 mm wafer nest that locates a wafer by its
two flats and indexes it on a laser table's 1 inch (25.4 mm) tapped-hole grid. The
laser is fixed and field-centered; moving the jig moves the wafer under the beam.
Four steel dowels underneath the plate drop into the table's grid holes, and the
four grid positions expose the four wafer quadrants.

The plate is a single solid 12.5 mm slab. It carries no pins itself: four separate
3/16 in ground steel dowels are inserted into through-bores after printing and
retained with epoxy. There is no perimeter reinforcement bar, no bar notches, no
printed downward pins, no tapered pin tip, and no per-station coordinate engraving.

## Fixed geometry

- Grid pitch: `25.400 mm`
- Indexing move: two grid spaces = `50.800 mm`
- Dowel pattern: four corners of a `101.600 x 101.600 mm` square (`4 x 4` spaces).
  The inner `2 x 2` set is gone; the outer square alone fixes position and rotation.
- Locating dowels: four 3/16 in (`4.7625 mm`) ground **steel** dowels, inserted
  after printing into press/slip-fit through-bores and retained with epoxy. Each
  protrudes `5.000 mm` below the base into a table hole.
- Dowel bore: `DOWEL_HOLE_DIAMETER = 4.850 mm` (PLA), straight through the full
  base (`BOSS_HEIGHT = 0`, so ~8 mm of bore wall engages the dowel and the far end
  bears in the table hole).
- Corner fill: `PIN_EDGE_FILL = 7.000 mm` of solid material radially out from every
  bore edge, via `BOSS_DIAMETER = DOWEL_HOLE_DIAMETER + 2 x PIN_EDGE_FILL =
  18.850 mm`. This footprint drives the plate corners out.
- Base: one solid slab, `BASE_THICKNESS = 12.500 mm`. Thick enough to resist warping
  and give the bore a solid wall; it is the only stiffener (no perimeter bar).
- Plate: a computed tight bounding box (not nest-centered),
  `124.702 x 120.450 x 12.500 mm`. The left, rear, and front edges are set by the
  corner fill; the right edge is set by the nest wall plus `PLATFORM_NEST_GAP =
  1.000 mm`.
- Side pickup tabs ("handles"): one centered on the left edge and one on the right,
  at the nest Y-center, `10.000 mm` out by `24.000 mm` long. Each is a
  `SIDE_TAB_HEIGHT = 4.000 mm` flange whose top is flush with the base top
  (extruded **down** from z = 12.5 to z = 8.5); the open ~8.5 mm below it is the
  lift undercut a fingernail or tweezer tip hooks into. Overall width including both
  tabs: `144.702 mm`.
- Wafer nest: located purely by the two flats. Primary flat faces table front
  (`-Y`), secondary flat faces table left (`-X`).
- Nest lip (sidewall): `SIDEWALL_HEIGHT = 2.000 mm`, tall enough to retain a short
  stack of wafers; `SIDEWALL_THICKNESS = 3.000 mm`.
- Pickup opening: `15.000 mm` at the primary flat, beveled 45 degrees, cutting the
  raised lip only (the solid base stays continuous under the wafer).
- Rear tape gap: `15.000 mm` directly opposite the primary flat (180 degrees away),
  same 45 degree bevel, also cutting the lip only.
- Engraving: exactly one, a two-line credit `DESIGNED BY:` / `RYAN SCOTT` in the
  top-left, anchored off the top-left dowel-fill inner edge. Text height `2.500 mm`,
  and it is **raised** `0.500 mm` above the top face (a join, not a cut). All earlier
  engravings (`4-POSITION ALIGNER`, per-station coordinates, `ALIGNMENT PIN`,
  `C1=LEFT R1=FRONT`) are removed.

The dowel slip-fits the table's 1/4-20 tapped hole (~`4.870 mm` crest ID, so about
`0.11 mm` diametral clearance). Print a small pin-fit coupon first to dial in the
printed bore over the `4.7625 mm` dowel, because FDM prints small holes undersize
and PLA is brittle: aim for a slip/snug fit retained with epoxy rather than a hard
press that could split the wall.

## Wafer fit

The wafer is located entirely by its two flats for repeatability. The flat datums
are tight and the arc is deliberately loose so it never contacts first.

- Wafer: standard 100 mm, primary flat forward, secondary flat left
- Radial (arc) clearance: `0.500 mm` per side -- deliberately looser than the
  `0.175 x sqrt(2) = 0.248 mm` flat-seat diagonal, so the arc never contacts before
  the wafer is home on both flats
- Primary-flat clearance: `0.175 mm`
- Secondary-flat rotational datum clearance: `0.175 mm`
- Sidewall thickness: `3.000 mm`

Note: these flats are tightened from the old v2 fit (`0.500 / 0.500 / 0.300`), which
shifts where the wafer seats and **invalidates the current `NEST_CALIBRATION`**. A
manual recalibration is required with this print; see
`CALIBRATION_AND_SLIDING_NEST_NOTES.md`.

## Indexing and calibration

The nest is offset from the dowel-pattern center by `NEST_OFFSET_FROM_PIN_CENTER`
(`X = +7.290 mm`, `Y = -4.950 mm`) plus a baked machine-offset correction
`NEST_CALIBRATION` (`X = +3.187 mm`, `Y = -1.346 mm`), for an effective nest center
of `X = +10.477 mm`, `Y = -6.296 mm` relative to the dowel pattern. Combined with the
authoritative laser-zero `(96.190, 109.350) mm`, this places the four exposure
centers at `+/-25.400 mm` on the wafer. Because the calibration is baked into the
jig, the DXFs no longer need the software offset: once a jig printed from this is in
use, reset `GLOBAL_X/Y_OFFSET_UM` to `0` in `python/split_klayout.py`, or the DXF
and the jig will double-correct.

For the station-to-quadrant mapping and the step-by-step exposure procedure, see
`OPERATING_PROCEDURE.md` rather than re-deriving it here.

## Run

1. In Fusion, press **Shift+S**.
2. On the Scripts tab, click **+** and select this folder.
3. Select `FusionPinGridJig` and click **Run**.

The script creates an editable parametric design and exports
`pin_grid_wafer_jig.f3d` and `pin_grid_wafer_jig.step` beside itself, plus a
high-refinement binary `pin_grid_wafer_jig.stl` to the shared `fusion/print-files`
folder.

## Printing

- Print the plate **flat, nest side up**. The bottom face is flat, so no supports
  are needed and there are no downward pins to bridge or blocker off.
- After printing, insert the four `4.7625 mm` steel dowels into the corner bores
  with a drop of epoxy, leaving `5.000 mm` protruding below the base. Cut each dowel
  to roughly engagement + protrusion (about `13 mm` for ~8 mm engaged and 5 mm
  proud).
- Verify dowel fit and plate flatness on the table before placing a real wafer in
  the nest.

## SLA variant

`fusion/FusionPinGridJigSLA/FusionPinGridJigSLA.py` builds the same jig for
resin printing. It is functionally identical to the PLA script except for four
things:

- `DOWEL_HOLE_DIAMETER = 4.950 mm` instead of `4.850 mm` -- `0.10 mm` larger for a
  clear resin slip fit (a standard resin cracked on a tighter bore; retention is
  still epoxy). This makes the plate marginally larger:
  `124.752 x 120.550 x 12.500 mm`.
- A `SCALE_FACTOR` constant (default `1.000`) that applies a single uniform scale
  about the origin (the dowel-pattern center) at the end of the build, to null resin
  print-shrink. Leave it at `1.000` for the first print, then set
  `SCALE_FACTOR = nominal / measured` from the `101.600 mm` dowel-hole pitch on a
  test print.
- Export filenames: `pin_grid_wafer_jig_sla.f3d` / `.step` / `.stl`.
- The run/completion message: `Four-dowel grid wafer jig (SLA) created at scale
  {SCALE_FACTOR}.`
