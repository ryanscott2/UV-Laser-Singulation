# Fusion four-dowel wafer aligner (pin-grid jig)

This Fusion script (`FusionPinGridJig.py`, folder `AlignerPLA`) builds one compact
100 mm wafer nest that locates a wafer by its **primary flat plus one hard arc pin**
and indexes it on a laser table's 1 inch (25.4 mm) tapped-hole grid. The laser is
fixed and field-centered; moving the jig moves the wafer under the beam, and the
four grid positions expose the four wafer quadrants.

Four separate 3/16 in ground **steel** dowels are inserted into vertical through-bores
after printing and retained with epoxy (slip fit, not interference). There are no
printed pins, no perimeter bar, no pickup tabs, and no text except a small `RYAN
SCOTT` maker's mark.

## Shape

The base is not a rectangular plate. It is a **"spider"** built in `build_model`:

- a **hub disc** over the nest (`hub_radius = WAFER_DIAMETER/2 + SIDEWALL_THICKNESS +
  PLATFORM_NEST_GAP = 54 mm`, i.e. 108 mm dia). The hub is sized as the minimum that
  fully supports the nest -- the wafer floor and the 3 mm wall reach 53 mm from the
  nest center -- so the plate cannot be scooped inside that.
- four **necked arms** (`ARM_WIDTH = 15 mm`) running out to the corner dowel bosses,
- four **boss discs** (`BOSS_DIAMETER = 20 mm`, 10 mm radius) around the dowel bores,
- all unioned and then **filleted** (`FILLET_RADIUS = 2.5 mm`) on every outer corner
  where the arms meet the hub and bosses, so there are no sharp outer edges.

The rectangular corners of the old plate are gone; this removes bulk while keeping
`>=15 mm` of material in every arm.

## Fixed geometry

- Grid pitch: `25.400 mm`; indexing move: two spaces = `50.800 mm`.
- Dowel pattern: four corners of a `101.600 x 101.600 mm` square (`4 x 4` spaces).
- Locating dowels: four 3/16 in (`4.7625 mm`) ground **steel** dowels, slip-fit into
  the bores with epoxy; each protrudes `5.000 mm` below the base into a table hole.
- Dowel bore: `DOWEL_HOLE_DIAMETER = 4.850 mm` (PLA), straight through the full
  `12.5 mm` base. Bosses give `~7.6 mm` of material around each bore.
- Base: one solid slab, `BASE_THICKNESS = 12.500 mm` (warp resistance + a solid bore
  wall).
- X-datum pin: an `8 mm` post at the **9:30** arc position (`165 deg` CCW from `+X`,
  upper-left), built as a **truncated half-disc** -- only the inner half facing the
  wafer, so its round face contacts the nominal wafer OD and its flat back sits at
  the hub edge with no overhang. Extruded `SIDEWALL_HEIGHT` tall.
- Nest wall (sidewall): `SIDEWALL_HEIGHT = 2.000 mm` (retains a short stack of
  wafers), `SIDEWALL_THICKNESS = 3.000 mm`.
- Pickup opening: `15.000 mm` at the primary flat, 45-degree bevel, cutting the
  raised wall only. Rear tape gap: `15.000 mm` opposite it, same bevel.
- Maker's mark: `RYAN SCOTT` engraved `0.5 mm` deep, running along the top-left arm
  (fit-on-path, so it follows the strut).

## Wafer fit

Located by the **primary flat** plus **one hard arc pin** -- not the secondary flat
-- so one nest fits every SEMI flat type (100 p/n, 111 p/n) and a wafer flipped for
back-side work. Press the wafer **forward onto the primary flat** and **left onto the
pin** by hand.

- Wafer: standard 100 mm, primary flat forward.
- Primary-flat clearance: `0.175 mm` -- front datum, sets **Y + rotation**.
- X pin at `9:30` -- sets **X**, referencing the wafer OD. Repeatability therefore
  tracks OD consistency (tens of um within a batch) rather than a flat.
- Radial (arc) clearance: `0.600 mm` -- the rest of the wall is a loose retainer,
  opened so the pin (not the wall) takes first contact.

Note: this primary-flat + pin datum **invalidates the old `NEST_CALIBRATION`** (it
replaced the earlier two-flat fit); a one-time manual recalibration is required with
this print. The subsequent reshape, pin resize, and arc change are calibration-
neutral. See `CALIBRATION_AND_SLIDING_NEST_NOTES.md`.

## Indexing and calibration

The nest is offset from the dowel-pattern center by `NEST_OFFSET_FROM_PIN_CENTER`
(`X = +7.290`, `Y = -4.950 mm`) plus a baked `NEST_CALIBRATION` (`X = +3.187`,
`Y = -1.346 mm`), for an effective nest center of `X = +10.477`, `Y = -6.296 mm`.
With the laser-zero at `(96.190, 109.350) mm` this places the four exposure centers
at `+/-25.400 mm` on the wafer. Because the offset is baked into the jig, reset
`GLOBAL_X/Y_OFFSET_UM` to `0` in `slicing/split_klayout.py` once a jig from this is in
use, or the DXF and jig will double-correct. For the station-to-quadrant mapping and
the exposure steps, see `OPERATING_PROCEDURE.md`.

## Run

1. In Fusion, press **Shift+S**.
2. On the Scripts tab, add this folder (`AlignerPLA`) and run `FusionPinGridJig`.

It creates an editable parametric design and exports `pin_grid_wafer_jig.f3d` and
`.step` beside itself, plus a high-refinement binary `.stl` to `fusion/print-files`.

## Printing

- Print **flat, nest side up**. The bottom face is flat -- no supports, no downward
  pins to bridge.
- Insert the four `4.7625 mm` steel dowels into the bores with epoxy, `5.000 mm`
  proud below the base. A **true slip fit** (dowel drops in, epoxy holds) matters:
  an interference fit can crack a printed bore.
- **Resin choice (SLA):** avoid brittle glass-filled resins -- Rigid 10K
  (~1.7% elongation) shattered on dowel insertion. Use a tougher engineering resin:
  **Grey Pro** (`2.6 GPa`, `13%` elongation -- stiff and far less brittle) or
  **Tough 2000** (ABS-like, `48%` elongation). Standard grey is an improvement over
  Rigid but still the most crack-prone of the acceptable options.
- Verify dowel fit and flatness on the table before seating a real wafer.

## SLA variant

`fusion/AlignerSLA/FusionPinGridJigSLA.py` builds the same jig for resin. It is
identical to the PLA script except:

- `DOWEL_HOLE_DIAMETER = 4.950 mm` (vs `4.850`) -- `0.10 mm` larger for a clear resin
  slip fit. This does **not** change the footprint (the `20 mm` bosses are fixed), so
  the SLA and PLA shapes are identical.
- A `SCALE_FACTOR` constant (default `1.000`) applying a uniform scale about the
  origin to null resin print-shrink; set `SCALE_FACTOR = nominal / measured` from the
  `101.600 mm` dowel-hole pitch on a test print if needed.
- Export filenames `pin_grid_wafer_jig_sla.f3d` / `.step` / `.stl`, and its run
  message reports the scale.
