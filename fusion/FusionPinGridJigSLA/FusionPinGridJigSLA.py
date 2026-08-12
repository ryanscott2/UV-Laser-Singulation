"""Build and export the SLA variant of the four-dowel grid-indexed 100 mm wafer jig.

A copy of FusionPinGridJig.py for SLA/resin printing (still with pressed steel
dowels). The only functional difference is SCALE_FACTOR: a single uniform scale
applied to the whole solid about the origin (the pin-pattern center) so a resin
print can be sized to come out on nominal dimensions -- most importantly the
101.600 mm dowel-pin pitch, which must match the table's 1 inch grid.

Formlabs PreForm already auto-compensates cure shrinkage, so leave SCALE_FACTOR at
1.000 for the first print, then measure a known span (ideally the dowel-hole pitch,
nominal 101.600 mm) and set SCALE_FACTOR = nominal / measured to null any residual
(Formlabs standard/general-purpose resins leave up to ~0.15% XY, ~0.15 mm on the
pitch). Scaling about the origin corrects the pitch and every feature proportionally.
"""

from __future__ import annotations

import math
import os
import traceback

import adsk.core
import adsk.fusion


# =============================================================================
# USER-EDITABLE DIMENSIONS (millimeters)
# =============================================================================

# SLA shrink-compensation scale. A single uniform scale is applied to the whole
# solid about the origin (the pin-pattern center) at the end of build_model. Leave
# at 1.000 for the first print -- Formlabs PreForm already compensates cure shrink
# -- then set SCALE_FACTOR = nominal / measured from a test print (measure the
# 101.600 mm dowel-hole pitch) to null any residual; > 1.0 grows the model.
SCALE_FACTOR = 1.000

# Table/grid calibration.
GRID_PITCH = 25.400
INDEX_MOVE_SPACES = 2
INDEX_MOVE = GRID_PITCH * INDEX_MOVE_SPACES
OUTER_PIN_PATTERN_SPACES = 4
OUTER_PIN_PATTERN_SPAN = GRID_PITCH * OUTER_PIN_PATTERN_SPACES
FIRST_HOLE_EDGE_OFFSET = 12.700

# Authoritative laser-zero calibration retained from the direct cross test.
LASER_ZERO_X = 96.190
LASER_ZERO_Y = 109.350

# The selected low/high grid rectangles have mean centers of X=88.900 mm and
# Y=114.300 mm. These offsets place the four exposure centers at +/-25.4 mm.
NEST_OFFSET_FROM_PIN_CENTER_X = +7.290
NEST_OFFSET_FROM_PIN_CENTER_Y = -4.950
# Print-v2 machine-offset correction. The 081126 alignment test measured the
# exposure landing off the wafer flats; after the re-measure and offset trims the
# best-known value is +3.187 mm X, -1.346 mm Y. Shifting the nest by that much
# relative to the pins makes a fixed, field-centered exposure land correctly, so
# the DXFs no longer need the software offset. IMPORTANT: once a jig printed from
# this is in use, reset GLOBAL_X/Y_OFFSET_UM to 0 in python/split_klayout.py, or
# the DXF and the jig double-correct.
NEST_CALIBRATION_X = +3.187
NEST_CALIBRATION_Y = -1.346
NEST_CENTER_X = NEST_OFFSET_FROM_PIN_CENTER_X + NEST_CALIBRATION_X
NEST_CENTER_Y = NEST_OFFSET_FROM_PIN_CENTER_Y + NEST_CALIBRATION_Y

# Four steel locating dowels on the corners of a 4 x 4 grid-space square. The
# inner 2 x 2 set was removed: the outer square alone fixes position and rotation,
# and fewer dowels means fewer holes to line up when seating the plate.
#
# The printed body no longer forms the pins. Each corner has a press-fit through
# hole in a raised boss that takes a 3/16 in (4.7625 mm) steel dowel. Moving the
# locating surface to ground steel decouples pin precision and wear from the print
# tolerance: the dowel slip-fits the table's 1/4-20 tapped hole (~4.87 mm crest
# ID) and press-fits the boss. Retain with a drop of epoxy; the dowel's far end
# bears in the table hole, so the boss only has to hold it square and captive.
DOWEL_DIAMETER = 4.7625          # 3/16 in ground steel dowel
DOWEL_PROTRUSION = 5.000         # protrusion below the base into the table hole; matches the v2 pins (5 mm)
# Bore engagement = BOSS_HEIGHT + BASE_THICKNESS = 8 mm, so cut each dowel to
# 8 + 5 = 13 mm and press it flush with the boss top to leave 5 mm proud below.
# Bore for the dowel. Resin (MSLA) prints small holes closer to nominal than FDM
# (light bleed shrinks them a little, but less than FDM's extrusion undersize), so
# this is dropped from the PLA jig's 4.85 to 4.80 for a snugger fit on the
# 4.7625 mm dowel. Resin is brittle, so still retain with epoxy rather than a hard
# press. Dial in on a printed coupon (try 4.70 / 4.75 / 4.80 / 4.85) for your resin.
DOWEL_HOLE_DIAMETER = 4.800
BOSS_DIAMETER = 8.500            # ~1.85 mm wall around the bore
BOSS_HEIGHT = 5.000              # above the platform top; total engagement = base + boss = 8 mm

# Platform and wafer nest. The plate is a tight bounding box computed in
# build_model, not centered on the nest: the corner bosses sit flush to the left
# and rear edges (they merge into the perimeter bar there), the right edge holds
# the top-right station map inside the rim, and the front edge holds the front
# labels forward of the nest. PLATFORM_NEST_GAP keeps the perimeter bar clear of
# the raised nest wall on the sides where the nest, not a boss, is outermost.
PLATFORM_NEST_GAP = 1.000
BASE_THICKNESS = 3.000
OUTER_BAR_WIDTH = 4.000
OUTER_BAR_HEIGHT = 4.000
SIDEWALL_HEIGHT = 1.500
SIDEWALL_THICKNESS = 3.000

# Small pickup tabs centered on the left and right edges, so the plate can be
# lifted straight off the pins without prying at the wafer or the nest wall. They
# start at the top of the platform, leaving a full base-thickness undercut to hook under.
SIDE_TAB_PROTRUSION = 10.000
SIDE_TAB_LENGTH = 24.000

WAFER_DIAMETER = 100.000
PRIMARY_FLAT_LENGTH = 32.500
SECONDARY_FLAT_LENGTH = 18.000
# Nest clearances. The wafer is located purely by its two flats for maximum
# repeatability, so the flat datums are tight and the arc is deliberately loose
# enough that it never contacts first:
#   - PRIMARY_FLAT (front datum) and SECONDARY_DATUM (left datum): 0.175 mm each.
#   - RADIAL (arc) must exceed the flat-seat diagonal
#     sqrt(PRIMARY^2 + SECONDARY^2) = 0.175 * sqrt(2) = 0.248 mm, or the front-left
#     arc jams before both flats seat. 0.500 leaves ~0.25 mm arc clearance when
#     both flats are home, sized so every wafer (incl. undersize, which seats
#     deeper into the corner) clears the arc and datums on its flats.
# NOTE: this tightens the flats from the old v2 fit (0.500 / 0.500 / 0.300), which
# shifts the wafer seat and INVALIDATES the current NEST_CALIBRATION. A manual
# recalibration is required with this print; see CALIBRATION_AND_SLIDING_NEST_NOTES.md.
RADIAL_CLEARANCE = 0.500
PRIMARY_FLAT_CLEARANCE = 0.175
SECONDARY_DATUM_CLEARANCE = 0.175

# Two gaps in the raised lip, 180 degrees apart, so a Kapton tab can run from the
# platform onto the wafer without having to bridge the 1.5 mm wall. The wafer is
# pushed against the secondary flat and taped down; the pocket only locates it,
# it does not retain it. Both cut the raised wall only -- the 2 mm support
# platform stays continuous under the wafer.
#
# Both are 15 mm. They stay separate constants so either can be tuned alone, but
# PICKUP_GAP_WIDTH additionally drives the outer-bar tweezer notch, so changing
# it moves that notch too.
PICKUP_GAP_WIDTH = 15.000
REAR_TAPE_GAP_WIDTH = 15.000

# One engraving on the platform floor: a two-line credit in the top-left corner,
# just inboard of the top-left dowel boss.
ANNOTATION_DEPTH = 0.500
ANNOTATION_TEXT_HEIGHT = 2.500
ANNOTATION_MARGIN_Y = 5.000
# Clearance from the top-left dowel boss to the nearest credit glyph. The credit
# is anchored off the boss edge (not the platform corner) so it stays clear of
# the boss no matter how the platform is sized.
LABEL_BOSS_GAP = 3.500
TITLE_BOX_WIDTH = 40.000
TITLE_BOX_HEIGHT = 14.000
TITLE_TEXT = (
    "DESIGNED BY:\n"
    "RYAN SCOTT"
)

SEGMENTS = 180


def cm(mm: float) -> float:
    """Fusion API internal length unit is centimeters."""
    return mm / 10.0


def clip_polygon(points, axis: int, threshold: float, keep_greater: bool):
    if not points:
        return []
    result = []
    previous = points[-1]
    previous_inside = previous[axis] >= threshold if keep_greater else previous[axis] <= threshold
    for current in points:
        current_inside = current[axis] >= threshold if keep_greater else current[axis] <= threshold
        if current_inside != previous_inside:
            delta = current[axis] - previous[axis]
            ratio = (threshold - previous[axis]) / delta
            result.append(
                (
                    previous[0] + ratio * (current[0] - previous[0]),
                    previous[1] + ratio * (current[1] - previous[1]),
                )
            )
        if current_inside:
            result.append(current)
        previous = current
        previous_inside = current_inside
    return result


def wafer_polygon(
    center_x: float,
    center_y: float,
    radial_offset: float = 0.0,
    primary_relief: float = 0.0,
    secondary_relief: float = 0.0,
):
    radius = WAFER_DIAMETER / 2.0
    primary_depth = math.sqrt(radius**2 - (PRIMARY_FLAT_LENGTH / 2.0) ** 2)
    secondary_depth = math.sqrt(radius**2 - (SECONDARY_FLAT_LENGTH / 2.0) ** 2)
    expanded_radius = radius + radial_offset
    points = [
        (
            center_x + expanded_radius * math.cos(index * 2.0 * math.pi / SEGMENTS),
            center_y + expanded_radius * math.sin(index * 2.0 * math.pi / SEGMENTS),
        )
        for index in range(SEGMENTS)
    ]
    # Primary flat faces table front (-Y); secondary flat faces table left (-X).
    points = clip_polygon(
        points,
        axis=1,
        threshold=center_y - primary_depth - primary_relief,
        keep_greater=True,
    )
    points = clip_polygon(
        points,
        axis=0,
        threshold=center_x - secondary_depth - secondary_relief,
        keep_greater=True,
    )
    return points


def rectangle_points(x: float, y: float, width: float, height: float):
    return [(x, y), (x + width, y), (x + width, y + height), (x, y + height)]


def vertical_capsule_points(center_x, start_center_y, end_center_y, width, segments=28):
    radius = width / 2.0
    points = [(center_x - radius, start_center_y), (center_x - radius, end_center_y)]
    for index in range(1, segments + 1):
        angle = math.pi - index * math.pi / segments
        points.append(
            (center_x + radius * math.cos(angle), end_center_y + radius * math.sin(angle))
        )
    points.append((center_x + radius, start_center_y))
    for index in range(1, segments):
        angle = -index * math.pi / segments
        points.append(
            (center_x + radius * math.cos(angle), start_center_y + radius * math.sin(angle))
        )
    return points


def offset_plane(component, offset_mm: float, name: str):
    plane_input = component.constructionPlanes.createInput()
    plane_input.setByOffset(
        component.xYConstructionPlane,
        adsk.core.ValueInput.createByString(f"{offset_mm} mm"),
    )
    plane = component.constructionPlanes.add(plane_input)
    plane.name = name
    return plane


def polygon_sketch(component, plane, points_mm, name: str):
    sketch = component.sketches.add(plane)
    sketch.name = name
    points = [adsk.core.Point3D.create(cm(x), cm(y), 0) for x, y in points_mm]
    lines = sketch.sketchCurves.sketchLines
    for index, point in enumerate(points):
        lines.addByTwoPoints(point, points[(index + 1) % len(points)])
    return sketch


def ring_sketch(component, plane, outer_points_mm, inner_points_mm, name: str):
    sketch = component.sketches.add(plane)
    sketch.name = name
    lines = sketch.sketchCurves.sketchLines
    for loop in (outer_points_mm, inner_points_mm):
        points = [adsk.core.Point3D.create(cm(x), cm(y), 0) for x, y in loop]
        for index, point in enumerate(points):
            lines.addByTwoPoints(point, points[(index + 1) % len(points)])
    return sketch


def circle_sketch(component, plane, center_x, center_y, diameter, name):
    sketch = component.sketches.add(plane)
    sketch.name = name
    sketch.sketchCurves.sketchCircles.addByCenterRadius(
        adsk.core.Point3D.create(cm(center_x), cm(center_y), 0),
        cm(diameter / 2.0),
    )
    return sketch


def extrude_profile(component, sketch, distance_mm, operation, name):
    if sketch.profiles.count != 1:
        raise RuntimeError(f"{name}: expected one profile, found {sketch.profiles.count}")
    extrudes = component.features.extrudeFeatures
    feature_input = extrudes.createInput(sketch.profiles.item(0), operation)
    feature_input.setDistanceExtent(
        False,
        adsk.core.ValueInput.createByString(f"{distance_mm} mm"),
    )
    feature = extrudes.add(feature_input)
    feature.name = name
    sketch.isVisible = False
    return feature


def engrave_text(component, plane, text, x_min, y_min, width, height, text_height, depth, name,
                 align=None):
    """Raise multiline sketch text above the platform's top face (additive)."""
    if align is None:
        align = adsk.core.HorizontalAlignments.LeftHorizontalAlignment
    sketch = component.sketches.add(plane)
    sketch.name = f"{name} Sketch"
    text_input = sketch.sketchTexts.createInput2(text, cm(text_height))
    placed = text_input.setAsMultiLine(
        adsk.core.Point3D.create(cm(x_min), cm(y_min), 0),
        adsk.core.Point3D.create(cm(x_min + width), cm(y_min + height), 0),
        align,
        adsk.core.VerticalAlignments.TopVerticalAlignment,
        0.0,
    )
    if not placed:
        raise RuntimeError(f"{name}: Fusion rejected the multiline text box")
    sketch_text = sketch.sketchTexts.add(text_input)
    if not sketch_text:
        raise RuntimeError(f"{name}: Fusion could not create sketch text")

    extrudes = component.features.extrudeFeatures
    feature_input = extrudes.createInput(
        sketch_text,
        adsk.fusion.FeatureOperations.JoinFeatureOperation,
    )
    feature_input.setDistanceExtent(
        False,
        adsk.core.ValueInput.createByString(f"{depth} mm"),
    )
    feature = extrudes.add(feature_input)
    feature.name = name
    sketch.isVisible = False
    return feature


def extrude_polygon(component, plane, points_mm, distance_mm, operation, name):
    return extrude_profile(
        component,
        polygon_sketch(component, plane, points_mm, f"{name} Sketch"),
        distance_mm,
        operation,
        name,
    )


def extrude_ring(component, plane, outer_points, inner_points, distance_mm, operation, name):
    sketch = ring_sketch(component, plane, outer_points, inner_points, f"{name} Sketch")
    if sketch.profiles.count != 2:
        raise RuntimeError(f"{name}: expected two profiles, found {sketch.profiles.count}")
    profiles = [sketch.profiles.item(index) for index in range(sketch.profiles.count)]
    # With a 4 mm rim around a ~140 mm platform, the annular profile has the
    # smaller area; the other profile is the large open center.
    ring_profile = min(profiles, key=lambda profile: profile.areaProperties().area)
    extrudes = component.features.extrudeFeatures
    feature_input = extrudes.createInput(ring_profile, operation)
    feature_input.setDistanceExtent(
        False,
        adsk.core.ValueInput.createByString(f"{distance_mm} mm"),
    )
    feature = extrudes.add(feature_input)
    feature.name = name
    sketch.isVisible = False
    return feature


def loft_polygons(component, first_plane, first_points, second_plane, second_points, operation, name):
    first = polygon_sketch(component, first_plane, first_points, f"{name} Lower Sketch")
    second = polygon_sketch(component, second_plane, second_points, f"{name} Upper Sketch")
    if first.profiles.count != 1 or second.profiles.count != 1:
        raise RuntimeError(f"{name}: expected one profile on each loft plane")
    loft_input = component.features.loftFeatures.createInput(operation)
    loft_input.loftSections.add(first.profiles.item(0))
    loft_input.loftSections.add(second.profiles.item(0))
    loft_input.isSolid = True
    feature = component.features.loftFeatures.add(loft_input)
    feature.name = name
    first.isVisible = False
    second.isVisible = False
    return feature


def loft_circles(
    component,
    first_plane,
    first_center,
    first_diameter,
    second_plane,
    second_center,
    second_diameter,
    operation,
    name,
):
    first = circle_sketch(
        component, first_plane, first_center[0], first_center[1], first_diameter, f"{name} Tip"
    )
    second = circle_sketch(
        component,
        second_plane,
        second_center[0],
        second_center[1],
        second_diameter,
        f"{name} Shoulder",
    )
    loft_input = component.features.loftFeatures.createInput(operation)
    loft_input.loftSections.add(first.profiles.item(0))
    loft_input.loftSections.add(second.profiles.item(0))
    loft_input.isSolid = True
    feature = component.features.loftFeatures.add(loft_input)
    feature.name = name
    first.isVisible = False
    second.isVisible = False
    return feature


def add_parameter(design, name, value_mm, comment):
    design.userParameters.add(
        name,
        adsk.core.ValueInput.createByString(f"{value_mm} mm"),
        "mm",
        comment,
    )


def build_model(design):
    component = design.rootComponent
    xy_plane = component.xYConstructionPlane
    wall_plane = offset_plane(component, BASE_THICKNESS, "Top of Wafer Platform")
    pickup_top_plane = offset_plane(
        component,
        BASE_THICKNESS + SIDEWALL_HEIGHT + 0.2,
        "Top of 45 Degree Pickup Bevel",
    )
    outer_bar_notch_top_plane = offset_plane(
        component,
        BASE_THICKNESS + OUTER_BAR_HEIGHT + 0.2,
        "Top of 45 Degree Outer Bar Notch",
    )
    boss_top_plane = offset_plane(
        component,
        BASE_THICKNESS + BOSS_HEIGHT,
        "Dowel Boss Top Plane",
    )

    # --- Minimal platform: a tight bounding box, not centered on the nest ---
    # Each edge sits at whichever is outermost: a corner boss (flush, merging into
    # the perimeter bar) or the nest wall plus a bar width and gap. With the labels
    # removed this packs the plate to the bosses on the left/rear and to the nest
    # wall on the right/front.
    _wafer_r = WAFER_DIAMETER / 2.0
    _primary_depth = math.sqrt(_wafer_r ** 2 - (PRIMARY_FLAT_LENGTH / 2.0) ** 2)
    _secondary_depth = math.sqrt(_wafer_r ** 2 - (SECONDARY_FLAT_LENGTH / 2.0) ** 2)
    _boss_reach = OUTER_PIN_PATTERN_SPAN / 2.0 + BOSS_DIAMETER / 2.0
    _nest_left = NEST_CENTER_X - _secondary_depth - SIDEWALL_THICKNESS
    _nest_right = NEST_CENTER_X + _wafer_r + SIDEWALL_THICKNESS
    _nest_rear = NEST_CENTER_Y + _wafer_r + SIDEWALL_THICKNESS
    _nest_front = NEST_CENTER_Y - _primary_depth - SIDEWALL_THICKNESS
    platform_left = min(-_boss_reach, _nest_left - PLATFORM_NEST_GAP - OUTER_BAR_WIDTH)
    platform_right = max(_boss_reach, _nest_right + PLATFORM_NEST_GAP + OUTER_BAR_WIDTH)
    platform_rear = max(_boss_reach, _nest_rear + PLATFORM_NEST_GAP + OUTER_BAR_WIDTH)
    platform_front = min(-_boss_reach, _nest_front - PLATFORM_NEST_GAP - OUTER_BAR_WIDTH)
    platform_size_x = platform_right - platform_left
    platform_size_y = platform_rear - platform_front

    for name, value, comment in (
        ("gridPitch", GRID_PITCH, "Table hole-grid pitch"),
        ("indexMove", INDEX_MOVE, "Two-grid-space indexing move"),
        ("outerPinPatternSpan", OUTER_PIN_PATTERN_SPAN, "Four-space outer pin span"),
        ("dowelDiameter", DOWEL_DIAMETER, "3/16 in steel locating dowel diameter"),
        ("dowelHoleDiameter", DOWEL_HOLE_DIAMETER, "Press-fit bore for the dowel"),
        ("bossHeight", BOSS_HEIGHT, "Dowel boss height above platform"),
        ("bossDiameter", BOSS_DIAMETER, "Dowel boss outer diameter"),
        ("platformSizeX", platform_size_x, "Overall plate width"),
        ("platformSizeY", platform_size_y, "Overall plate depth"),
        ("baseThickness", BASE_THICKNESS, "Wafer platform thickness"),
        ("outerBarWidth", OUTER_BAR_WIDTH, "Perimeter reinforcement width"),
        ("outerBarHeight", OUTER_BAR_HEIGHT, "Perimeter reinforcement height"),
        ("sidewallHeight", SIDEWALL_HEIGHT, "Nest lip height above platform"),
        ("nestOffsetX", NEST_OFFSET_FROM_PIN_CENTER_X, "Nest X from pin-square center"),
        ("nestOffsetY", NEST_OFFSET_FROM_PIN_CENTER_Y, "Nest Y from pin-square center"),
        ("pickupGapWidth", PICKUP_GAP_WIDTH, "Primary-flat pickup opening"),
        ("rearTapeGapWidth", REAR_TAPE_GAP_WIDTH, "Rear tape-access gap in the lip"),
        ("annotationDepth", ANNOTATION_DEPTH, "Baseplate text engraving depth"),
        ("annotationTextHeight", ANNOTATION_TEXT_HEIGHT, "Baseplate text height"),
    ):
        add_parameter(design, name, value, comment)

    # The platform supports the wafer and carries all four dowel bosses.
    platform = rectangle_points(
        platform_left,
        platform_front,
        platform_size_x,
        platform_size_y,
    )
    extrude_polygon(
        component,
        xy_plane,
        platform,
        BASE_THICKNESS,
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation,
        "Wafer Platform",
    )

    # Continuous 4 x 4 mm perimeter reinforcement above the platform.
    inner_platform = rectangle_points(
        platform_left + OUTER_BAR_WIDTH,
        platform_front + OUTER_BAR_WIDTH,
        platform_size_x - 2.0 * OUTER_BAR_WIDTH,
        platform_size_y - 2.0 * OUTER_BAR_WIDTH,
    )
    extrude_ring(
        component,
        wall_plane,
        platform,
        inner_platform,
        OUTER_BAR_HEIGHT,
        adsk.fusion.FeatureOperations.JoinFeatureOperation,
        "4 x 4 mm Perimeter Reinforcement Bar",
    )

    # Pickup tabs, one per side, centered on the platform's Y center. Extruded
    # from the top of the platform rather than from the table, so each tab
    # is cantilevered with a 2 mm gap underneath: that undercut is what a
    # fingernail or tweezer tip hooks into to lift the plate straight off its
    # pins, instead of prying against the wafer or the nest wall.
    platform_left_x = platform_left
    platform_right_x = platform_right
    for tab_name, tab_x in (
        ("Left Pickup Tab", platform_left_x - SIDE_TAB_PROTRUSION),
        ("Right Pickup Tab", platform_right_x),
    ):
        extrude_polygon(
            component,
            wall_plane,
            rectangle_points(
                tab_x,
                NEST_CENTER_Y - SIDE_TAB_LENGTH / 2.0,
                SIDE_TAB_PROTRUSION,
                SIDE_TAB_LENGTH,
            ),
            OUTER_BAR_HEIGHT,
            adsk.fusion.FeatureOperations.JoinFeatureOperation,
            tab_name,
        )

    # Centered tweezer notch aligned to the pickup opening, same width, with
    # a 45 degree flare through the full 4 mm perimeter bar. The platform
    # remains continuous.
    platform_front_y = platform_front
    outer_notch_bottom = rectangle_points(
        NEST_CENTER_X - PICKUP_GAP_WIDTH / 2.0,
        platform_front_y - 0.1,
        PICKUP_GAP_WIDTH,
        OUTER_BAR_WIDTH + 0.2,
    )
    outer_notch_expansion = OUTER_BAR_HEIGHT + 0.2
    outer_notch_top = rectangle_points(
        NEST_CENTER_X - PICKUP_GAP_WIDTH / 2.0 - outer_notch_expansion,
        platform_front_y - 0.1 - outer_notch_expansion,
        PICKUP_GAP_WIDTH + 2.0 * outer_notch_expansion,
        OUTER_BAR_WIDTH + 0.2 + 2.0 * outer_notch_expansion,
    )
    loft_polygons(
        component,
        wall_plane,
        outer_notch_bottom,
        outer_bar_notch_top_plane,
        outer_notch_top,
        adsk.fusion.FeatureOperations.CutFeatureOperation,
        f"{PICKUP_GAP_WIDTH:g} mm Outer Bar Tweezer Notch with 45 Degree Sides",
    )

    # Raised nest wall; the pocket cut below leaves only the 3 mm wall ring.
    outer = wafer_polygon(
        NEST_CENTER_X,
        NEST_CENTER_Y,
        radial_offset=SIDEWALL_THICKNESS,
        primary_relief=SIDEWALL_THICKNESS,
        secondary_relief=SIDEWALL_THICKNESS,
    )
    extrude_polygon(
        component,
        wall_plane,
        outer,
        SIDEWALL_HEIGHT,
        adsk.fusion.FeatureOperations.JoinFeatureOperation,
        "1.5 mm Raised Wafer Nest",
    )

    pocket = wafer_polygon(
        NEST_CENTER_X,
        NEST_CENTER_Y,
        radial_offset=RADIAL_CLEARANCE,
        primary_relief=PRIMARY_FLAT_CLEARANCE,
        secondary_relief=SECONDARY_DATUM_CLEARANCE,
    )
    extrude_polygon(
        component,
        wall_plane,
        pocket,
        SIDEWALL_HEIGHT + 0.1,
        adsk.fusion.FeatureOperations.CutFeatureOperation,
        "Final Wafer Pocket Clearance",
    )

    # Beveled 20 mm pickup opening through the raised primary-flat wall only.
    wafer_radius = WAFER_DIAMETER / 2.0
    primary_depth = math.sqrt(wafer_radius**2 - (PRIMARY_FLAT_LENGTH / 2.0) ** 2)
    outer_flat_y = NEST_CENTER_Y - primary_depth - SIDEWALL_THICKNESS
    nominal_flat_y = NEST_CENTER_Y - primary_depth
    pickup_bottom = vertical_capsule_points(
        NEST_CENTER_X,
        outer_flat_y,
        nominal_flat_y,
        PICKUP_GAP_WIDTH,
    )
    bevel_expansion = SIDEWALL_HEIGHT + 0.2
    pickup_top = vertical_capsule_points(
        NEST_CENTER_X,
        outer_flat_y - bevel_expansion,
        nominal_flat_y + bevel_expansion,
        PICKUP_GAP_WIDTH + 2.0 * bevel_expansion,
    )
    loft_polygons(
        component,
        wall_plane,
        pickup_bottom,
        pickup_top_plane,
        pickup_top,
        adsk.fusion.FeatureOperations.CutFeatureOperation,
        f"{PICKUP_GAP_WIDTH:g} mm Pickup Opening with 45 Degree Bevel",
    )

    # The matching tape gap, directly opposite the primary flat on the plain arc.
    # Spans the full wall thickness radially and bevels 45 degrees on both sides,
    # the same way the pickup opening does. Starting inboard of the pocket wall
    # guarantees the lip is cut through; there is no material inside that radius.
    rear_gap_inner_y = NEST_CENTER_Y + wafer_radius
    rear_gap_depth = SIDEWALL_THICKNESS + 0.2
    rear_gap_bottom = rectangle_points(
        NEST_CENTER_X - REAR_TAPE_GAP_WIDTH / 2.0,
        rear_gap_inner_y,
        REAR_TAPE_GAP_WIDTH,
        rear_gap_depth,
    )
    rear_gap_top = rectangle_points(
        NEST_CENTER_X - REAR_TAPE_GAP_WIDTH / 2.0 - bevel_expansion,
        rear_gap_inner_y,
        REAR_TAPE_GAP_WIDTH + 2.0 * bevel_expansion,
        rear_gap_depth,
    )
    loft_polygons(
        component,
        wall_plane,
        rear_gap_bottom,
        pickup_top_plane,
        rear_gap_top,
        adsk.fusion.FeatureOperations.CutFeatureOperation,
        f"{REAR_TAPE_GAP_WIDTH:g} mm Rear Tape Gap with 45 Degree Bevel",
    )

    # The perimeter bar gets the same 45 degree notch behind the rear tape gap
    # that it already has behind the pickup opening, so a finger and a tab can
    # reach the wafer edge from outside the plate. The platform is untouched.
    platform_rear_y = platform_rear
    rear_notch_bottom = rectangle_points(
        NEST_CENTER_X - REAR_TAPE_GAP_WIDTH / 2.0,
        platform_rear_y - OUTER_BAR_WIDTH - 0.1,
        REAR_TAPE_GAP_WIDTH,
        OUTER_BAR_WIDTH + 0.2,
    )
    rear_notch_top = rectangle_points(
        NEST_CENTER_X - REAR_TAPE_GAP_WIDTH / 2.0 - outer_notch_expansion,
        platform_rear_y - OUTER_BAR_WIDTH - 0.1 - outer_notch_expansion,
        REAR_TAPE_GAP_WIDTH + 2.0 * outer_notch_expansion,
        OUTER_BAR_WIDTH + 0.2 + 2.0 * outer_notch_expansion,
    )
    loft_polygons(
        component,
        wall_plane,
        rear_notch_bottom,
        outer_bar_notch_top_plane,
        rear_notch_top,
        adsk.fusion.FeatureOperations.CutFeatureOperation,
        f"{REAR_TAPE_GAP_WIDTH:g} mm Rear Outer Bar Notch with 45 Degree Sides",
    )

    # A raised boss at each corner of the 4 x 4 grid-space square, each with a
    # press-fit through hole for a 3/16 in steel dowel. The boss joins the platform
    # (and the outer bar where they meet), giving the bore base + boss = 8 mm of
    # engagement. The left and rear bosses ride the platform edge and form a small
    # lobe there, which is harmless. The bore is cut from the boss top straight
    # down through the base so the dowel drops in from above and protrudes below.
    outer_half_span = OUTER_PIN_PATTERN_SPAN / 2.0
    dowel_locations = (
        ("Outer Front Left", -outer_half_span, -outer_half_span),
        ("Outer Front Right", +outer_half_span, -outer_half_span),
        ("Outer Rear Left", -outer_half_span, +outer_half_span),
        ("Outer Rear Right", +outer_half_span, +outer_half_span),
    )
    for boss_name, x, y in dowel_locations:
        boss = circle_sketch(
            component,
            wall_plane,
            x,
            y,
            BOSS_DIAMETER,
            f"{boss_name} Dowel Boss Sketch",
        )
        extrude_profile(
            component,
            boss,
            BOSS_HEIGHT,
            adsk.fusion.FeatureOperations.JoinFeatureOperation,
            f"{boss_name} Dowel Boss",
        )
        bore = circle_sketch(
            component,
            boss_top_plane,
            x,
            y,
            DOWEL_HOLE_DIAMETER,
            f"{boss_name} Dowel Bore Sketch",
        )
        extrude_profile(
            component,
            bore,
            -(BOSS_HEIGHT + BASE_THICKNESS),
            adsk.fusion.FeatureOperations.CutFeatureOperation,
            f"{boss_name} Dowel Bore",
        )

    # The single engraving: a two-line credit, left-aligned just inboard of the
    # top-left boss so it stays clear of the boss for any font.
    boss_inner_edge_x = OUTER_PIN_PATTERN_SPAN / 2.0 - BOSS_DIAMETER / 2.0
    title_x_min = -boss_inner_edge_x + LABEL_BOSS_GAP
    engrave_text(
        component,
        wall_plane,
        TITLE_TEXT,
        title_x_min,
        platform_rear - ANNOTATION_MARGIN_Y - TITLE_BOX_HEIGHT,
        TITLE_BOX_WIDTH,
        TITLE_BOX_HEIGHT,
        ANNOTATION_TEXT_HEIGHT,
        ANNOTATION_DEPTH,
        "Designed By - 0.5 mm Engraving",
    )

    # SLA shrink compensation: uniformly scale the whole solid about the origin
    # (the pin-pattern center) so the resin print comes out on nominal dimensions.
    # Skipped at 1.000 so the default output matches the PLA jig exactly.
    if abs(SCALE_FACTOR - 1.0) > 1e-9:
        scale_bodies = adsk.core.ObjectCollection.create()
        for body in component.bRepBodies:
            scale_bodies.add(body)
        scale_input = component.features.scaleFeatures.createInput(
            scale_bodies,
            component.originConstructionPoint,
            adsk.core.ValueInput.createByReal(SCALE_FACTOR),
        )
        component.features.scaleFeatures.add(scale_input)

    for plane in (
        component.xYConstructionPlane,
        wall_plane,
        pickup_top_plane,
        outer_bar_notch_top_plane,
        boss_top_plane,
    ):
        plane.isLightBulbOn = False


def export_design(design, output_directory):
    manager = design.exportManager
    f3d_path = os.path.join(output_directory, "pin_grid_wafer_jig_sla.f3d")
    step_path = os.path.join(output_directory, "pin_grid_wafer_jig_sla.step")
    print_directory = os.path.join(os.path.dirname(output_directory), "print-files")
    os.makedirs(print_directory, exist_ok=True)
    stl_path = os.path.join(print_directory, "pin_grid_wafer_jig_sla.stl")
    if not manager.execute(manager.createFusionArchiveExportOptions(f3d_path)):
        raise RuntimeError("Fusion archive export failed")
    if not manager.execute(manager.createSTEPExportOptions(step_path)):
        raise RuntimeError("STEP export failed")
    stl_options = manager.createSTLExportOptions(design.rootComponent, stl_path)
    stl_options.isBinaryFormat = True
    stl_options.isOneFilePerBody = False
    stl_options.sendToPrintUtility = False
    stl_options.unitType = adsk.fusion.DistanceUnits.MillimeterDistanceUnits
    stl_options.meshRefinement = adsk.fusion.MeshRefinementSettings.MeshRefinementHigh
    if not manager.execute(stl_options):
        raise RuntimeError("STL export failed")
    return f3d_path, step_path, stl_path


def run(_context):
    app = adsk.core.Application.get()
    ui = app.userInterface
    try:
        app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
        design = adsk.fusion.Design.cast(app.activeProduct)
        if not design:
            raise RuntimeError("Could not create a Fusion design")
        design.designType = adsk.fusion.DesignTypes.ParametricDesignType
        build_model(design)
        app.activeViewport.fit()
        output_directory = os.path.dirname(os.path.realpath(__file__))
        f3d_path, step_path, stl_path = export_design(design, output_directory)
        ui.messageBox(
            f"Four-dowel grid wafer jig (SLA) created at scale {SCALE_FACTOR:g}.\n\n"
            f"Fusion archive:\n{f3d_path}\n\n"
            f"STEP file:\n{step_path}\n\n"
            f"High-quality binary STL:\n{stl_path}",
            "Pin Grid Jig Complete",
        )
    except Exception:
        ui.messageBox(traceback.format_exc(), "Pin Grid Jig Error")


def stop(_context):
    pass
