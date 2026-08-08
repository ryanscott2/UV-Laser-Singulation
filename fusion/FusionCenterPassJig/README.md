# Fusion center-pass wafer jig

This Fusion script creates a single-position jig that places the center of a
100 mm wafer at the directly measured location of a cross commanded at
`(0, 0)`. The measured near edges were for a 78.484 mm square centered inside
the 78.485 mm usable field and are retained as an independent reference:

- Measured field left edge: `60.930 mm` from the table-left datum
- Measured field front edge: `68.430 mm` from the table-front datum
- Edge-derived field center (reference only): X `100.172 mm`, Y `107.672 mm`
- Authoritative zero-cross center: X `96.190 mm`, Y `109.350 mm`
- Direct-cross minus edge-derived discrepancy: X `-3.982 mm`, Y `+1.678 mm`

The wafer-retaining lip is `1.500 mm` tall above the support base. The primary
flat faces front and has a centered 20 mm pickup opening. The left
secondary flat is the rotational datum. Four constant-width 8 mm ribs fan from
the reinforced front corners and use 45 degree thickness ramps at the nest.
The 2 mm holder base continues from the front table bar to the horizontal nest
centerline at Y = `109.350 mm` as an exactly 100 mm wide structural sheet.
The 20 mm pickup opening interrupts the raised front reinforcement and the
primary-flat nest wall. Its front-bar sides open at 45 degrees from 20 mm at
the base to 36.4 mm at the top. The 2 mm wafer-support floor remains continuous
and uncut.

The inside span between the left and right table datum bars is exactly
`200.000 mm`, matching the stated table width with no designed side clearance.
Edit `JIG_X_CORRECTION` or `JIG_Y_CORRECTION` near the top of
`FusionCenterPassJig.py` if the prototype calibration shows a systematic error.

The wafer pocket currently has `0.500 mm` radial clearance per side
(`1.000 mm` diametral), `0.500 mm` clearance at the front primary flat, and
`0.100 mm` designed clearance at the left secondary-flat rotational datum.

## Run

1. In Fusion, press **Shift+S**.
2. On the Scripts tab, click **+** and select this folder.
3. Select `FusionCenterPassJig` and click **Run**.

The script creates an editable design and exports `center_pass_wafer_jig.f3d`
and `center_pass_wafer_jig.step` beside itself. It also exports a high-quality
binary `center_pass_wafer_jig.stl` automatically to the shared
`fusion/print-files` folder.
