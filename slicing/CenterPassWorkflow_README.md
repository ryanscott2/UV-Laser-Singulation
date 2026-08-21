# Center-pass KLayout job

This makes one centered laser-field job. The dedicated center-pass Fusion jig was
retired on 2026-08-11, and the four-pin-grid jig that replaced it was itself removed
2026-08-21. Seat the wafer in the current edge-datum jig
([`../fusion/AlignerEdgePLA`](../fusion/AlignerEdgePLA) / [`../fusion/AlignerEdgeAL`](../fusion/AlignerEdgeAL)),
whose nest is already centered on the field.

## Geometry assumption

`75 mm` is treated as the **scored diameter**, not radius. A standard 100 mm
wafer has a 50 mm radius, so a 75 mm score radius cannot fit on the wafer. The
default 75.000 mm score circle fits the galvo's 78.485 mm square max field but
exceeds the 60 mm qualified usable field, so it reaches into the weaker edge region.

## KLayout center-pass script

The center pass is `mode=center_pass` of `split_klayout.py`, so it
shares that file's `GLOBAL_X_OFFSET_UM` / `GLOBAL_Y_OFFSET_UM` with the
four-window split. Both are `0`: calibration lives in the taught stage stations and
the baked edge-jig forward shim, not in the DXF. Its center-pass settings there are:

```python
SCORE_DIAMETER_UM = 75_000.0
SCORE_SHAPE = "circle"      # `circle` or `square`
FULL_FIELD_SIZE_UM = 78_485.0
```

Native DXF/KLayout paths wider than `MAX_CUT_WIDTH_UM` are narrowed around their
existing centerlines before clipping. Closed filled contours are polygons rather
than paths and keep their drawn dimensions unless the width mode is `force`. The
supplied DXFs are read as 1 DXF unit = 1 mm; the generated DXF is also in
millimeters, on layer `0`.

Run it from the slicer UI (choose **Center pass**), from KLayout with
**File > Run Script**, or headlessly:

```powershell
klayout_app.exe -zz -rx -r split_klayout.py `
  -rd "mode=center_pass" `
  -rd "input=C:\path\to\wafer_cutlines.dxf" `
  -rd "output_dir=C:\path\to\center_output" `
  -rd "score_diameter_um=75000" -rd "score_shape=circle"
```

Or via the CLI wrapper: `python slicing/run_splitter.py --input wafer.dxf --mode
center-pass --score-diameter 75000`. The output is `<input_name>_center_pass.dxf`
plus a text log.

## Physical sequence

1. Seat the wafer in the current edge-datum jig (primary flat forward, seated against
   the front/left datums; see ../fusion/AlignerEdgePLA / ../fusion/AlignerEdgeAL).
2. Confirm the wafer is flat, clean, and fully seated before focusing.
3. Run a low-power alignment target first; placement calibration lives in the
   pin-grid jig / splitter offset, not here.
4. Run the centered DXF once without moving the jig or wafer.
5. Remove the wafer with the plate's pickup tab. Evaluate fracture behavior on a
   sacrificial wafer before relying on a scored break for finished material.

Wear eye protection and contain fragments when testing a scored break. Score
depth, crystal orientation, wafer thickness, coatings, and edge defects all
affect whether it breaks cleanly; the 75 mm diameter is a starting experiment,
not a guaranteed fracture recipe.

## Validation

Both supplied reference DXFs were processed and reopened with KLayout. The
generated geometry had zero XOR difference from the intended centered 75 mm
circular clip, and remained on layer `0`.
