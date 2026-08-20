"""Edge-datum PLA wafer jig -- wafer centered on the laser field.

The stage indexes the wafer under a fixed field, so this jig no longer seats on the
grid. It is located by an L against the table's FRONT-LEFT corner:

  * Datum origin = table front-left corner (left edge = X 0, front edge = Y 0).
  * A LEFT-edge datum bar (X + yaw) and a FRONT-edge datum foot (Y). Only small NUBS on
    the downstands touch the table -- two on the left, one on the front = a 3-point
    exact-constraint seat; the rest of each lip is held clear so it cannot rock.
  * THREE arms carry those two datums to the nest hub (two arms to the left bar, one
    to the front foot).
  * Preload = a rubber band from the press-fit anchor rod on the plate to a pin in a table hole
    up-and-right of the nest; its tension pulls the plate up/right, seating both edges.
  * A rear Kapton-tape tab (spider-arm width) off the back of the hub, at the rear tape
    gap, gives a flat pad to anchor the wafer hold-down tape.

Wafer sits on the FIELD center: table (92.45, 110.09), measured from the datum
corner (confirmed 2026-08-14; supersedes the 101.78/127.80 that was logged in
laser-pc/optiscan_positions.json -- reconcile that file). Slicer GLOBAL offset stays 0.

Nest (hub, 2 mm wall, primary-flat + 9:30 X-pin datum, pickup / rear tape gaps) and the
bore style are copied verbatim from FusionPinGridJig.py.
"""

from __future__ import annotations

import math
import os
import traceback

import adsk.core
import adsk.fusion


# =============================================================================
# USER-EDITABLE DIMENSIONS (millimeters). Origin = table front-left corner.
# =============================================================================

# Wafer nest center = laser field center in table coords (from the 08-14 stage cal).
NEST_CENTER_X = 92.450
NEST_CENTER_Y = 110.090

# Nest + base (copied from FusionPinGridJig.py so the nest is identical).
BASE_THICKNESS = 8.000
SIDEWALL_HEIGHT = 2.000
SIDEWALL_THICKNESS = 3.000
PLATFORM_NEST_GAP = 1.000
WAFER_DIAMETER = 100.000
PRIMARY_FLAT_LENGTH = 32.500
SECONDARY_FLAT_LENGTH = 18.000
RADIAL_CLEARANCE = 0.600
PRIMARY_FLAT_CLEARANCE = 0.175
X_PIN_ANGLE_DEG = 165.0
X_PIN_DIAMETER = 8.000
PICKUP_GAP_WIDTH = 15.000
REAR_TAPE_GAP_WIDTH = 15.000
# Kapton-tape landing tab off the REAR of the hub (opposite the primary/major flat, at
# the rear tape gap). Its width is the spider-arm width (ARM_WIDTH); it sticks this far
# past the hub edge to give a flat pad at wafer-seat level for anchoring the hold-down
# tape that reaches through the rear gap onto the wafer.
REAR_TAB_PROTRUSION = 10.000

# Spider arms + fillets (a touch wider than the pin-grid jig for the longer reach).
ARM_WIDTH = 18.000
FILLET_RADIUS = 2.500

# Edge datums. The base laps LIP_OVERHANG past each table edge and a downstand LIP_DROP
# deep drops below the base to carry the nubs. LIP_OVERHANG doubles as the nub BACKPLATE
# thickness -- the wall directly behind each nub -- so keep it >= 10 mm for stiffness.
LIP_OVERHANG = 10.000
LIP_DROP = 6.000
DATUM_BAR_WIDTH = 8.000        # left datum bar reach inboard from the left edge
LEFT_BAR_Y0 = 48.000          # left bar runs from here ...
LEFT_BAR_Y1 = 172.000         # ... to here (structure/stiffener; the nubs set the baseline)
FRONT_FOOT_X0 = 83.000        # front datum foot spans this X range ...
FRONT_FOOT_X1 = 101.000       # ... (18 mm wide, centered ~under the new nest X)
FRONT_FOOT_DEPTH = 14.000     # how far the front foot reaches inboard from the front edge

# Only small nubs touch the table (not the whole bar): point-ish contacts seat far more
# repeatably than a full face rocking on two rough surfaces (cosmetic table skin vs FDM
# PLA). The lip is held NUB_CLEARANCE clear; nubs stand proud to the edge (X 0 / Y 0).
NUB_CLEARANCE = 0.400
NUB_LEN = 5.000
LEFT_NUB_Y = (58.000, 162.000)   # two left-edge nubs, ~104 mm apart for a stiff yaw baseline
FRONT_NUB_X = 92.000             # one front-edge nub, under the nest

# Rubber-band anchor: a short stub arm + boss + bore up-and-right of the nest, holding a
# PRESS-FIT 3/16 in steel rod that the band loops over; the band to the table pin pulls
# the plate up/right into the corner datums. Bore matches the pin-grid PLA jig's dowel
# bore (4.850 mm over the 4.7625 mm rod): FDM prints small holes undersize, so this gives
# a snug press/slip fit retained with epoxy rather than a hard press that splits the wall.
ANCHOR_X = 140.000
ANCHOR_Y = 152.000
ANCHOR_ARM_WIDTH = 12.000
ANCHOR_BOSS_DIAMETER = 14.000
ANCHOR_ROD_DIAMETER = 4.7625       # 3/16 in ground steel anchor rod
ANCHOR_ROD_BORE_DIAMETER = 4.850   # press-fit bore, matches FusionPinGridJig.py DOWEL_HOLE_DIAMETER
ANCHOR_ROD_PROTRUSION = 15.000     # rod stands 1.5 cm proud; cut it to base thickness + this

# Maker's mark.
NAME_TEXT = "RYAN SCOTT"
NAME_TEXT_HEIGHT = 4.000
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
    """Semicircle of `radius` about the center, bulging toward `facing_rad`."""
    start = facing_rad - math.pi / 2.0
    return [
        (center_x + radius * math.cos(start + math.pi * i / segments),
         center_y + radius * math.sin(start + math.pi * i / segments))
        for i in range(segments + 1)
    ]


def fillet_outer_vertical_edges(component, radius_mm):
    """Round every vertical (Z-parallel straight) edge of the base body -- the in-plane
    outline corners where arms meet the hub, bar, feet and bosses."""
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
    """Recess single-line text along p0->p1. Wrapped so a text-API hiccup never blocks
    the build -- if it fails the jig still generates, just without the name."""
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

    hub_radius = WAFER_DIAMETER / 2.0 + SIDEWALL_THICKNESS + PLATFORM_NEST_GAP

    for name, value, comment in (
        ("nestCenterX", NEST_CENTER_X, "Wafer/field center X from the datum corner"),
        ("nestCenterY", NEST_CENTER_Y, "Wafer/field center Y from the datum corner"),
        ("hubRadius", hub_radius, "Nest hub radius"),
        ("armWidth", ARM_WIDTH, "Spider arm width"),
        ("baseThickness", BASE_THICKNESS, "Wafer platform thickness"),
        ("sidewallHeight", SIDEWALL_HEIGHT, "Nest lip height above platform"),
        ("lipOverhang", LIP_OVERHANG, "Base lap past each table edge"),
        ("lipDrop", LIP_DROP, "Datum downstand depth below the base"),
        ("anchorRodDiameter", ANCHOR_ROD_DIAMETER, "3/16 in steel anchor rod diameter"),
        ("anchorRodBoreDiameter", ANCHOR_ROD_BORE_DIAMETER, "Press-fit anchor-rod bore"),
        ("anchorRodProtrusion", ANCHOR_ROD_PROTRUSION, "Anchor rod stand-proud height"),
        ("rearTabProtrusion", REAR_TAB_PROTRUSION, "Rear Kapton-tape tab reach past hub edge"),
    ):
        add_parameter(design, name, value, comment)

    # --- Nest hub disc.
    extrude_profile(
        component,
        circle_sketch(component, xy_plane, NEST_CENTER_X, NEST_CENTER_Y, 2.0 * hub_radius, "Nest Hub Sketch"),
        BASE_THICKNESS,
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation,
        "Nest Hub",
    )

    # --- Three arms from the nest hub out toward the datums (two toward the left bar,
    # one toward the front foot). Built first so each overlaps and joins the hub at its
    # inner end; the bar and foot are added next and overlap the arm outer ends.
    arm_targets = (
        ("Left Arm Rear", (DATUM_BAR_WIDTH * 0.5, LEFT_BAR_Y1 - 12.0)),
        ("Left Arm Front", (DATUM_BAR_WIDTH * 0.5, LEFT_BAR_Y0 + 12.0)),
        ("Front Arm", ((FRONT_FOOT_X0 + FRONT_FOOT_X1) / 2.0, FRONT_FOOT_DEPTH * 0.5)),
    )
    for arm_name, target in arm_targets:
        extrude_polygon(
            component,
            xy_plane,
            oriented_rect((NEST_CENTER_X, NEST_CENTER_Y), target, ARM_WIDTH),
            BASE_THICKNESS,
            adsk.fusion.FeatureOperations.JoinFeatureOperation,
            arm_name,
        )

    # --- Edge datums (base level). Left bar laps LIP_OVERHANG past the left edge (X 0);
    # front foot laps past the front edge (Y 0). Each overlaps its arm end(s) and joins.
    extrude_polygon(
        component,
        xy_plane,
        rectangle_points(-LIP_OVERHANG, LEFT_BAR_Y0, DATUM_BAR_WIDTH + LIP_OVERHANG, LEFT_BAR_Y1 - LEFT_BAR_Y0),
        BASE_THICKNESS,
        adsk.fusion.FeatureOperations.JoinFeatureOperation,
        "Left Datum Bar (X + yaw)",
    )
    extrude_polygon(
        component,
        xy_plane,
        rectangle_points(FRONT_FOOT_X0, -LIP_OVERHANG, FRONT_FOOT_X1 - FRONT_FOOT_X0, FRONT_FOOT_DEPTH + LIP_OVERHANG),
        BASE_THICKNESS,
        adsk.fusion.FeatureOperations.JoinFeatureOperation,
        "Front Datum Foot (Y)",
    )

    # --- Rubber-band anchor: stub arm + boss, up/right of the nest.
    extrude_polygon(
        component,
        xy_plane,
        oriented_rect((NEST_CENTER_X, NEST_CENTER_Y), (ANCHOR_X, ANCHOR_Y), ANCHOR_ARM_WIDTH),
        BASE_THICKNESS,
        adsk.fusion.FeatureOperations.JoinFeatureOperation,
        "Rubber-Band Anchor Arm",
    )
    extrude_profile(
        component,
        circle_sketch(component, xy_plane, ANCHOR_X, ANCHOR_Y, ANCHOR_BOSS_DIAMETER, "RB Anchor Boss Sketch"),
        BASE_THICKNESS,
        adsk.fusion.FeatureOperations.JoinFeatureOperation,
        "Rubber-Band Anchor Boss",
    )

    # --- Rear Kapton-tape tab: a small base-level tongue off the rear of the hub, at the
    # rear tape gap (opposite the primary/major flat, which is at the front). Same width
    # as the spider arms (ARM_WIDTH); its top sits at wafer-seat level so hold-down tape
    # can stick to it and reach through the rear gap onto the wafer. Overlaps the hub so
    # it joins solidly and sticks REAR_TAB_PROTRUSION past the hub edge. Added before the
    # corner fillet so its outer corners round like the rest of the outline.
    rear_tab_inner_y = NEST_CENTER_Y + hub_radius - 6.0
    rear_tab_outer_y = NEST_CENTER_Y + hub_radius + REAR_TAB_PROTRUSION
    extrude_polygon(
        component,
        xy_plane,
        rectangle_points(
            NEST_CENTER_X - ARM_WIDTH / 2.0,
            rear_tab_inner_y,
            ARM_WIDTH,
            rear_tab_outer_y - rear_tab_inner_y,
        ),
        BASE_THICKNESS,
        adsk.fusion.FeatureOperations.JoinFeatureOperation,
        "Rear Kapton-Tape Tab",
    )

    # Round the in-plane outline corners.
    fillet_outer_vertical_edges(component, FILLET_RADIUS)

    # ============================ NEST (verbatim) ============================
    # Raised nest wall: plain arc + primary-flat bar (no secondary-flat datum).
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

    # Hard X-datum pin at the 9:30 arc position (upper-left).
    x_pin_angle = math.radians(X_PIN_ANGLE_DEG)
    x_pin_center_r = WAFER_DIAMETER / 2.0 + X_PIN_DIAMETER / 2.0
    x_pin_cx = NEST_CENTER_X + x_pin_center_r * math.cos(x_pin_angle)
    x_pin_cy = NEST_CENTER_Y + x_pin_center_r * math.sin(x_pin_angle)
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

    # Matching rear tape gap opposite the primary flat.
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
    # ========================== end NEST (verbatim) ==========================

    # --- Datum downstands. The lip drops below the base at each edge lap but is held
    # NUB_CLEARANCE clear of the table face; only small nubs stand proud to the edge and
    # actually touch -- two on the left (X + yaw), one on the front (Y) -- a repeatable
    # 3-point seat instead of a full face rocking on two rough surfaces. Extruded DOWN
    # from the base bottom (xy_plane) and joined.
    extrude_polygon(
        component,
        xy_plane,
        rectangle_points(-LIP_OVERHANG, LEFT_BAR_Y0, LIP_OVERHANG - NUB_CLEARANCE, LEFT_BAR_Y1 - LEFT_BAR_Y0),
        -LIP_DROP,
        adsk.fusion.FeatureOperations.JoinFeatureOperation,
        "Left Datum Lip (recessed clear of X 0)",
    )
    for nub_index, nub_y in enumerate(LEFT_NUB_Y):
        extrude_polygon(
            component,
            xy_plane,
            rectangle_points(-NUB_CLEARANCE, nub_y - NUB_LEN / 2.0, NUB_CLEARANCE, NUB_LEN),
            -LIP_DROP,
            adsk.fusion.FeatureOperations.JoinFeatureOperation,
            f"Left Datum Nub {nub_index + 1} (touches X 0)",
        )
    extrude_polygon(
        component,
        xy_plane,
        rectangle_points(FRONT_FOOT_X0, -LIP_OVERHANG, FRONT_FOOT_X1 - FRONT_FOOT_X0, LIP_OVERHANG - NUB_CLEARANCE),
        -LIP_DROP,
        adsk.fusion.FeatureOperations.JoinFeatureOperation,
        "Front Datum Lip (recessed clear of Y 0)",
    )
    extrude_polygon(
        component,
        xy_plane,
        rectangle_points(FRONT_NUB_X - NUB_LEN / 2.0, -NUB_CLEARANCE, NUB_LEN, NUB_CLEARANCE),
        -LIP_DROP,
        adsk.fusion.FeatureOperations.JoinFeatureOperation,
        "Front Datum Nub (touches Y 0)",
    )

    # --- Rubber-band anchor ROD BORE through the anchor boss: a press-fit bore for a
    # 3/16 in steel rod (the rod stands ANCHOR_ROD_PROTRUSION proud; not modeled, same as
    # the dowels in FusionPinGridJig.py). Bore is 4.850 mm over the 4.7625 mm rod so the
    # FDM print lands on a snug press/slip fit; retain with epoxy. Cut straight down
    # through the full base from the top plane, same method as the dowel bores.
    extrude_profile(
        component,
        circle_sketch(component, wall_plane, ANCHOR_X, ANCHOR_Y, ANCHOR_ROD_BORE_DIAMETER, "RB Anchor Rod Bore Sketch"),
        -BASE_THICKNESS,
        adsk.fusion.FeatureOperations.CutFeatureOperation,
        "Rubber-Band Anchor Rod Bore (3/16 in press-fit)",
    )

    # --- Maker's name along the rear-left arm.
    len_rl = math.hypot(NEST_CENTER_X - DATUM_BAR_WIDTH * 0.5, NEST_CENTER_Y - (LEFT_BAR_Y1 - 12.0))
    ux = (DATUM_BAR_WIDTH * 0.5 - NEST_CENTER_X) / len_rl
    uy = ((LEFT_BAR_Y1 - 12.0) - NEST_CENTER_Y) / len_rl
    engrave_on_path(
        component,
        wall_plane,
        NAME_TEXT,
        (NEST_CENTER_X + 60.0 * ux, NEST_CENTER_Y + 60.0 * uy),
        (NEST_CENTER_X + 98.0 * ux, NEST_CENTER_Y + 98.0 * uy),
        NAME_TEXT_HEIGHT,
        NAME_DEPTH,
        "Maker Name - Rear-Left Arm",
    )

    for plane in (component.xYConstructionPlane, wall_plane, pickup_top_plane):
        plane.isLightBulbOn = False


def export_design(design, output_directory):
    manager = design.exportManager
    f3d_path = os.path.join(output_directory, "edge_datum_wafer_jig.f3d")
    step_path = os.path.join(output_directory, "edge_datum_wafer_jig.step")
    print_directory = os.path.join(os.path.dirname(output_directory), "print-files")
    os.makedirs(print_directory, exist_ok=True)
    stl_path = os.path.join(print_directory, "edge_datum_wafer_jig.stl")
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
            "Edge-datum wafer jig created (wafer on field center 92.45, 110.09).\n\n"
            f"Fusion archive:\n{f3d_path}\n\n"
            f"STEP file:\n{step_path}\n\n"
            f"High-quality binary STL:\n{stl_path}",
            "Edge-Datum Jig Complete",
        )
    except Exception:
        ui.messageBox(traceback.format_exc(), "Edge-Datum Jig Error")


def stop(_context):
    pass
