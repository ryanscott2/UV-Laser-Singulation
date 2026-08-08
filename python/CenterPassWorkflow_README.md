# Center-pass wafer jig and KLayout job

This package makes one centered laser-field job and a matching single-position
jig for the measured table.

## Geometry assumption

`75 mm` is treated as the **scored diameter**, not radius. A standard 100 mm
wafer has a 50 mm radius, so a 75 mm score radius cannot fit on the wafer. The
default 75.000 mm score circle leaves 1.7425 mm between the scored circle and
each edge of the 78.485 mm square usable optical field.

## Jig datums

- Table width: 200.000 mm nominal.
- Inside stop span: 200.000 mm, with no designed side clearance.
- Front edge and both side stops establish the jig position.
- The near edges of a centered 78.484 mm measurement field were X = 60.930 mm
  and Y = 68.430 mm from the table edges.
- Those edges imply the reference center `(100.172, 107.672) mm`, but the
  direct calibration cross commanded at `(0, 0)` was measured at
  `(96.190, 109.350) mm` and is authoritative for the jig.
- Primary flat faces front; secondary flat touches the left nest wall to set
  rotation.
- Base thickness: 2.000 mm.
- Nest wall height above base: 1.500 mm.
- Table lip drop: 5.000 mm.
- Four ribs are 8.000 mm wide by 8.000 mm high at the frame and taper only in
  height at 45 degrees near the nest.
- Primary-flat pickup opening: 20.000 mm with a 45 degree wall-edge bevel.

Use `FusionCenterPassJig/FusionCenterPassJig.py` in Fusion. The two calibration
settings near the top are:

```python
JIG_X_CORRECTION = 0.000
JIG_Y_CORRECTION = 0.000
```

After a low-power calibration target, enter the measured systematic placement
error there and rerun the Fusion script.

## KLayout center-pass script

Edit these values near the top of `split_klayout_center_pass.py`:

```python
INPUT_FILE = r"C:\path\to\wafer_cutlines.dxf"
GLOBAL_X_OFFSET_UM = 0.0
GLOBAL_Y_OFFSET_UM = 0.0
MAX_CUT_WIDTH_UM = 50.0
SCORE_DIAMETER_UM = 75_000.0
SCORE_SHAPE = "circle"
```

Native DXF/KLayout paths wider than `MAX_CUT_WIDTH_UM` are narrowed around
their existing centerlines before clipping. The default cap is `50 um`; thinner
paths are unchanged. Closed filled contours are polygons rather than paths and
retain their drawn dimensions. The center-pass log reports how many paths were
capped.

Positive X moves the output cut geometry right. Positive Y moves it away from
the operator in the drawing coordinate system. The supplied DXFs are read as
1 DXF unit = 1 mm. The generated DXF is also in millimeters and all entities
are written on layer `0`.

Run it from KLayout with **File > Run Script**, or headlessly:

```powershell
klayout_app.exe -zz -rx -r split_klayout_center_pass.py `
  -rd "input=C:\path\to\wafer_cutlines.dxf" `
  -rd "output_dir=C:\path\to\center_output" `
  -rd "global_x_um=0" -rd "global_y_um=0" `
  -rd "max_cut_width_um=50"
```

The output is `<input_name>_center_pass.dxf` plus a text log. The optional
runtime variables `score_diameter_um` and `score_shape` override the settings
without editing the file.

## Physical sequence

1. Seat the jig firmly against the front edge with both side stops fitted over
   the 200.000 mm table width.
2. Place the wafer on the 2 mm base with the primary flat forward and the
   secondary flat seated against the left nest datum.
3. Confirm the wafer is flat, clean, and fully seated before focusing.
4. Run a low-power alignment target first, then apply measured X/Y corrections.
5. Run the centered DXF once without moving the jig or wafer.
6. Remove the wafer with the pickup opening. Evaluate fracture behavior on a
   sacrificial wafer before relying on a scored break for finished material.

Wear eye protection and contain fragments when testing a scored break. Score
depth, crystal orientation, wafer thickness, coatings, and edge defects all
affect whether it breaks cleanly; the 75 mm diameter is a starting experiment,
not a guaranteed fracture recipe.

## Validation

Both supplied reference DXFs were processed and reopened with KLayout. The
generated geometry had zero XOR difference from the intended centered 75 mm
circular clip, and remained on layer `0`.
