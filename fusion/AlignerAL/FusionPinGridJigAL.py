"""Build and export the ALUMINUM variant of the four-dowel grid-indexed 100 mm wafer jig.

Derived from the SLA script (FusionPinGridJigSLA.py) but reworked for machining from
aluminum plate rather than 3D printing. The differences from the printed jigs:

  - Base is a flat plate 7 mm thick. Its outline is not a fixed square: it is the tight
    bounding box of the real features (dowel bores + pocket walls) plus PLATE_EDGE_MARGIN
    (5 mm) per side, so no material is wasted. The wafer is centered on the dowel
    pattern, so the plate comes out nearly centered on the origin. The "spider" is gone.
  - The wafer nest is a POCKET milled POCKET_DEPTH (2 mm) into the plate top, not
    raised walls: the wafer drops into the pocket and rests on its floor, with the
    surrounding rim standing proud. 7 mm plate - 2 mm pocket leaves a solid 5 mm
    floor under the wafer.
  - The wafer is located by only two things: the pocket FRONT wall (the primary flat,
    Y + rotation) and a square X-datum block on the upper-left wall whose slightly-
    rounded corner touches the wafer OD at the 9:30 position (X) -- the same contact
    point the SLA locating pin used. The side and rear walls are held clear; the wafer
    is centered on the pin pattern and taped down.
  - Two access reliefs, milled at pocket depth, run from the pocket out to the plate
    edge at front-center and rear-center for finger / tape access to the recessed
    wafer. The front one also splits the primary-flat datum into two end pads.
  - Dowel bores are reamed to a true 3/16 in (4.7625 mm), line-to-line with the
    ground steel dowels, for a location / light-press fit in aluminum (retain with a
    drop of epoxy). With the wafer centered, the two rear dowels fall inside the pocket,
    so those corners are left un-milled (clipped) to keep the bores in full 7 mm metal.
  - No engraved maker's mark.

A machined part is cut to nominal on the mill, so there is no cure-shrink to
compensate -- leave SCALE_FACTOR at 1.000 (kept only as a general nominal/measured
trim). The wafer is now CENTERED on the pin pattern (NEST_CENTER = 0,0), which removes
the old ~(+10.48, -6.30) mm exposure-landing offset -- so re-derive the exposure
position in software (GLOBAL_X/Y_OFFSET_UM in slicing/split_klayout.py) or re-center the
exposure for a centered wafer (see CALIBRATION_AND_SLIDING_NEST_NOTES.md).
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

# Uniform-scale factor about the origin (the pin-pattern center), applied to the
# whole solid at the end of build_model. Carried over from the SLA script's cure-
# shrink compensation. A machined aluminum part is cut to nominal on the mill and
# has no such shrink, so leave this at 1.000; it is retained only as a general
# nominal/measured trim if a finished part ever measures off. > 1.0 grows the model.
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

# Wafer nest CENTERED on the pin pattern: the wafer center coincides with the middle
# of the four dowels (the origin, 0,0). The nest used to be offset from the pins
# (+7.290, -4.950 design offset plus a +3.187, -1.346 machine-offset calibration,
# ~(+10.48, -6.30) mm total) so a fixed, field-centered exposure landed on the wafer.
# Per request the wafer is now centered on the pins, which REMOVES that shift -- so a
# fixed exposure no longer lands where it did. Re-introduce the equivalent offset in
# software (GLOBAL_X/Y_OFFSET_UM in slicing/split_klayout.py) or re-center the exposure.
NEST_OFFSET_FROM_PIN_CENTER_X = 0.0
NEST_OFFSET_FROM_PIN_CENTER_Y = 0.0
NEST_CALIBRATION_X = 0.0
NEST_CALIBRATION_Y = 0.0
NEST_CENTER_X = NEST_OFFSET_FROM_PIN_CENTER_X + NEST_CALIBRATION_X
NEST_CENTER_Y = NEST_OFFSET_FROM_PIN_CENTER_Y + NEST_CALIBRATION_Y

# Four steel locating dowels on the corners of a 4 x 4 grid-space square. The
# inner 2 x 2 set was removed: the outer square alone fixes position and rotation,
# and fewer dowels means fewer holes to line up when seating the plate.
#
# Each corner has a through bore straight through the 7 mm plate that takes a 3/16 in
# (4.7625 mm) ground steel dowel. The locating surface is ground steel, not milled
# aluminum, so pin precision and wear are decoupled from the plate's machined
# tolerance: the dowel slip-fits the table's 1/4-20 tapped hole (~4.87 mm crest ID)
# and locates in the plate bore. The dowel's far end bears in the table hole, so the
# bore only has to hold it square and captive; retain with a drop of epoxy. With the
# wafer centered on the pins, the two rear dowels fall inside the wafer pocket, so
# those corners are left un-milled (clipped in build_model) to keep the bores solid.
DOWEL_DIAMETER = 4.7625          # 3/16 in ground steel dowel
DOWEL_PROTRUSION = 5.000         # protrusion below the plate into the table hole; matches the v2 pins (5 mm)
# The bore runs through the full 7 mm plate. Cut each dowel to plate thickness +
# protrusion (~7 + 5 = ~12 mm) so it engages the full bore and stands 5 mm proud.
# Bore diameter: a true 3/16 in, line-to-line with the dowel. A reamed 3/16 hole in
# aluminum is a location / light-press fit on the ground dowel (aluminum will not
# split the way the resin did, so it takes the interference); retain with epoxy.
DOWEL_HOLE_DIAMETER = 4.7625     # exactly 3/16 in
FILLET_RADIUS = 2.500             # rounds the four vertical corner edges of the plate (deburr / looks)

# Base plate. The outline is NOT a fixed square: build_model computes it as the tight
# bounding box of the real features -- the dowel-bore outer edges and the milled pocket
# walls -- grown by PLATE_EDGE_MARGIN on every side, so the plate carries no wasted
# material. The wafer is centered on the dowel pattern, so the plate comes out a
# rectangle nearly centered on the origin. The plate is 7 mm thick so that after the 2 mm
# nest pocket is milled in, a solid 5 mm floor remains under the wafer.
PLATE_EDGE_MARGIN = 5.000        # solid margin from each plate edge to the nearest feature
BASE_THICKNESS = 7.000           # 7 mm aluminum plate (2 mm pocket + 5 mm floor)

# Wafer nest: a pocket milled POCKET_DEPTH into the plate top (not raised walls). The
# wafer drops into the pocket and rests on its floor; the surrounding rim stands
# POCKET_DEPTH proud. The wafer is located by:
#   - the pocket FRONT wall (the primary flat) -> Y + rotation, and
#   - a square X-datum block on the upper-left wall whose slightly-rounded corner
#     touches the wafer OD at 9:30 -> X.
# The front wall is a hard datum -- it sets the wafer's Y, hence where the exposure
# lands -- so it stays fixed on the flat. The side and rear walls are pure clearance:
# NEST_CLEARANCE_SIDE is symmetric so the wafer stays centered left-right, and
# NEST_CLEARANCE_REAR is larger because the pocket's extra depth (front is fixed) is
# added entirely at the back. The wafer is taped down; the nest only locates it.
POCKET_DEPTH = 2.000             # depth milled into the plate top for the wafer nest
NEST_CLEARANCE_SIDE = 2.500      # left/right gap (symmetric -> wafer centered left-right)
NEST_CLEARANCE_REAR = 4.000      # rear gap (front is the datum, so pocket height grows rearward)

WAFER_DIAMETER = 100.000
PRIMARY_FLAT_LENGTH = 32.500
# Nest datums. The wafer is located by its PRIMARY flat plus ONE X-datum block,
# nothing else. That single nest fits every SEMI flat type (the secondary flat sits at
# a different clock angle per type, or is absent) and a wafer flipped for back-side
# work. The operator presses it forward onto the front pocket wall and left onto the
# block, then tapes it down:
#   - PRIMARY_FLAT (front pocket wall), 0.175 mm clearance: sets Y + rotation.
#   - X-datum block at the 9:30 position: sets X. 9:30 (165 deg CCW from +X) is the
#     one window that stays clear of the secondary flat for all types and both faces.
#     It presses to the nominal wafer OD, so X references the OD -- repeatability
#     tracks OD consistency, not a flat. Same contact point as the SLA locating pin.
# The X datum is an axis-aligned square (0/90 deg edges) with its lower-right corner
# slightly rounded; only that rounded corner touches the wafer OD (the straight edges
# clear it). The square is positioned so the rounded corner is tangent to the OD at
# X_DATUM_ANGLE_DEG.
PRIMARY_FLAT_CLEARANCE = 0.175    # front pocket wall set this far forward of the nominal flat
X_DATUM_ANGLE_DEG = 165.0         # 9:30 upper-left; same clock position the SLA pin used
X_DATUM_SIZE = 8.000              # square X-datum block side (0/90 deg edges)
X_DATUM_CORNER_RADIUS = 1.000     # slightly-rounded contact corner, tangent to the wafer OD

# Two access reliefs, milled at pocket depth: one front-center (through the primary-
# flat wall) and one rear-center, both centered on the wafer and running all the way
# out to the plate edge. They give finger / tape access to the recessed wafer, and
# the front one splits the primary-flat datum into two end pads (good rotation
# control). Centered on the wafer (NEST_CENTER_X, now the origin), so the front relief
# splits the flat symmetrically.
NEST_RELIEF_WIDTH = 15.000


def cm(mm: float) -> float:
    """Fusion API internal length unit is centimeters."""
    return mm / 10.0


def rectangle_points(x: float, y: float, width: float, height: float):
    return [(x, y), (x + width, y), (x + width, y + height), (x, y + height)]


def fillet_outer_vertical_edges(component, radius_mm):
    """Round every vertical (Z-parallel straight) edge of the base body.

    Called right after the square plate is created, when its four corners are the
    only vertical straight edges in the body, so it rounds just those corners.
    Degrades gracefully (tries smaller radii, then skips) if a radius is too large.
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


def rounded_lr_corner_square_sketch(component, plane, x_left, y_bottom, size, corner_radius, name):
    """Axis-aligned square with only its LOWER-RIGHT corner rounded (radius corner_radius).

    Three sharp corners (top-left, top-right, bottom-left); the bottom-right corner is
    a tangent fillet arc. Returns a single-profile sketch (0/90 deg straight edges plus
    the one arc) for extrude_profile.
    """
    sketch = component.sketches.add(plane)
    sketch.name = name
    x_right = x_left + size
    y_top = y_bottom + size
    rc = corner_radius
    p = lambda x, y: adsk.core.Point3D.create(cm(x), cm(y), 0)
    top_left = p(x_left, y_top)
    top_right = p(x_right, y_top)
    right_fillet_start = p(x_right, y_bottom + rc)          # on the right edge
    bottom_fillet_end = p(x_right - rc, y_bottom)           # on the bottom edge
    bottom_left = p(x_left, y_bottom)
    arc_mid = p(
        x_right - rc + rc * math.cos(-math.pi / 4.0),
        y_bottom + rc + rc * math.sin(-math.pi / 4.0),
    )
    lines = sketch.sketchCurves.sketchLines
    lines.addByTwoPoints(top_left, top_right)               # top edge
    lines.addByTwoPoints(top_right, right_fillet_start)     # right edge (down to fillet)
    sketch.sketchCurves.sketchArcs.addByThreePoints(
        right_fillet_start, arc_mid, bottom_fillet_end)     # rounded corner
    lines.addByTwoPoints(bottom_fillet_end, bottom_left)    # bottom edge (left)
    lines.addByTwoPoints(bottom_left, top_left)             # left edge (up)
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
    top_plane = offset_plane(component, BASE_THICKNESS, "Plate Top")

    # Shared geometry references (all in absolute mm; origin = pin-pattern center).
    outer_half_span = OUTER_PIN_PATTERN_SPAN / 2.0
    wafer_radius = WAFER_DIAMETER / 2.0
    primary_depth = math.sqrt(wafer_radius**2 - (PRIMARY_FLAT_LENGTH / 2.0) ** 2)
    flat_y = NEST_CENTER_Y - primary_depth  # nominal primary-flat line

    # Wafer extents and the pocket rectangle around it.
    wx_left = NEST_CENTER_X - wafer_radius
    wx_right = NEST_CENTER_X + wafer_radius
    wy_rear = NEST_CENTER_Y + wafer_radius
    px_left = wx_left - NEST_CLEARANCE_SIDE
    px_right = wx_right + NEST_CLEARANCE_SIDE
    py_rear = wy_rear + NEST_CLEARANCE_REAR
    py_front = flat_y - PRIMARY_FLAT_CLEARANCE  # front pocket wall = primary-flat datum (fixed)

    # Base-plate outline: the tight bounding box of the real features -- the dowel-bore
    # outer edges and the pocket step-down walls -- grown by PLATE_EDGE_MARGIN on every
    # side, so no material is wasted. The wafer is centered on the dowel pattern, so this
    # comes out nearly centered on the origin. The access reliefs are open channels to
    # the edge, so they do not drive the outline.
    dowel_outer = outer_half_span + DOWEL_HOLE_DIAMETER / 2.0
    plate_x_min = min(px_left, -dowel_outer) - PLATE_EDGE_MARGIN
    plate_x_max = max(px_right, dowel_outer) + PLATE_EDGE_MARGIN
    plate_y_min = min(py_front, -dowel_outer) - PLATE_EDGE_MARGIN
    plate_y_max = max(py_rear, dowel_outer) + PLATE_EDGE_MARGIN
    plate_width = plate_x_max - plate_x_min
    plate_height = plate_y_max - plate_y_min

    for name, value, comment in (
        ("gridPitch", GRID_PITCH, "Table hole-grid pitch"),
        ("indexMove", INDEX_MOVE, "Two-grid-space indexing move"),
        ("outerPinPatternSpan", OUTER_PIN_PATTERN_SPAN, "Four-space outer pin span"),
        ("dowelDiameter", DOWEL_DIAMETER, "3/16 in steel locating dowel diameter"),
        ("dowelHoleDiameter", DOWEL_HOLE_DIAMETER, "3/16 in reamed dowel bore"),
        ("plateEdgeMargin", PLATE_EDGE_MARGIN, "Solid margin, plate edge to nearest feature"),
        ("plateWidth", plate_width, "Computed plate width (X)"),
        ("plateHeight", plate_height, "Computed plate height (Y)"),
        ("baseThickness", BASE_THICKNESS, "Base plate thickness"),
        ("pocketDepth", POCKET_DEPTH, "Wafer-nest pocket depth"),
        ("nestClearanceSide", NEST_CLEARANCE_SIDE, "Left/right pocket-wall clearance"),
        ("nestClearanceRear", NEST_CLEARANCE_REAR, "Rear pocket-wall clearance"),
        ("filletRadius", FILLET_RADIUS, "Base-plate corner fillet radius"),
        ("primaryFlatClearance", PRIMARY_FLAT_CLEARANCE, "Front wall forward of nominal flat"),
        ("xDatumSize", X_DATUM_SIZE, "Square X-datum block side"),
        ("nestReliefWidth", NEST_RELIEF_WIDTH, "Front/rear access relief width"),
        ("nestOffsetX", NEST_OFFSET_FROM_PIN_CENTER_X, "Nest X from pin-square center"),
        ("nestOffsetY", NEST_OFFSET_FROM_PIN_CENTER_Y, "Nest Y from pin-square center"),
    ):
        add_parameter(design, name, value, comment)

    # --- Base plate: the computed feature-bounding rectangle (see above).
    extrude_polygon(
        component,
        xy_plane,
        rectangle_points(plate_x_min, plate_y_min, plate_width, plate_height),
        BASE_THICKNESS,
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation,
        "Base Plate",
    )
    # Round the four vertical corner edges of the plate. Runs now, while the plate
    # corners are the only vertical straight edges in the body (before the pocket).
    fillet_outer_vertical_edges(component, FILLET_RADIUS)

    # --- Wafer nest pocket: a rectangle milled POCKET_DEPTH into the plate top. The
    # wafer drops in and rests on the floor; front wall = primary-flat datum (fixed),
    # sides held NEST_CLEARANCE_SIDE clear, rear held NEST_CLEARANCE_REAR clear. Cut as
    # a plain rectangle here; the X-datum block and the clipped front-right corner are
    # added back afterward.
    extrude_polygon(
        component,
        top_plane,
        rectangle_points(px_left, py_front, px_right - px_left, py_rear - py_front),
        -POCKET_DEPTH,
        adsk.fusion.FeatureOperations.CutFeatureOperation,
        "Wafer Nest Pocket",
    )

    # --- Two access reliefs at pocket depth, centered on the wafer, running out to the
    # plate edge: front-center (through the primary-flat wall, also splitting the datum
    # into two end pads) and rear-center. Each starts a few mm inside the pocket and
    # extends ~1 mm past the plate edge to guarantee a clean open channel.
    half_relief = NEST_RELIEF_WIDTH / 2.0
    front_relief_top = py_front + 3.0
    front_relief_bottom = plate_y_min - 1.0  # ~1 mm past the front plate edge
    extrude_polygon(
        component,
        top_plane,
        rectangle_points(
            NEST_CENTER_X - half_relief,
            front_relief_bottom,
            NEST_RELIEF_WIDTH,
            front_relief_top - front_relief_bottom,
        ),
        -POCKET_DEPTH,
        adsk.fusion.FeatureOperations.CutFeatureOperation,
        "Front-Center Access Relief",
    )
    rear_relief_bottom = py_rear - 3.0
    rear_relief_top = plate_y_max + 1.0  # ~1 mm past the rear plate edge
    extrude_polygon(
        component,
        top_plane,
        rectangle_points(
            NEST_CENTER_X - half_relief,
            rear_relief_bottom,
            NEST_RELIEF_WIDTH,
            rear_relief_top - rear_relief_bottom,
        ),
        -POCKET_DEPTH,
        adsk.fusion.FeatureOperations.CutFeatureOperation,
        "Rear-Center Access Relief",
    )

    # --- X-datum block at the 9:30 position (upper-left): an axis-aligned square whose
    # lower-right corner is slightly rounded. Refilling it from the pocket floor back to
    # the plate top leaves a square tab on the left wall; only its rounded corner
    # touches the wafer OD (tangent at 9:30 -- the same contact point as the SLA pin),
    # while the straight 0/90 deg edges clear the wafer.
    x_datum_angle = math.radians(X_DATUM_ANGLE_DEG)
    rc = X_DATUM_CORNER_RADIUS
    # Fillet-arc center on the OD radial at (R + rc) makes the rounded corner externally
    # tangent to the wafer OD; back out the square's lower-right corner from that center.
    arc_cx = NEST_CENTER_X + (wafer_radius + rc) * math.cos(x_datum_angle)
    arc_cy = NEST_CENTER_Y + (wafer_radius + rc) * math.sin(x_datum_angle)
    sq_right = arc_cx + rc
    sq_bottom = arc_cy - rc
    sq_left = sq_right - X_DATUM_SIZE
    extrude_profile(
        component,
        rounded_lr_corner_square_sketch(
            component,
            top_plane,
            sq_left,
            sq_bottom,
            X_DATUM_SIZE,
            rc,
            f"X Datum Square Sketch ({X_DATUM_ANGLE_DEG:g} deg / 9:30)",
        ),
        -POCKET_DEPTH,
        adsk.fusion.FeatureOperations.JoinFeatureOperation,
        f"X Datum Square ({X_DATUM_ANGLE_DEG:g} deg / 9:30, rounded corner)",
    )

    # --- Above the X-datum the wafer OD has curved inboard, so the pocket does not need
    # to reach the far-left wall there. Refill the strip between the left wall and the
    # X-datum's right face, from the top of the datum up to the rear wall, leaving it
    # un-milled: the left wall runs flush with the X-datum above the datum (saves mill
    # time for no loss of clearance -- the wafer is well inboard of it up there).
    sq_top = sq_bottom + X_DATUM_SIZE
    extrude_polygon(
        component,
        top_plane,
        rectangle_points(px_left, sq_top, sq_right - px_left, py_rear - sq_top),
        -POCKET_DEPTH,
        adsk.fusion.FeatureOperations.JoinFeatureOperation,
        "Left Wall Flush Above X-Datum",
    )

    # --- Clip any pocket corner that a dowel falls inside: refill a block around that
    # dowel back to full height so its bore stays in solid metal, keeping a ~clip_wall
    # wall to the pocket void. The wafer never reaches the pocket corners, so leaving
    # them solid is free. Which dowels land inside depends on where the wafer sits:
    # with the wafer centered on the pins, the two REAR dowels fall in the rear corners
    # (the front pair sit ahead of the primary-flat wall, outside the pocket).
    clip_wall = 3.5
    clip_margin = DOWEL_HOLE_DIAMETER / 2.0 + clip_wall
    for cx, cy in (
        (-outer_half_span, -outer_half_span),
        (+outer_half_span, -outer_half_span),
        (-outer_half_span, +outer_half_span),
        (+outer_half_span, +outer_half_span),
    ):
        if not (px_left < cx < px_right and py_front < cy < py_rear):
            continue  # dowel already sits in the solid rim
        bx0 = (cx - clip_margin) if cx > 0 else px_left
        bx1 = px_right if cx > 0 else (cx + clip_margin)
        by0 = (cy - clip_margin) if cy > 0 else py_front
        by1 = py_rear if cy > 0 else (cy + clip_margin)
        extrude_polygon(
            component,
            top_plane,
            rectangle_points(bx0, by0, bx1 - bx0, by1 - by0),
            -POCKET_DEPTH,
            adsk.fusion.FeatureOperations.JoinFeatureOperation,
            f"Corner Clip (dowel {cx:+.1f}, {cy:+.1f})",
        )

    # --- Four 3/16 in dowel bores straight through the full 7 mm plate, at the corners
    # of the 4 x 4 grid-space square. Reamed line-to-line with the dowels for a
    # location / light-press fit; retain with epoxy. All four sit in full-height metal
    # (the front-right one via the corner clip above).
    dowel_locations = (
        ("Outer Front Left", -outer_half_span, -outer_half_span),
        ("Outer Front Right", +outer_half_span, -outer_half_span),
        ("Outer Rear Left", -outer_half_span, +outer_half_span),
        ("Outer Rear Right", +outer_half_span, +outer_half_span),
    )
    for bore_name, x, y in dowel_locations:
        extrude_profile(
            component,
            circle_sketch(
                component,
                top_plane,
                x,
                y,
                DOWEL_HOLE_DIAMETER,
                f"{bore_name} Dowel Bore Sketch",
            ),
            -BASE_THICKNESS,
            adsk.fusion.FeatureOperations.CutFeatureOperation,
            f"{bore_name} Dowel Bore",
        )

    # Uniform-scale trim about the origin (see SCALE_FACTOR). Skipped at 1.000, which
    # is the intended value for a machined part.
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

    for plane in (component.xYConstructionPlane, top_plane):
        plane.isLightBulbOn = False


def export_design(design, output_directory):
    manager = design.exportManager
    f3d_path = os.path.join(output_directory, "pin_grid_wafer_jig_al.f3d")
    step_path = os.path.join(output_directory, "pin_grid_wafer_jig_al.step")
    print_directory = os.path.join(os.path.dirname(output_directory), "print-files")
    os.makedirs(print_directory, exist_ok=True)
    stl_path = os.path.join(print_directory, "pin_grid_wafer_jig_al.stl")
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
            f"Four-dowel grid wafer jig (aluminum) created at scale {SCALE_FACTOR:g}.\n\n"
            f"Fusion archive:\n{f3d_path}\n\n"
            f"STEP file:\n{step_path}\n\n"
            f"High-quality binary STL:\n{stl_path}",
            "Pin Grid Jig Complete",
        )
    except Exception:
        ui.messageBox(traceback.format_exc(), "Pin Grid Jig Error")


def stop(_context):
    pass
