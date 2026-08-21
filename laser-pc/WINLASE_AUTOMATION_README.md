# Auto-building WinLase jobs (`winlase_build_jobs.py`)

Turns a built pin-grid set into ready WinLase Pro jobs so you stop importing and
re-entering settings by hand for every pass. It makes **4 jobs per wafer** — one per
station (P1–P4), each holding every pass-angle DXF in that station's folder (named by
angle, e.g. `+45.0.dxf`), with the parallel-fill angle read from the filename; legacy
`Horizontal.dxf` / `Vertical.dxf` are a fallback mapping to 0° / 90°. Each is positioned
at true field coordinates, with 0.01 mm fill spacing, 1 pass, mark-fill on / outline
off. Output lands in `<set>/WinLaseJobs/`.

It drives WinLase Professional's COM automation server (`Winlase.Automate`,
`IAutomate` interface) per the *WinLase Automation Server Reference Manual* (Lanmark
Controls). It only **builds and saves** `.wlj` files — it never marks.

## Prerequisites (on the laser PC)
- WinLase Professional + its dongle + a scan card, with a lens cal loaded.
- Python + `pywin32`:  `pip install pywin32`
- **Close the WinLase GUI first** — the GUI and the automation server can't hold the
  marker library at the same time.

## Run it
Off-machine, confirm the plan (no WinLase needed):
```bash
python laser-pc/winlase_build_jobs.py output/DXFs/082126_AlignmentTest_v1 --dry-run
```
On the laser PC, verify placement on one job without saving, then build all four:
```bash
python laser-pc/winlase_build_jobs.py output/DXFs/082126_AlignmentTest_v1 --verify
python laser-pc/winlase_build_jobs.py output/DXFs/082126_AlignmentTest_v1
```
Several wafers at once:
```bash
python laser-pc/winlase_build_jobs.py output/DXFs/082126_AlignmentTest_v1 output/DXFs/082126_AlignmentTest_v2 output/DXFs/082126_AlignmentTest_v3
```

`--verify` imports P1 in memory and reports each object's placement delta, a size
sanity check, and an out-of-bounds check. **No warnings ⇒ safe to run the full build.**

## Still done by hand (by design)
Per `OPERATING_PROCEDURE.md` §3, in the WinLase GUI once per job:
- **Job loop = 175×** — a run-time execution setting, not stored geometry.
- **Z / table height**, jig re-seat between stations, and the actual mark (P1→P2→P3→P4).

Mark **speed (400 mm/s)** and **laser power/frequency** are inherited from WinLase's
current **default profile**; the script prints that profile so you can confirm it and
deliberately does not write laser parameters. If the default speed isn't 400 mm/s, set
it once in the GUI's default profile (it's global, not per-file).

## If `--verify` shows warnings
- **Size mismatch** (imported bits ≠ expected) → the DXF import filter is scaling;
  tell me and I'll pin the import filter / add explicit scaling.
- **Out of bounds** → the lens field is smaller than the mark radius; check the loaded
  lens cal.
- **COM errors on the first call** → your `winlase.tlb` may flag an `[out]` parameter
  differently; the COM calls are all isolated in `WinLaseSession` for a quick fix.
