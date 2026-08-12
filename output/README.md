# Generated laser job sets

Each folder under `DXFs/` is one complete, validated set of exposure files. Only
the pin-grid set is current. The two old-jig sets are kept because the
calibration history in
[CALIBRATION_AND_SLIDING_NEST_NOTES.md](../CALIBRATION_AND_SLIDING_NEST_NOTES.md)
refers to what they actually produced on the machine.

| Set | Jig | Field | Status |
| --- | --- | --- | --- |
| [080726_FourPosDicer_PinGrid52mm](DXFs/080726_FourPosDicer_PinGrid52mm) | eight-pin grid | `52 mm` | **current production** |
| [080726_FourPosDicer_OriginLocked](DXFs/080726_FourPosDicer_OriginLocked) | original printed four-position | `60 mm` | superseded |
| [080726_FourPosDicer](DXFs/080726_FourPosDicer) | original printed four-position | `60 mm` | superseded, failed on the machine |

## Which labeling each set uses

The current set labels folders by **jig station**, numbered clockwise from the
table's top-left: `P1` is the top-left jig position, which exposes the wafer's
bottom-right quadrant (`P2` top-right, `P3` bottom-right, `P4` bottom-left). See the
[coordinate convention](../CALIBRATION_AND_SLIDING_NEST_NOTES.md#coordinate-convention).

Both old-jig sets predate that change and label folders by **exposed wafer
quadrant**, where `DXF11` means the wafer's top-left. They were deliberately not
renumbered, because the recorded seam measurements name those folders. Converting
between the schemes swaps `11` and `22` and leaves `12` and `21` alone.

## Why the failed set is still here

`080726_FourPosDicer` is the first full-wafer run. Its bottom-right horizontal
pass landed about `8 mm` low. The splitter math was correct: the cause was
per-file automatic centering during laser import, because that set has cutting
geometry on layer `0` and nothing else, so every file had a different content
bounding box.

`080726_FourPosDicer_OriginLocked` is the same geometry re-emitted with four
`50 um` registration anchors on `REGISTRATION_DO_NOT_EXPOSE`, which force an
identical bounding box in every file so an auto-centering importer cannot displace
one job.

The current pin-grid set drops the anchors entirely: it is exposed with the laser's
automatic centering turned **off**, so each job lands at its true coordinates (the
DXF origin on the field center), verified by the field-placement self-test in the
validator. Never use fit-to-field scaling.

## Regenerating

Only the current set is reproducible from this repository:

```bash
python tools/build_pin_grid_set.py
python tools/validate_pin_grid_set.py
```

The two old-jig sets came from a `split_klayout_four_windows_old_jig_test.py`
profile carrying window-pattern offsets for a jig that no longer exists. That file
was removed on 2026-08-08; recover it from git history if these ever need
rebuilding.

There are no rendered previews here. The earlier set was removed on 2026-08-08: it
showed the superseded 60 mm field and named its panels by the pre-relabel scheme,
so `DXF11` in those images meant what is now `P3`. The figures under
[docs/figures](../docs/figures) are generated from the current geometry instead.
