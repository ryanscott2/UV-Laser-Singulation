# Operating procedure — 100 mm wafer four-pass dicing

Slice the wafer GDS into four laser jobs, seat the wafer, and scribe each quadrant
on the UV galvo. The jig indexes on the table's 1 inch hole grid; the laser stays
fixed and field-centered, so indexing the jig moves the wafer under the beam.

## 1. Slice the GDS (slicer UI)

1. Launch the UI: `python tools/slicer_app.py`.
2. **Source:** pick the wafer GDS. All cutlines are assumed on one layer — select
   that layer from the list.
3. **Output:** type a folder name; it lands under `output/<name>`.
4. **Mode:** Four windows. **Cut width:** 50 µm. Set a **wafer edge bead** (mm)
   only if the GDS runs cuts to the wafer edge (the standard masters already inset
   2 mm).
5. **Run.** The UI bakes the current calibration offset automatically (confirm it
   matches the jig in use — see `CALIBRATION_AND_SLIDING_NEST_NOTES.md`; the
   tightened-nest recal is pending) and writes four field-centered jobs:
   `P1_jig_top_left.dxf`, `P2_jig_top_right.dxf`, `P3_jig_bottom_right.dxf`,
   `P4_jig_bottom_left.dxf`, plus a manifest and log.

Each station DXF holds both horizontal and vertical cuts. To get them as
ready-split files, use `python tools/build_pin_grid_set.py --combined <gds>
--cut-layer <layer>` instead of the UI.

## 2. Seat and tape the wafer

1. Set the jig on the table with all four dowels in the grid holes for the first
   position (P1 — see the table below).
2. Drop the wafer in and push it **forward against the primary flat** (front datum,
   sets Y + rotation) and **left against the X-datum pin** at the upper-left of the
   nest (sets X). The primary flat plus the pin fully locate it; the secondary flat
   is not used, so any wafer flat type seats the same way.
3. **Kapton-tape the wafer down** at the perimeter through the two tape gaps
   (180° apart). Tape **on top only, never underneath** — tape under the wafer
   rocks it and shifts focus. Keep tape clear of the scanned area (polyimide
   absorbs UV).

## 3. Scribe each quadrant (WinLase)

For each station, import its DXF and set:

- **Fill:** parallel (hatch), **0.01 mm** spacing — **0°** for horizontal cuts,
  **90°** for vertical cuts.
- **Mark speed:** 400 mm/s. **Passes:** 1 (mark once). **Loop the job 175×.**
- **Z / table height:** **0.463 in + jig base thickness (12.500 mm)** ≈ 24.26 mm.
- **Auto-centering OFF** — the DXF origin is the field center.

Run **P1 → P2 → P3 → P4 in order.** Do both the horizontal (0°) and vertical (90°)
fills at each station before moving. Between stations, lift the jig and re-seat all
four dowels at the next grid position; the taped wafer rides with it — do not
disturb the tape.

| Pass | Front-left (alignment) pin hole | Table position (from left, front) | Exposes |
| --- | --- | --- | --- |
| P1 (top-left)     | C1 R4 | (12.7, 88.9) mm | wafer bottom-right |
| P2 (top-right)    | C3 R4 | (63.5, 88.9) mm | wafer bottom-left |
| P3 (bottom-right) | C3 R2 | (63.5, 38.1) mm | wafer top-left |
| P4 (bottom-left)  | C1 R2 | (12.7, 38.1) mm | wafer top-right |

Columns count from the table left, rows from the front; hole 1 is 12.7 mm in, then
25.4 mm pitch. The front-left pin is the reference — seating it puts the other three
dowels in their matching holes of the 4-space square. Adjacent stations are 2 grid
spaces (50.8 mm) apart. (P0 = C2 R3 centers the whole wafer in one field.)
