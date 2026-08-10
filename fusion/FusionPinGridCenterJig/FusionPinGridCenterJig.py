"""Build and export a four-pin center-field 100 mm wafer jig in Fusion."""

from __future__ import annotations

import math
import os
import traceback

import adsk.core
import adsk.fusion


# =============================================================================
# USER-EDITABLE DIMENSIONS (millimeters)
# =============================================================================

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
NEST_CENTER_X = NEST_OFFSET_FROM_PIN_CENTER_X
NEST_CENTER_Y = NEST_OFFSET_FROM_PIN_CENTER_Y

# Center-field placement: the common pattern center is grid column 3, row 4.
CENTER_GRID_COLUMN = 3
CENTER_GRID_ROW = 4
CENTER_PATTERN_X = FIRST_HOLE_EDGE_OFFSET + CENTER_GRID_COLUMN * GRID_PITCH
CENTER_PATTERN_Y = FIRST_HOLE_EDGE_OFFSET + CENTER_GRID_ROW * GRID_PITCH
CENTER_WAFER_X = CENTER_PATTERN_X + NEST_CENTER_X
CENTER_WAFER_Y = CENTER_PATTERN_Y + NEST_CENTER_Y

# Four downward locating pins on the corners of a 4 x 4 grid-space square. The
# inner 2 x 2 set was removed: the outer square alone fixes position and rotation,
# and fewer pins means fewer holes to line up when seating the plate.
PIN_DIAMETER = 4.650
PIN_ENGAGEMENT = 5.000
PIN_TIP_DIAMETER = 4.000
PIN_TIP_TAPER = 1.000

# Compact platform and wafer nest.
PLATFORM_SIZE_X = 128.000
PLATFORM_SIZE_Y = 128.000
BASE_THICKNESS = 2.000
OUTER_BAR_WIDTH = 4.000
OUTER_BAR_HEIGHT = 4.000
SIDEWALL_HEIGHT = 1.500
SIDEWALL_THICKNESS = 3.000

# Small pickup tabs centered on the left and right edges, so the plate can be
# lifted straight off the pins without prying at the wafer or the nest wall. They
# start at the top of the 2 mm platform, leaving a 2 mm undercut to hook under.
SIDE_TAB_PROTRUSION = 10.000
SIDE_TAB_LENGTH = 24.000

WAFER_DIAMETER = 100.000
PRIMARY_FLAT_LENGTH = 32.500
SECONDARY_FLAT_LENGTH = 18.000
RADIAL_CLEARANCE = 0.500
PRIMARY_FLAT_CLEARANCE = 0.500
SECONDARY_DATUM_CLEARANCE = 0.300

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

# Three separate engravings cut into the platform floor, laid out exactly like
# the four-position plate, which shares this one's platform size, nest offset and
# margins.
#
# Top-left gives the single hole for this station: the alignment pin, which is the
# outer front-right pin of the pattern. The four-pin pattern is rigid, so that
# one hole fixes the other three; it sits two grid spaces right of and two forward
# of the pin-pattern center.
#
# Text height drops from 2.5 mm to match the four-position plate, because the
# heading is now long and the top-left corner narrows as it goes down, where the
# wafer-pocket wall curves in.
ANNOTATION_DEPTH = 0.500
ANNOTATION_TEXT_HEIGHT = 2.000
ANNOTATION_MARGIN_X = 5.000
ANNOTATION_MARGIN_Y = 5.000
ANNOTATION_BOX_WIDTH = 62.000
ANNOTATION_BOX_HEIGHT = 10.000
ANNOTATION_TEXT = (
    "CENTER FIELD ALIGNER\n"
    "C5 R2"
)

# Front-edge labels: the grid convention at front-left, and the alignment pin
# named at front-right, which is the corner its outer pin sits nearest. Both live
# in the clear band forward of the wafer pocket and outboard of the centered
# pickup notch, which keeps about 5 mm to the pocket wall.
FRONT_LABEL_MARGIN = 5.000
FRONT_LABEL_BOX_WIDTH = 34.000
FRONT_LABEL_BOX_HEIGHT = 6.000
ORIENTATION_TEXT = "C0=LEFT R0=FRONT"
ALIGNMENT_PIN_TEXT = "ALIGNMENT PIN"

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


def engrave_text(component, plane, text, x_min, y_min, width, height, text_height, depth, name):
    """Cut multiline sketch text downward from the platform's top face."""
    sketch = component.sketches.add(plane)
    sketch.name = f"{name} Sketch"
    text_input = sketch.sketchTexts.createInput2(text, cm(text_height))
    placed = text_input.setAsMultiLine(
        adsk.core.Point3D.create(cm(x_min), cm(y_min), 0),
        adsk.core.Point3D.create(cm(x_min + width), cm(y_min + height), 0),
        adsk.core.HorizontalAlignments.LeftHorizontalAlignment,
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
        adsk.fusion.FeatureOperations.CutFeatureOperation,
    )
    feature_input.setDistanceExtent(
        False,
        adsk.core.ValueInput.createByString(f"-{depth} mm"),
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
    # With a 4 mm rim around a 128 mm platform, the annular profile has the
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
    wall_plane = offset_plane(component, BASE_THICKNESS, "Top of 2 mm Wafer Platform")
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
    pin_tip_plane = offset_plane(component, -PIN_ENGAGEMENT, "Pin Tip Plane")
    pin_shoulder_plane = offset_plane(
        component,
        -PIN_ENGAGEMENT + PIN_TIP_TAPER,
        "Pin Full-Diameter Shoulder Plane",
    )

    for name, value, comment in (
        ("gridPitch", GRID_PITCH, "Table hole-grid pitch"),
        ("indexMove", INDEX_MOVE, "Two-grid-space indexing move"),
        ("outerPinPatternSpan", OUTER_PIN_PATTERN_SPAN, "Four-space outer pin span"),
        ("pinDiameter", PIN_DIAMETER, "Printed locating pin diameter"),
        ("pinEngagement", PIN_ENGAGEMENT, "Pin length below platform"),
        ("platformSizeX", PLATFORM_SIZE_X, "Compact platform width"),
        ("platformSizeY", PLATFORM_SIZE_Y, "Compact platform depth"),
        ("baseThickness", BASE_THICKNESS, "Wafer platform thickness"),
        ("outerBarWidth", OUTER_BAR_WIDTH, "Perimeter reinforcement width"),
        ("outerBarHeight", OUTER_BAR_HEIGHT, "Perimeter reinforcement height"),
        ("sidewallHeight", SIDEWALL_HEIGHT, "Nest lip height above platform"),
        ("nestOffsetX", NEST_OFFSET_FROM_PIN_CENTER_X, "Nest X from pin-square center"),
        ("nestOffsetY", NEST_OFFSET_FROM_PIN_CENTER_Y, "Nest Y from pin-square center"),
        ("centerPatternX", CENTER_PATTERN_X, "Center placement pin-pattern X"),
        ("centerPatternY", CENTER_PATTERN_Y, "Center placement pin-pattern Y"),
        ("centerWaferX", CENTER_WAFER_X, "Centered wafer X on table"),
        ("centerWaferY", CENTER_WAFER_Y, "Centered wafer Y on table"),
        ("pickupGapWidth", PICKUP_GAP_WIDTH, "Primary-flat pickup opening"),
        ("rearTapeGapWidth", REAR_TAPE_GAP_WIDTH, "Rear tape-access gap in the lip"),
        ("annotationDepth", ANNOTATION_DEPTH, "Baseplate text engraving depth"),
        ("annotationTextHeight", ANNOTATION_TEXT_HEIGHT, "Baseplate text height"),
    ):
        add_parameter(design, name, value, comment)

    # A full 2 mm square platform supports the wafer and all eight pin roots.
    platform = rectangle_points(
        NEST_CENTER_X - PLATFORM_SIZE_X / 2.0,
        NEST_CENTER_Y - PLATFORM_SIZE_Y / 2.0,
        PLATFORM_SIZE_X,
        PLATFORM_SIZE_Y,
    )
    extrude_polygon(
        component,
        xy_plane,
        platform,
        BASE_THICKNESS,
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation,
        "128 mm Square Wafer Platform",
    )

    # Continuous 4 x 4 mm perimeter reinforcement above the 2 mm platform.
    inner_platform = rectangle_points(
        NEST_CENTER_X - PLATFORM_SIZE_X / 2.0 + OUTER_BAR_WIDTH,
        NEST_CENTER_Y - PLATFORM_SIZE_Y / 2.0 + OUTER_BAR_WIDTH,
        PLATFORM_SIZE_X - 2.0 * OUTER_BAR_WIDTH,
        PLATFORM_SIZE_Y - 2.0 * OUTER_BAR_WIDTH,
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
    # from the top of the 2 mm platform rather than from the table, so each tab
    # is cantilevered with a 2 mm gap underneath: that undercut is what a
    # fingernail or tweezer tip hooks into to lift the plate straight off its
    # pins, instead of prying against the wafer or the nest wall.
    platform_left_x = NEST_CENTER_X - PLATFORM_SIZE_X / 2.0
    platform_right_x = NEST_CENTER_X + PLATFORM_SIZE_X / 2.0
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
    # a 45 degree flare through the full 4 mm perimeter bar. The 2 mm platform
    # remains continuous.
    platform_front_y = NEST_CENTER_Y - PLATFORM_SIZE_Y / 2.0
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
    # reach the wafer edge from outside the plate. The 2 mm platform is untouched.
    platform_rear_y = NEST_CENTER_Y + PLATFORM_SIZE_Y / 2.0
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

    # Four 4.65 mm pins on the corners of the 4 x 4 grid-space square. The full
    # diameter continues through the 2 mm platform for maximum root strength.
    outer_half_span = OUTER_PIN_PATTERN_SPAN / 2.0
    pin_locations = (
        ("Outer Front Left", -outer_half_span, -outer_half_span),
        ("Outer Front Right", +outer_half_span, -outer_half_span),
        ("Outer Rear Left", -outer_half_span, +outer_half_span),
        ("Outer Rear Right", +outer_half_span, +outer_half_span),
    )
    cylinder_height = PIN_ENGAGEMENT - PIN_TIP_TAPER + BASE_THICKNESS
    for pin_name, x, y in pin_locations:
        cylinder = circle_sketch(
            component,
            pin_shoulder_plane,
            x,
            y,
            PIN_DIAMETER,
            f"{pin_name} Pin Cylinder Sketch",
        )
        extrude_profile(
            component,
            cylinder,
            cylinder_height,
            adsk.fusion.FeatureOperations.JoinFeatureOperation,
            f"{pin_name} 4.65 mm Pin",
        )
        loft_circles(
            component,
            pin_tip_plane,
            (x, y),
            PIN_TIP_DIAMETER,
            pin_shoulder_plane,
            (x, y),
            PIN_DIAMETER,
            adsk.fusion.FeatureOperations.JoinFeatureOperation,
            f"{pin_name} Tapered Tip",
        )

    platform_left = NEST_CENTER_X - PLATFORM_SIZE_X / 2.0
    platform_right = NEST_CENTER_X + PLATFORM_SIZE_X / 2.0
    platform_rear = NEST_CENTER_Y + PLATFORM_SIZE_Y / 2.0
    platform_front = NEST_CENTER_Y - PLATFORM_SIZE_Y / 2.0
    engrave_text(
        component,
        wall_plane,
        ANNOTATION_TEXT,
        platform_left + ANNOTATION_MARGIN_X,
        platform_rear - ANNOTATION_MARGIN_Y - ANNOTATION_BOX_HEIGHT,
        ANNOTATION_BOX_WIDTH,
        ANNOTATION_BOX_HEIGHT,
        ANNOTATION_TEXT_HEIGHT,
        ANNOTATION_DEPTH,
        "CENTER Position Map - 0.5 mm Engraving",
    )
    engrave_text(
        component,
        wall_plane,
        ORIENTATION_TEXT,
        platform_left + FRONT_LABEL_MARGIN,
        platform_front + FRONT_LABEL_MARGIN,
        FRONT_LABEL_BOX_WIDTH,
        FRONT_LABEL_BOX_HEIGHT,
        ANNOTATION_TEXT_HEIGHT,
        ANNOTATION_DEPTH,
        "Grid Orientation Label - 0.5 mm Engraving",
    )
    engrave_text(
        component,
        wall_plane,
        ALIGNMENT_PIN_TEXT,
        platform_right - FRONT_LABEL_MARGIN - FRONT_LABEL_BOX_WIDTH,
        platform_front + FRONT_LABEL_MARGIN,
        FRONT_LABEL_BOX_WIDTH,
        FRONT_LABEL_BOX_HEIGHT,
        ANNOTATION_TEXT_HEIGHT,
        ANNOTATION_DEPTH,
        "Alignment Pin Label - 0.5 mm Engraving",
    )

    for plane in (
        component.xYConstructionPlane,
        wall_plane,
        pickup_top_plane,
        outer_bar_notch_top_plane,
        pin_tip_plane,
        pin_shoulder_plane,
    ):
        plane.isLightBulbOn = False


def export_design(design, output_directory):
    manager = design.exportManager
    f3d_path = os.path.join(output_directory, "pin_grid_center_wafer_jig.f3d")
    step_path = os.path.join(output_directory, "pin_grid_center_wafer_jig.step")
    print_directory = os.path.join(os.path.dirname(output_directory), "print-files")
    os.makedirs(print_directory, exist_ok=True)
    stl_path = os.path.join(print_directory, "pin_grid_center_wafer_jig.stl")
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
            "Eight-pin center-field wafer jig created.\n\n"
            f"Fusion archive:\n{f3d_path}\n\n"
            f"STEP file:\n{step_path}\n\n"
            f"High-quality binary STL:\n{stl_path}",
            "Pin Grid Center Jig Complete",
        )
    except Exception:
        ui.messageBox(traceback.format_exc(), "Pin Grid Center Jig Error")


def stop(_context):
    pass
