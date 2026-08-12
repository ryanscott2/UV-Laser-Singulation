# Center-pass KLayout job

This makes one centered laser-field job. The dedicated center-pass Fusion jig was
retired on 2026-08-11; center the wafer with the four-position pin-grid jig at its
P0 position instead (see [`../fusion/FusionPinGridJig`](../fusion/FusionPinGridJig)).

## Geometry assumption

`75 mm` is treated as the **scored diameter**, not radius. A standard 100 mm
wafer has a 50 mm radius, so a 75 mm score radius cannot fit on the wafer. The
default 75.000 mm score circle fits the galvo's 78.485 mm square max field but
exceeds the 60 mm qualified usable field, so it reaches into the weaker edge region.

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

1. Mount the pin-grid jig and seat the wafer at its P0 (center) position: primary
   flat forward, secondary flat against the nest datum (see ../fusion/FusionPinGridJig).
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
