# Fusion single-jig wafer indexer

This Fusion script builds the wafer indexer as an editable solid and exports:

- `single_jig_wafer_indexer.f3d`
- `single_jig_wafer_indexer.step`
- `../print-files/single_jig_wafer_indexer.stl` as a high-quality binary STL

## Run it in Fusion

1. Open Fusion.
2. Go to **Utilities > Add-Ins > Scripts and Add-Ins**.
3. On the **Scripts** tab, add this `FusionSingleJig` folder to **My Scripts**.
4. Select **FusionSingleJig** and click **Run**.
5. The F3D and STEP files are written beside the script. The slicer-ready STL
   is written automatically to the shared `fusion/print-files` folder.

## Current controlled dimensions

- Table width: `200.000 mm`
- Maximum usable field: `78.485 x 78.485 mm`
- Measurement field: `78.484 x 78.484 mm`, centered in the usable field
- Measured near edges: X `60.930 mm`, Y `68.430 mm`
- Edge-derived field center (reference only): X `100.172 mm`, Y `107.672 mm`
- Authoritative field center from the cross commanded at `(0, 0)`:
  X `96.190 mm`, Y `109.350 mm`
- Direct-cross minus edge-derived discrepancy: X `-3.982 mm`, Y `+1.678 mm`
- Inside side-stop span: `250.000 mm`
- Horizontal indexing travel: `50.000 mm`
- Nest center spacing: `50.000 mm`
- Four physical wafer-center positions: `(71.190, 84.350)`,
  `(121.190, 84.350)`, `(71.190, 134.350)`, and `(121.190, 134.350)`
- Wafer-support base: `2.000 mm`
- Structural base bridge: `2.000 mm` thick and exactly `100.000 mm` wide,
  extending from the front table bar through the lower nest to the horizontal
  centerline of the upper/rear nest at Y = `134.350 mm`
- Sidewall height above base: `1.500 mm`
- Downward table-contact lip: `5.000 mm`
- Reinforced PLA top ribs: `8.000 mm` wide x `8.000 mm` high above the base
- Diagonal ribs remain `8.000 mm` wide and taper in height from `8.000 mm`
  to the `1.500 mm` nest-wall height with a 45 degree end ramp
- Side bars extend to the same top height as the front reinforcement rib
- Primary-flat pickup opening: `20.000 mm` at the base, centered and
  round-ended, with a full-height 45 degree bevel opening to `36.000 mm` at top
- The pickup opening interrupts the raised front reinforcement and nest wall;
  the `2.000 mm` wafer-support floor remains continuous and uncut
- Secondary flat: left side, shared rotational datum wall
- Wafer fit: `0.500 mm` radial clearance per side (`1.000 mm`
  diametral), `0.500 mm` at the primary flat, and `0.100 mm` designed
  clearance at the secondary-flat datum
- Primary flat: faces table front

The table-contact bars are modeled as a **5 mm downward lip below the base**.
The reinforcement is one continuous front rib plus four diagonal ribs joining
the nest walls to the full-height side arms. Both ribs on each side fan from
the reinforced front/side corner, and the final pocket cuts preserve clearance.
If 5 mm was intended as their total top-to-bottom height, change
`TABLE_LIP_DROP` in `FusionSingleJig.py` before running it.
