"""Edge-datum ALUMINUM wafer jig -- flat-plate SPIDER, laser outline + hand-milled nest.

A single flat 7 mm aluminum plate: the spider outline is laser/waterjet cut (that time is
basically free, so the form follows the features) and the nest is HAND-MILLABLE -- only
straight-walled cuts, no curved milled walls. Structure:

  * A round nest HUB with thin ARMS out to the datum pads and the anchor -- two arms to a
    LEFT datum bar, one to a FRONT datum foot, one to the anchor boss. Open windows between.
  * The whole nest interior + neck is MILLED DOWN to POCKET_DEPTH. The recess runs out to
    the laser-cut round edge (the mill just clears to the pre-cut edge -- no curved wall),
    and only the straight datum features are left proud: a PRIMARY-FLAT ridge (Y + rotation)
    and a SQUARE X-DATUM with one slightly-rounded corner touching the wafer OD at 9:30 (X).
    Same flat position + 9:30 contact as the PLA jig, so the wafer seats in the same place.
  * DATUMS TO THE TABLE ARE EDGE-CONTACT SCREWS in the bar/foot ends: set screws drop
    through the overhang just off the table's front-left edges; their shanks butt the
    table's side faces. Two on the left (X + yaw), one on the front (Y). The band pulls the
    jig up/right into them.
  * The rubber-band anchor is the full-height SQUARE boss in the top-right (left UNMILLED),
    with a press-fit 3/16 in rod the band loops over.

Origin = table front-left corner (left edge = X 0, front edge = Y 0). Wafer nest center =
laser field center in table coords, (92.45, 110.09) (confirmed 2026-08-14). Slicer GLOBAL
offset stays 0.
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

# Wafer nest center = laser field center (08-14 stage cal). Kept identical to the PLA jig.
NEST_CENTER_X = 92.450
NEST_CENTER_Y = 110.090

# Flat 7 mm plate; nest recess milled POCKET_DEPTH into the top (5 mm floor).
BASE_THICKNESS = 7.000
POCKET_DEPTH = 2.000

# Wafer + datum geometry -- same flat/contact as the PLA jig so the wafer seats the same.
WAFER_DIAMETER = 100.000
PRIMARY_FLAT_LENGTH = 32.500
PRIMARY_FLAT_CLEARANCE = 0.175      # primary-flat ridge face this far forward of nominal flat
PRIMARY_FLAT_PAD_DEPTH = 4.000      # ridge thickness (Y) behind its datum face
PRIMARY_FLAT_PAD_MARGIN = 1.500     # ridge overhang past each end of the flat
X_DATUM_ANGLE_DEG = 165.0           # 9:30 upper-left; same contact point as the PLA jig
X_DATUM_SIZE = 8.000                # square X-datum side
X_DATUM_CORNER_RADIUS = 1.000       # slightly-rounded contact corner, tangent to the wafer OD
PICKUP_GAP_WIDTH = 15.000           # opening through the primary flat for wafer pickup (splits it)

# Nest hub + spider arms.
NEST_RIM_WALL = 5.000               # hub disc radius = wafer radius + this
ARM_WIDTH = 18.000
ANCHOR_ARM_WIDTH = 12.000
FILLET_RADIUS = 2.500

# Nest recess milling: extend the straight-walled cut MILL_OVERTRAVEL past the hub so its
# boundary is the laser-cut edge (no curved wall), and keep ANCHOR_KEEPOUT of full-height
# metal around the anchor boss (notched out of the cut).
MILL_OVERTRAVEL = 3.000
ANCHOR_KEEPOUT = 4.000

# Left datum bar + front datum foot: full-height pads that lap past the table edges to
# carry the datum screws and land the arms.
DATUM_BAR_WIDTH = 8.000
LEFT_BAR_Y0 = 66.000
LEFT_BAR_Y1 = 171.000
FRONT_FOOT_X0 = 82.000
FRONT_FOOT_X1 = 103.000
FRONT_FOOT_DEPTH = 14.000           # front foot reach inboard from Y 0 (also the neck mill front)

# Edge-contact datum screws (OD tangent to the table edge -> hole center half a diameter in).
DATUM_SCREW_DIAMETER = 6.350        # 1/4-20 UNC major dia = the shank OD that contacts the table
DATUM_SCREW_TAP_DRILL = 5.100       # 1/4-20 tap drill (#7); tap it and run a set screw as the datum
LEFT_SCREW_Y = (75.000, 162.000)    # two left-edge screws (X + yaw)
FRONT_SCREW_X = 92.450              # one front-edge screw (Y), on the nest centerline
DATUM_EDGE_MARGIN = 4.000

# Rubber-band anchor: full-height SQUARE boss (upper-right, left unmilled) with a press-fit
# 3/16 in rod the band loops over; its tension pulls the plate up/right into the screws.
ANCHOR_X = 140.000
ANCHOR_Y = 158.000
ANCHOR_ROD_DIAMETER = 4.7625        # 3/16 in ground steel anchor rod
ANCHOR_ROD_BORE_DIAMETER = 4.7625   # exactly 3/16 in, reamed line-to-line (press fit + epoxy)
ANCHOR_ROD_PROTRUSION = 15.000      # rod stands 1.5 cm proud; cut it to plate thickness + this
ANCHOR_ISLAND_SIZE = 14.000         # square anchor boss side


def cm(mm):
    """Fusion API internal length unit is centimeters."""
    return mm / 10.0


def rectangle_points(x, y, width, height):
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


def rounded_lr_corner_square_sketch(component, plane, x_left, y_bottom, size, corner_radius, name):
    """Axis-aligned square with only its LOWER-RIGHT corner rounded (radius corner_radius).

    Three sharp corners (top-left, top-right, bottom-left); the bottom-right corner is a
    tangent fillet arc -- the only part that touches the wafer OD. One-profile sketch.
    """
    sketch = component.sketches.add(plane)
    sketch.name = name
    x_right = x_left + size
    y_top = y_bottom + size
    rc = corner_radius
    p = lambda x, y: adsk.core.Point3D.create(cm(x), cm(y), 0)
    top_left = p(x_left, y_top)
    top_right = p(x_right, y_top)
    right_fillet_start = p(x_right, y_bottom + rc)
    bottom_fillet_end = p(x_right - rc, y_bottom)
    bottom_left = p(x_left, y_bottom)
    arc_mid = p(
        x_right - rc + rc * math.cos(-math.pi / 4.0),
        y_bottom + rc + rc * math.sin(-math.pi / 4.0),
    )
    lines = sketch.sketchCurves.sketchLines
    lines.addByTwoPoints(top_left, top_right)
    lines.addByTwoPoints(top_right, right_fillet_start)
    sketch.sketchCurves.sketchArcs.addByThreePoints(right_fillet_start, arc_mid, bottom_fillet_end)
    lines.addByTwoPoints(bottom_fillet_end, bottom_left)
    lines.addByTwoPoints(bottom_left, top_left)
    return sketch


def fillet_outer_vertical_edges(component, radius_mm):
    """Round every vertical (Z-parallel straight) edge of the base body -- the in-plane
    outline corners where arms meet the hub, bar, foot and boss."""
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


def offset_plane(component, offset_mm, name):
    plane_input = component.constructionPlanes.createInput()
    plane_input.setByOffset(
        component.xYConstructionPlane,
        adsk.core.ValueInput.createByString(f"{offset_mm} mm"),
    )
    plane = component.constructionPlanes.add(plane_input)
    plane.name = name
    return plane


def polygon_sketch(component, plane, points_mm, name):
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

    wafer_radius = WAFER_DIAMETER / 2.0
    hub_radius = wafer_radius + NEST_RIM_WALL
    primary_depth = math.sqrt(wafer_radius**2 - (PRIMARY_FLAT_LENGTH / 2.0) ** 2)
    flat_y = NEST_CENTER_Y - primary_depth
    py_front = flat_y - PRIMARY_FLAT_CLEARANCE   # primary-flat datum face (wafer pushes to here)

    screw_r = DATUM_SCREW_DIAMETER / 2.0
    left_screw_x = -screw_r          # left screws: OD tangent to the table left edge (X 0)
    front_screw_y = -screw_r         # front screw: OD tangent to the table front edge (Y 0)
    datum_reach = screw_r + DATUM_EDGE_MARGIN
    bar_x_outer = left_screw_x - datum_reach
    foot_y_outer = front_screw_y - datum_reach

    for name, value, comment in (
        ("nestCenterX", NEST_CENTER_X, "Wafer/field center X from the datum corner"),
        ("nestCenterY", NEST_CENTER_Y, "Wafer/field center Y from the datum corner"),
        ("hubRadius", hub_radius, "Nest hub disc radius"),
        ("armWidth", ARM_WIDTH, "Spider arm width"),
        ("baseThickness", BASE_THICKNESS, "Flat aluminum plate thickness"),
        ("pocketDepth", POCKET_DEPTH, "Nest recess milled depth"),
        ("primaryFlatClearance", PRIMARY_FLAT_CLEARANCE, "Flat ridge face forward of nominal flat"),
        ("xDatumSize", X_DATUM_SIZE, "Square X-datum side"),
        ("datumScrewDiameter", DATUM_SCREW_DIAMETER, "Datum set-screw OD (contacts the table)"),
        ("datumScrewTapDrill", DATUM_SCREW_TAP_DRILL, "Datum screw tap-drill hole"),
        ("anchorRodDiameter", ANCHOR_ROD_DIAMETER, "3/16 in steel anchor rod diameter"),
        ("anchorRodBoreDiameter", ANCHOR_ROD_BORE_DIAMETER, "Press-fit anchor-rod bore"),
        ("anchorRodProtrusion", ANCHOR_ROD_PROTRUSION, "Anchor rod stand-proud height"),
        ("anchorIslandSize", ANCHOR_ISLAND_SIZE, "Square anchor boss side"),
        ("filletRadius", FILLET_RADIUS, "Outline corner fillet radius"),
    ):
        add_parameter(design, name, value, comment)

    # --- Nest hub disc (full height).
    extrude_profile(
        component,
        circle_sketch(component, xy_plane, NEST_CENTER_X, NEST_CENTER_Y, 2.0 * hub_radius, "Nest Hub Sketch"),
        BASE_THICKNESS,
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation,
        "Nest Hub",
    )

    # --- Spider arms (full height): two to the left bar, one to the front foot, one to the
    # anchor boss.
    arm_specs = (
        ("Left Arm Rear", (DATUM_BAR_WIDTH * 0.5, LEFT_BAR_Y1 - 12.0), ARM_WIDTH),
        ("Left Arm Front", (DATUM_BAR_WIDTH * 0.5, LEFT_BAR_Y0 + 12.0), ARM_WIDTH),
        ("Front Arm", ((FRONT_FOOT_X0 + FRONT_FOOT_X1) / 2.0, FRONT_FOOT_DEPTH * 0.5), ARM_WIDTH),
        ("Anchor Arm", (ANCHOR_X, ANCHOR_Y), ANCHOR_ARM_WIDTH),
    )
    for arm_name, target, width in arm_specs:
        extrude_polygon(
            component,
            xy_plane,
            oriented_rect((NEST_CENTER_X, NEST_CENTER_Y), target, width),
            BASE_THICKNESS,
            adsk.fusion.FeatureOperations.JoinFeatureOperation,
            arm_name,
        )

    # --- Left datum bar + front datum foot: full-height pads lapping past the edges.
    extrude_polygon(
        component,
        xy_plane,
        rectangle_points(bar_x_outer, LEFT_BAR_Y0, DATUM_BAR_WIDTH - bar_x_outer, LEFT_BAR_Y1 - LEFT_BAR_Y0),
        BASE_THICKNESS,
        adsk.fusion.FeatureOperations.JoinFeatureOperation,
        "Left Datum Bar (X + yaw)",
    )
    extrude_polygon(
        component,
        xy_plane,
        rectangle_points(FRONT_FOOT_X0, foot_y_outer, FRONT_FOOT_X1 - FRONT_FOOT_X0, FRONT_FOOT_DEPTH - foot_y_outer),
        BASE_THICKNESS,
        adsk.fusion.FeatureOperations.JoinFeatureOperation,
        "Front Datum Foot (Y)",
    )

    # --- Square anchor boss (full height, upper-right).
    extrude_polygon(
        component,
        xy_plane,
        rectangle_points(ANCHOR_X - ANCHOR_ISLAND_SIZE / 2.0, ANCHOR_Y - ANCHOR_ISLAND_SIZE / 2.0,
                         ANCHOR_ISLAND_SIZE, ANCHOR_ISLAND_SIZE),
        BASE_THICKNESS,
        adsk.fusion.FeatureOperations.JoinFeatureOperation,
        "Rubber-Band Anchor Boss (square)",
    )

    # Round the in-plane outline corners (arm/hub/bar/foot/boss junctions).
    fillet_outer_vertical_edges(component, FILLET_RADIUS)

    # --- Nest recess: mill the hub interior + neck down to POCKET_DEPTH. A straight-walled
    # cut extended MILL_OVERTRAVEL past the hub so its boundary is the laser-cut round edge
    # (the mill just clears to the pre-cut edge -- no curved wall). TWO corners are notched
    # out and left FULL HEIGHT: the top-right anchor pin (ANCHOR_KEEPOUT around the boss),
    # and the top-left cap ABOVE the X-datum (the wafer OD curves inboard there, so it needs
    # no clearance; its outer edge is just the laser hub edge). The X-datum itself is the
    # cut's slightly-rounded upper-left corner, tangent to the wafer OD at 9:30 (sets X).
    mill_x_left = NEST_CENTER_X - hub_radius - MILL_OVERTRAVEL
    mill_x_right = NEST_CENTER_X + hub_radius + MILL_OVERTRAVEL
    mill_y_rear = NEST_CENTER_Y + hub_radius + MILL_OVERTRAVEL
    mill_y_front = FRONT_FOOT_DEPTH                       # mill the neck down to the front foot
    anchor_notch_x = ANCHOR_X - ANCHOR_ISLAND_SIZE / 2.0 - ANCHOR_KEEPOUT
    anchor_notch_y = ANCHOR_Y - ANCHOR_ISLAND_SIZE / 2.0 - ANCHOR_KEEPOUT

    # X-datum rounded corner: a radius-X_DATUM_CORNER_RADIUS arc whose closest point touches
    # the wafer OD at 9:30 (same contact as the PLA jig). Above it, a straight "flush wall"
    # clears the inboard-curving OD; below it, the recess opens to the hub edge.
    x_datum_angle = math.radians(X_DATUM_ANGLE_DEG)
    rc = X_DATUM_CORNER_RADIUS
    arc_cx = NEST_CENTER_X + (wafer_radius + rc) * math.cos(x_datum_angle)
    arc_cy = NEST_CENTER_Y + (wafer_radius + rc) * math.sin(x_datum_angle)
    flush_wall_x = arc_cx + rc
    fillet_start = (flush_wall_x, arc_cy)
    fillet_end = (arc_cx, arc_cy - rc)
    fillet_mid = (arc_cx + rc * math.cos(-math.pi / 4.0), arc_cy + rc * math.sin(-math.pi / 4.0))

    recess = component.sketches.add(top_plane)
    recess.name = "Nest Recess Sketch"
    to_pt = lambda xy: adsk.core.Point3D.create(cm(xy[0]), cm(xy[1]), 0)
    recess_lines = recess.sketchCurves.sketchLines
    lead = [
        (mill_x_left, mill_y_front),
        (mill_x_right, mill_y_front),
        (mill_x_right, anchor_notch_y),   # up the right side to the anchor keep-out
        (anchor_notch_x, anchor_notch_y), # in to protect the anchor pin
        (anchor_notch_x, mill_y_rear),    # up past the hub rear
        (flush_wall_x, mill_y_rear),      # left along the rear to the X-datum flush wall
        fillet_start,                     # down the flush wall to the rounded X-datum corner
    ]
    for start, end in zip(lead, lead[1:]):
        recess_lines.addByTwoPoints(to_pt(start), to_pt(end))
    recess.sketchCurves.sketchArcs.addByThreePoints(
        to_pt(fillet_start), to_pt(fillet_mid), to_pt(fillet_end))
    tail = [
        fillet_end,
        (mill_x_left, fillet_end[1]),     # left along the X-datum base, leaving the cap unmilled
        (mill_x_left, mill_y_front),      # down the left edge (closes the loop)
    ]
    for start, end in zip(tail, tail[1:]):
        recess_lines.addByTwoPoints(to_pt(start), to_pt(end))
    extrude_profile(
        component,
        recess,
        -POCKET_DEPTH,
        adsk.fusion.FeatureOperations.CutFeatureOperation,
        f"Nest Recess (X-datum {X_DATUM_ANGLE_DEG:g} deg / 9:30, anchor + cap unmilled)",
    )

    # --- Primary-flat datum ridge (refilled full height): a straight proud wall whose +Y
    # face sits at the primary flat -> sets Y + rotation. Same flat position as the PLA jig.
    pad_x0 = NEST_CENTER_X - PRIMARY_FLAT_LENGTH / 2.0 - PRIMARY_FLAT_PAD_MARGIN
    pad_x1 = NEST_CENTER_X + PRIMARY_FLAT_LENGTH / 2.0 + PRIMARY_FLAT_PAD_MARGIN
    extrude_polygon(
        component,
        top_plane,
        rectangle_points(pad_x0, py_front - PRIMARY_FLAT_PAD_DEPTH, pad_x1 - pad_x0, PRIMARY_FLAT_PAD_DEPTH),
        -POCKET_DEPTH,
        adsk.fusion.FeatureOperations.JoinFeatureOperation,
        "Primary Flat Datum Ridge (Y + rotation)",
    )

    # --- Pickup gap: a PICKUP_GAP_WIDTH opening milled through the primary-flat ridge,
    # centered on the nest -- splits the ridge into two pads and gives wafer pickup/finger
    # access. Same place and width as the PLA jig's pickup opening.
    extrude_polygon(
        component,
        top_plane,
        rectangle_points(
            NEST_CENTER_X - PICKUP_GAP_WIDTH / 2.0,
            py_front - PRIMARY_FLAT_PAD_DEPTH - 2.0,
            PICKUP_GAP_WIDTH,
            PRIMARY_FLAT_PAD_DEPTH + 5.0,
        ),
        -POCKET_DEPTH,
        adsk.fusion.FeatureOperations.CutFeatureOperation,
        f"{PICKUP_GAP_WIDTH:g} mm Pickup Gap (through primary flat)",
    )

    # --- Datum screw tap-holes: 2 left (X + yaw), 1 front (Y). Through-tapped for set
    # screws whose shanks hang below the plate and butt the table edges.
    for index, screw_y in enumerate(LEFT_SCREW_Y):
        extrude_profile(
            component,
            circle_sketch(component, top_plane, left_screw_x, screw_y, DATUM_SCREW_TAP_DRILL,
                          f"Left Datum Screw {index + 1} Sketch"),
            -BASE_THICKNESS,
            adsk.fusion.FeatureOperations.CutFeatureOperation,
            f"Left Datum Screw Tap-Hole {index + 1} (X + yaw)",
        )
    extrude_profile(
        component,
        circle_sketch(component, top_plane, FRONT_SCREW_X, front_screw_y, DATUM_SCREW_TAP_DRILL,
                      "Front Datum Screw Sketch"),
        -BASE_THICKNESS,
        adsk.fusion.FeatureOperations.CutFeatureOperation,
        "Front Datum Screw Tap-Hole (Y)",
    )

    # --- Rubber-band anchor rod bore: reamed 3/16 in through-bore for a press-fit steel rod
    # (rod stands ANCHOR_ROD_PROTRUSION proud; not modeled, same as the dowels).
    extrude_profile(
        component,
        circle_sketch(component, top_plane, ANCHOR_X, ANCHOR_Y, ANCHOR_ROD_BORE_DIAMETER,
                      "RB Anchor Rod Bore Sketch"),
        -BASE_THICKNESS,
        adsk.fusion.FeatureOperations.CutFeatureOperation,
        "Rubber-Band Anchor Rod Bore (3/16 in press-fit)",
    )

    for plane in (component.xYConstructionPlane, top_plane):
        plane.isLightBulbOn = False


def export_design(design, output_directory):
    manager = design.exportManager
    f3d_path = os.path.join(output_directory, "edge_datum_wafer_jig_al.f3d")
    step_path = os.path.join(output_directory, "edge_datum_wafer_jig_al.step")
    print_directory = os.path.join(os.path.dirname(output_directory), "print-files")
    os.makedirs(print_directory, exist_ok=True)
    stl_path = os.path.join(print_directory, "edge_datum_wafer_jig_al.stl")
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
            "Edge-datum wafer jig (ALUMINUM spider: 7 mm plate, hand-milled nest, screw datums)\n"
            "created (wafer on field center 92.45, 110.09, same as the PLA jig).\n\n"
            f"Fusion archive:\n{f3d_path}\n\n"
            f"STEP file:\n{step_path}\n\n"
            f"High-quality binary STL:\n{stl_path}",
            "Edge-Datum Aluminum Spider Jig Complete",
        )
    except Exception:
        ui.messageBox(traceback.format_exc(), "Edge-Datum Aluminum Spider Jig Error")


def stop(_context):
    pass
