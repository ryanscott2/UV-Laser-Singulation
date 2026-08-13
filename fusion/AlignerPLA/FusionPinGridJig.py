"""Build and export a four-dowel grid-indexed 100 mm wafer jig in Fusion."""

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
# bore straight through the thick base that takes a 3/16 in (4.7625 mm) steel
# dowel. Moving the locating surface to ground steel decouples pin precision and
# wear from the print tolerance: the dowel slip-fits the table's 1/4-20 tapped
# hole (~4.87 mm crest ID) and press-fits the bore. Retain with a drop of epoxy;
# the dowel's far end bears in the table hole, so the bore only has to hold it
# square and captive.
DOWEL_DIAMETER = 4.7625          # 3/16 in ground steel dowel
DOWEL_PROTRUSION = 5.000         # protrusion below the base into the table hole; matches the v2 pins (5 mm)
# The bore runs through the full 12.5 mm base, so ample engagement is available;
# ~8 mm is plenty. Cut each dowel to engagement + 5 mm protrusion (e.g. ~13 mm for
# 8 mm engaged and 5 mm proud below) to match the v2 pins.
# Bore for the dowel. FDM prints small holes undersize (coarser layers come out a
# bit smaller), so this is modeled over the 4.7625 mm dowel and dialed in on a
# printed coupon. 4.85 offsets the undersize; PLA is brittle, so aim for a
# slip/snug fit retained with epoxy rather than a hard press that splits the wall.
DOWEL_HOLE_DIAMETER = 4.850
BOSS_DIAMETER = 20.000            # boss disc: 10 mm radius of material around each dowel hole
ARM_WIDTH = 15.000                # necked arm hub->boss; kept under the boss diameter for looks
FILLET_RADIUS = 2.500             # rounds the outer corners where arms meet the hub/bosses
BOSS_HEIGHT = 0.000              # no raised boss; the thick base gives the engagement and a solid bore wall

# Platform and wafer nest. The base is a "spider" built in build_model -- a hub disc
# over the nest plus four necked arms out to the corner dowel bosses -- not a
# rectangular plate. PLATFORM_NEST_GAP is the radial margin kept beyond the 3 mm nest
# wall when sizing that hub: hub_radius = WAFER_DIAMETER/2 + SIDEWALL_THICKNESS +
# PLATFORM_NEST_GAP.
PLATFORM_NEST_GAP = 1.000
BASE_THICKNESS = 12.500          # thick slab to resist warping and give the dowel bore a solid wall
SIDEWALL_HEIGHT = 2.000          # tall enough to retain a short stack of wafers
SIDEWALL_THICKNESS = 3.000


WAFER_DIAMETER = 100.000
PRIMARY_FLAT_LENGTH = 32.500
SECONDARY_FLAT_LENGTH = 18.000
# Nest datums. The wafer is located by its PRIMARY flat plus ONE hard pin on the
# arc -- not by the secondary flat -- so a single nest fits every SEMI flat type
# (the secondary sits at a different clock angle per type, or is absent) and a wafer
# flipped for back-side work. The operator presses it forward onto the primary-flat
# bar and left onto the pin by hand:
#   - PRIMARY_FLAT (front datum), 0.175 mm: sets Y + rotation.
#   - X_PIN at the 9:30 arc position: sets X. 9:30 (165 deg CCW from +X) is the one
#     window that stays clear of the secondary flat for all types and both faces. It
#     presses to the nominal wafer OD, so X now references the OD -- repeatability
#     tracks OD consistency, not a flat (fine within a wafer batch).
#   - RADIAL (arc) 0.600 mm: the rest of the wall is a loose retainer, held off the
#     wafer so the pin alone takes the X contact.
# NOTE: this replaces the old two-flat datum (v2 fit 0.500 / 0.500 / 0.300) and
# shifts the wafer seat, so it INVALIDATES the current NEST_CALIBRATION -- a manual
# recalibration is required with this print; see CALIBRATION_AND_SLIDING_NEST_NOTES.md.
RADIAL_CLEARANCE = 0.600          # loose arc retainer, opened so the X pin (not the wall) contacts first
PRIMARY_FLAT_CLEARANCE = 0.175    # front datum: Y + rotation
X_PIN_ANGLE_DEG = 165.0           # 9:30 upper-left; clear of every type's secondary flat
X_PIN_DIAMETER = 8.000            # hard X-datum pin; grows outward, inner edge stays at the wafer OD

# Two gaps in the raised lip, 180 degrees apart, so a Kapton tab can run from the
# platform onto the wafer without having to bridge the 2 mm wall. The wafer is
# pushed forward onto the primary flat (and left onto the X pin) and taped down; the
# nest only locates it, it does not retain it. Both cut the raised wall only -- the
# solid base stays continuous under the wafer.
#
# Both are 15 mm. They stay separate constants so either can be tuned alone.
PICKUP_GAP_WIDTH = 15.000
REAR_TAPE_GAP_WIDTH = 15.000

# Maker's name engraved along the top-left arm (the only solid strut with room).
NAME_TEXT = "RYAN SCOTT"
NAME_TEXT_HEIGHT = 3.000
NAME_DEPTH = 0.500

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
    include_secondary_flat: bool = True,
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
    # Primary flat faces table front (-Y); optional secondary flat faces left (-X).
    points = clip_polygon(
        points,
        axis=1,
        threshold=center_y - primary_depth - primary_relief,
        keep_greater=True,
    )
    if include_secondary_flat:
        points = clip_polygon(
            points,
            axis=0,
            threshold=center_x - secondary_depth - secondary_relief,
            keep_greater=True,
        )
    return points


def rectangle_points(x: float, y: float, width: float, height: float):
    return [(x, y), (x + width, y), (x + width, y + height), (x, y + height)]


def oriented_rect(p0, p1, width):
    """A width-wide rectangle centered on the segment from p0 to p1."""
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    length = math.hypot(dx, dy)
    ux, uy = dx / length, dy / length
    px, py = -uy * width / 2.0, ux * width / 2.0
    return [
        (p0[0] + px, p0[1] + py),
        (p1[0] + px, p1[1] + py),
        (p1[0] - px, p1[1] - py),
        (p0[0] - px, p0[1] - py),
    ]


def half_disc(center_x, center_y, radius, facing_rad, segments=32):
    """Semicircle of `radius` about the center, bulging toward `facing_rad`.

    The straight side (chord) is the flat back; the round side is the contact face.
    """
    start = facing_rad - math.pi / 2.0
    return [
        (center_x + radius * math.cos(start + math.pi * i / segments),
         center_y + radius * math.sin(start + math.pi * i / segments))
        for i in range(segments + 1)
    ]


def fillet_outer_vertical_edges(component, radius_mm):
    """Round every vertical (Z-parallel straight) edge of the base body.

    Those are the in-plane outline corners where the arms meet the hub and bosses;
    filleting them removes the sharp outer edges. Degrades gracefully (tries smaller
    radii, then skips) if a radius is too large for a notch.
    """
    if component.bRepBodies.count == 0:
        return
    body = component.bRepBodies.item(0)
    for radius in (radius_mm, radius_mm * 0.6, radius_mm * 0.3):
        edges = adsk.core.ObjectCollection.create()
        for edge in body.edges:
            geometry = edge.geometry
            if geometry.curveType != adsk.core.Curve3DTypes.Line3DCurveType:
                continue
            start, end = geometry.startPoint, geometry.endPoint
            if (abs(start.x - end.x) < 1e-6 and abs(start.y - end.y) < 1e-6
                    and abs(start.z - end.z) > 1e-6):
                edges.add(edge)
        if edges.count == 0:
            return
        try:
            fillet_input = component.features.filletFeatures.createInput()
            fillet_input.addConstantRadiusEdgeSet(
                edges, adsk.core.ValueInput.createByString(f"{radius} mm"), False)
            component.features.filletFeatures.add(fillet_input)
            return
        except Exception:
            continue


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


def engrave_on_path(component, plane, text, p0, p1, height, depth, name):
    """Recess single-line text running along the segment p0->p1 (a maker's mark).

    Uses fit-on-path so the text follows the diagonal arm. Wrapped so a text-API
    hiccup never blocks the build -- if it fails the jig still generates, just
    without the name.
    """
    try:
        sketch = component.sketches.add(plane)
        sketch.name = f"{name} Sketch"
        path_line = sketch.sketchCurves.sketchLines.addByTwoPoints(
            adsk.core.Point3D.create(cm(p0[0]), cm(p0[1]), 0),
            adsk.core.Point3D.create(cm(p1[0]), cm(p1[1]), 0),
        )
        text_input = sketch.sketchTexts.createInput2(text, cm(height))
        text_input.setAsFitOnPath(path_line, True)
        sketch_text = sketch.sketchTexts.add(text_input)
        extrudes = component.features.extrudeFeatures
        feature_input = extrudes.createInput(
            sketch_text, adsk.fusion.FeatureOperations.CutFeatureOperation)
        feature_input.setDistanceExtent(
            False, adsk.core.ValueInput.createByString(f"-{depth} mm"))
        feature = extrudes.add(feature_input)
        feature.name = name
        sketch.isVisible = False
        return feature
    except Exception:
        return None


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


def extrude_polygon(component, plane, points_mm, distance_mm, operation, name):
    return extrude_profile(
        component,
        polygon_sketch(component, plane, points_mm, f"{name} Sketch"),
        distance_mm,
        operation,
        name,
    )


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
    boss_top_plane = offset_plane(
        component,
        BASE_THICKNESS + BOSS_HEIGHT,
        "Dowel Boss Top Plane",
    )

    # --- Spider base: a hub over the wafer nest with necked arms out to the four
    # corner bosses. The base must stay solid under the whole nest (the wafer floor
    # and the 3 mm wall reach the nest radius), so the hub is a disc of that radius
    # plus a small margin; the old rectangular corners are gone and there are no
    # pickup tabs.
    half_span = OUTER_PIN_PATTERN_SPAN / 2.0
    boss_centers = [(sx * half_span, sy * half_span) for sx in (-1.0, 1.0) for sy in (-1.0, 1.0)]
    hub_radius = WAFER_DIAMETER / 2.0 + SIDEWALL_THICKNESS + PLATFORM_NEST_GAP

    for name, value, comment in (
        ("gridPitch", GRID_PITCH, "Table hole-grid pitch"),
        ("indexMove", INDEX_MOVE, "Two-grid-space indexing move"),
        ("outerPinPatternSpan", OUTER_PIN_PATTERN_SPAN, "Four-space outer pin span"),
        ("dowelDiameter", DOWEL_DIAMETER, "3/16 in steel locating dowel diameter"),
        ("dowelHoleDiameter", DOWEL_HOLE_DIAMETER, "Press-fit bore for the dowel"),
        ("bossDiameter", BOSS_DIAMETER, "Boss disc diameter (10 mm radius) around each dowel"),
        ("armWidth", ARM_WIDTH, "Necked arm width, hub to boss"),
        ("hubRadius", hub_radius, "Nest hub radius"),
        ("filletRadius", FILLET_RADIUS, "Outer-corner fillet radius"),
        ("baseThickness", BASE_THICKNESS, "Wafer platform thickness"),
        ("sidewallHeight", SIDEWALL_HEIGHT, "Nest lip height above platform"),
        ("nestOffsetX", NEST_OFFSET_FROM_PIN_CENTER_X, "Nest X from pin-square center"),
        ("nestOffsetY", NEST_OFFSET_FROM_PIN_CENTER_Y, "Nest Y from pin-square center"),
        ("pickupGapWidth", PICKUP_GAP_WIDTH, "Primary-flat pickup opening"),
        ("rearTapeGapWidth", REAR_TAPE_GAP_WIDTH, "Rear tape-access gap in the lip"),
    ):
        add_parameter(design, name, value, comment)

    # Hub disc that carries the wafer nest.
    extrude_profile(
        component,
        circle_sketch(component, xy_plane, NEST_CENTER_X, NEST_CENTER_Y, 2.0 * hub_radius, "Nest Hub Sketch"),
        BASE_THICKNESS,
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation,
        "Nest Hub",
    )
    # A necked arm out to each corner boss, then the boss disc around each dowel bore.
    for index, (boss_x, boss_y) in enumerate(boss_centers):
        extrude_polygon(
            component,
            xy_plane,
            oriented_rect((NEST_CENTER_X, NEST_CENTER_Y), (boss_x, boss_y), ARM_WIDTH),
            BASE_THICKNESS,
            adsk.fusion.FeatureOperations.JoinFeatureOperation,
            f"Boss Arm {index + 1}",
        )
        extrude_profile(
            component,
            circle_sketch(component, xy_plane, boss_x, boss_y, BOSS_DIAMETER, f"Boss {index + 1} Sketch"),
            BASE_THICKNESS,
            adsk.fusion.FeatureOperations.JoinFeatureOperation,
            f"Boss {index + 1}",
        )
    # Round the outer corners where the arms meet the hub and bosses -- no sharp edges.
    fillet_outer_vertical_edges(component, FILLET_RADIUS)

    # Raised nest wall: a plain arc plus the primary-flat bar (no secondary-flat
    # datum). The pocket cut below leaves the wall ring; the X pin is added after.
    outer = wafer_polygon(
        NEST_CENTER_X,
        NEST_CENTER_Y,
        radial_offset=SIDEWALL_THICKNESS,
        primary_relief=SIDEWALL_THICKNESS,
        include_secondary_flat=False,
    )
    extrude_polygon(
        component,
        wall_plane,
        outer,
        SIDEWALL_HEIGHT,
        adsk.fusion.FeatureOperations.JoinFeatureOperation,
        "2 mm Raised Wafer Nest",
    )

    pocket = wafer_polygon(
        NEST_CENTER_X,
        NEST_CENTER_Y,
        radial_offset=RADIAL_CLEARANCE,
        primary_relief=PRIMARY_FLAT_CLEARANCE,
        include_secondary_flat=False,
    )
    extrude_polygon(
        component,
        wall_plane,
        pocket,
        SIDEWALL_HEIGHT + 0.1,
        adsk.fusion.FeatureOperations.CutFeatureOperation,
        "Final Wafer Pocket Clearance",
    )

    # Hard X-datum pin at the 9:30 arc position (upper-left). The primary flat sets
    # Y + rotation; pressing the wafer left onto this pin sets X. 9:30 is the one arc
    # window clear of the secondary flat for every SEMI type and when the wafer is
    # flipped for back-side. Built after the pocket cut so it stands proud into the
    # cavity and stops the wafer at its nominal OD.
    x_pin_angle = math.radians(X_PIN_ANGLE_DEG)
    x_pin_center_r = WAFER_DIAMETER / 2.0 + X_PIN_DIAMETER / 2.0
    x_pin_cx = NEST_CENTER_X + x_pin_center_r * math.cos(x_pin_angle)
    x_pin_cy = NEST_CENTER_Y + x_pin_center_r * math.sin(x_pin_angle)
    # Only the inner half of the pin (the half facing the wafer): its flat back sits at
    # the hub edge so nothing overhangs the plate, and the round face contacts the OD.
    extrude_polygon(
        component,
        wall_plane,
        half_disc(x_pin_cx, x_pin_cy, X_PIN_DIAMETER / 2.0, x_pin_angle + math.pi),
        SIDEWALL_HEIGHT,
        adsk.fusion.FeatureOperations.JoinFeatureOperation,
        f"X Datum Pin ({X_PIN_ANGLE_DEG:g} deg / 9:30, hub-flush)",
    )

    # Beveled 15 mm pickup opening through the raised primary-flat wall only.
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

    # A press-fit through-bore at each corner of the 4 x 4 grid-space square for a
    # 3/16 in steel dowel, straight through the solid base. No raised boss: the
    # thick base gives the full engagement and a solid wall, so pressing a pin in
    # cannot split a thin stub. Setting BOSS_HEIGHT > 0 re-enables a raised boss --
    # it is joined on first and the bore then runs through boss + base.
    outer_half_span = OUTER_PIN_PATTERN_SPAN / 2.0
    dowel_locations = (
        ("Outer Front Left", -outer_half_span, -outer_half_span),
        ("Outer Front Right", +outer_half_span, -outer_half_span),
        ("Outer Rear Left", -outer_half_span, +outer_half_span),
        ("Outer Rear Right", +outer_half_span, +outer_half_span),
    )
    for boss_name, x, y in dowel_locations:
        if BOSS_HEIGHT > 0:
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

    # Maker's name engraved along the top-left arm, running from just past the hub
    # out toward the boss so it reads along the strut.
    _name_dir = math.atan2(half_span - NEST_CENTER_Y, -half_span - NEST_CENTER_X)
    engrave_on_path(
        component,
        wall_plane,
        NAME_TEXT,
        (NEST_CENTER_X + 56.0 * math.cos(_name_dir), NEST_CENTER_Y + 56.0 * math.sin(_name_dir)),
        (NEST_CENTER_X + 76.0 * math.cos(_name_dir), NEST_CENTER_Y + 76.0 * math.sin(_name_dir)),
        NAME_TEXT_HEIGHT,
        NAME_DEPTH,
        "Maker Name - Top-Left Arm",
    )

    for plane in (
        component.xYConstructionPlane,
        wall_plane,
        pickup_top_plane,
        boss_top_plane,
    ):
        plane.isLightBulbOn = False


def export_design(design, output_directory):
    manager = design.exportManager
    f3d_path = os.path.join(output_directory, "pin_grid_wafer_jig.f3d")
    step_path = os.path.join(output_directory, "pin_grid_wafer_jig.step")
    print_directory = os.path.join(os.path.dirname(output_directory), "print-files")
    os.makedirs(print_directory, exist_ok=True)
    stl_path = os.path.join(print_directory, "pin_grid_wafer_jig.stl")
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
            "Four-dowel grid wafer jig created.\n\n"
            f"Fusion archive:\n{f3d_path}\n\n"
            f"STEP file:\n{step_path}\n\n"
            f"High-quality binary STL:\n{stl_path}",
            "Pin Grid Jig Complete",
        )
    except Exception:
        ui.messageBox(traceback.format_exc(), "Pin Grid Jig Error")


def stop(_context):
    pass
