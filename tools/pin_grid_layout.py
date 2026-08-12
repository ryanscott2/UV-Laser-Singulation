"""Single source of truth for the four pin-grid jig stations.

Imported by `build_pin_grid_set.py` and `validate_pin_grid_set.py` so the two
cannot disagree about which folder holds which quadrant.

Four locating pins per station, on the corners of a 4 x 4 grid-space square; the
inner 2 x 2 set was removed.

Position labels P1-P4 name the JIG STATION, numbered clockwise from the table's
top-left: P1 top-left, P2 top-right, P3 bottom-right, P4 bottom-left. Indexing the
jig moves the wafer, not the laser, so both axes invert and each station exposes
the diagonally opposite wafer quadrant.

Run this file directly to re-derive every number from the table geometry:

    python tools/pin_grid_layout.py
"""

from __future__ import annotations

from dataclasses import dataclass

# Table and calibration constants, all millimeters. These mirror the Fusion jig
# scripts; see CALIBRATION_AND_SLIDING_NEST_NOTES.md for how they were measured.
GRID_PITCH = 25.400
FIRST_HOLE_INSET = 12.700
OUTER_SPAN_SPACES = 4
LASER_ZERO = (96.190, 109.350)
NEST_OFFSET_FROM_PIN_CENTER = (+7.290, -4.950)

# Exposure field, matching split_klayout.py.
QUALIFIED_FIELD_SIZE_MM = 54.000
FIELD_HALF_SIZE_MM = QUALIFIED_FIELD_SIZE_MM / 2.0
# The galvo's addressable field is larger than the qualified region; a calibration
# offset can place geometry anywhere inside it, so placement is checked against this.
USABLE_FIELD_SIZE_MM = 60.000
USABLE_FIELD_HALF_MM = USABLE_FIELD_SIZE_MM / 2.0
STITCH_OVERLAP_MM = 0.200


@dataclass(frozen=True)
class Station:
    """One jig position: where the pins go and what the laser therefore hits."""

    label: str
    jig_row: int  # 1 = table rear/top, 2 = table front/bottom
    jig_col: int  # 1 = table left, 2 = table right
    jig_station: str
    field_center_mm: tuple[float, float]  # exposed field center in wafer coords
    outer_columns: tuple[int, int]
    outer_rows: tuple[int, int]

    @property
    def exposed_wafer_area(self) -> str:
        """Row before column, matching `quadrant_name` in the splitter so both
        write the same spelling into `exposed_wafer_area`."""
        x, y = self.field_center_mm
        return f"{'top' if y > 0 else 'bottom'}_{'right' if x > 0 else 'left'}"

    @property
    def splitter_job(self) -> str:
        """Output name emitted by split_klayout.py."""
        return f"{self.label}_jig_{self.jig_station}"

    @property
    def outer_front_left_pin(self) -> tuple[int, int]:
        """The single hole engraved on the plate: (column, row)."""
        return (min(self.outer_columns), min(self.outer_rows))

    @property
    def pin_pattern_center_mm(self) -> tuple[float, float]:
        return (
            FIRST_HOLE_INSET + GRID_PITCH * sum(self.outer_columns) / 2.0,
            FIRST_HOLE_INSET + GRID_PITCH * sum(self.outer_rows) / 2.0,
        )

    @property
    def wafer_center_mm(self) -> tuple[float, float]:
        cx, cy = self.pin_pattern_center_mm
        return (cx + NEST_OFFSET_FROM_PIN_CENTER[0], cy + NEST_OFFSET_FROM_PIN_CENTER[1])


STATIONS: tuple[Station, ...] = (
    Station("P1", 1, 1, "top_left", (+25.400, -25.400), (0, 4), (3, 7)),
    Station("P2", 1, 2, "top_right", (-25.400, -25.400), (2, 6), (3, 7)),
    Station("P3", 2, 2, "bottom_right", (-25.400, +25.400), (2, 6), (1, 5)),
    Station("P4", 2, 1, "bottom_left", (+25.400, +25.400), (0, 4), (1, 5)),
)

# The center-field station, for the single centered pass. Same physical plate.
CENTER_OUTER_COLUMNS = (1, 5)
CENTER_OUTER_ROWS = (2, 6)


def hole_coordinate_mm(column: int, row: int) -> tuple[float, float]:
    """Table coordinate of a grid hole center, measured from left/front edges."""
    return (FIRST_HOLE_INSET + GRID_PITCH * column, FIRST_HOLE_INSET + GRID_PITCH * row)


def hole_label(column: int, row: int) -> str:
    """The 1-indexed label a human reads on the plate and in the docs: C1 is the
    first column from the table left, R1 the first row from the front. Columns and
    rows are stored 0-indexed everywhere in the geometry (C0/R0 = first hole); only
    the engraved and documented labels count from one, to match how an operator
    counts physical holes and to stop the off-by-one seating error."""
    return f"C{column + 1} R{row + 1}"


def check() -> list[str]:
    """Re-derive each station from the grid geometry. Returns failure strings."""
    failures = []
    half = OUTER_SPAN_SPACES / 2.0

    for station in STATIONS:
        # The exposed area is laser zero expressed in wafer coordinates.
        wx, wy = station.wafer_center_mm
        exposed = (round(LASER_ZERO[0] - wx, 3), round(LASER_ZERO[1] - wy, 3))
        if exposed != station.field_center_mm:
            failures.append(
                f"{station.label}: pins imply exposure {exposed}, "
                f"table says {station.field_center_mm}"
            )

        # Both pin squares must span the documented four grid spaces.
        for axis, outer in (("columns", station.outer_columns), ("rows", station.outer_rows)):
            if abs(outer[1] - outer[0]) != OUTER_SPAN_SPACES:
                failures.append(
                    f"{station.label}: outer {axis} {outer} do not span {OUTER_SPAN_SPACES}"
                )

        # The engraved hole must sit half a span left of and forward of center.
        col, row = station.outer_front_left_pin
        expected = (
            FIRST_HOLE_INSET + GRID_PITCH * (sum(station.outer_columns) / 2.0 - half),
            FIRST_HOLE_INSET + GRID_PITCH * (sum(station.outer_rows) / 2.0 - half),
        )
        actual = hole_coordinate_mm(col, row)
        if tuple(round(v, 3) for v in actual) != tuple(round(v, 3) for v in expected):
            failures.append(f"{station.label}: engraved pin {hole_label(col, row)} is not front-left")

        # The label digits must agree with the station name.
        expected_name = (
            f"{'top' if station.jig_row == 1 else 'bottom'}_"
            f"{'left' if station.jig_col == 1 else 'right'}"
        )
        if station.jig_station != expected_name:
            failures.append(f"{station.label}: digits imply {expected_name}, not {station.jig_station}")

    # The center station must land the wafer exactly on laser zero.
    cx = FIRST_HOLE_INSET + GRID_PITCH * sum(CENTER_OUTER_COLUMNS) / 2.0
    cy = FIRST_HOLE_INSET + GRID_PITCH * sum(CENTER_OUTER_ROWS) / 2.0
    center_wafer = (
        round(cx + NEST_OFFSET_FROM_PIN_CENTER[0], 3),
        round(cy + NEST_OFFSET_FROM_PIN_CENTER[1], 3),
    )
    if center_wafer != LASER_ZERO:
        failures.append(f"center station: wafer center {center_wafer} is not laser zero {LASER_ZERO}")

    return failures


def main() -> int:
    print(f"{'label':6} {'jig station':13} {'engraved pin':12} {'hole (mm)':20} exposes")
    for station in STATIONS:
        col, row = station.outer_front_left_pin
        hx, hy = hole_coordinate_mm(col, row)
        print(
            f"{station.label:6} {station.jig_station:13} {hole_label(col, row):12} "
            f"{f'({hx:.1f}, {hy:.1f})':20} {station.exposed_wafer_area} "
            f"at {station.field_center_mm}"
        )

    col, row = (min(CENTER_OUTER_COLUMNS), min(CENTER_OUTER_ROWS))
    hx, hy = hole_coordinate_mm(col, row)
    print(
        f"{'CENTER':6} {'center':13} {hole_label(col, row):12} "
        f"{f'({hx:.1f}, {hy:.1f})':20} wafer center on laser zero"
    )

    failures = check()
    print()
    if failures:
        for failure in failures:
            print(f"FAIL  {failure}")
        return 1
    print("All station geometry re-derives from the table grid. OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
