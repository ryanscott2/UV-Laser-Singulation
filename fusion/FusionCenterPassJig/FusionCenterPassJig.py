"""Build and export a center-field 100 mm wafer jig in Autodesk Fusion."""

from __future__ import annotations

import math
import os
import traceback

import adsk.core
import adsk.fusion


# Machine and calibration geometry, millimeters.
TABLE_WIDTH = 200.000
INSIDE_STOP_SPAN = TABLE_WIDTH
MAX_USABLE_FIELD_SIZE = 78.485
MEASUREMENT_FIELD_SIZE = 78.484
MEASURED_FIELD_LEFT_EDGE_X = 60.930
MEASURED_FIELD_FRONT_EDGE_Y = 68.430
EDGE_DERIVED_CENTER_X = MEASURED_FIELD_LEFT_EDGE_X + MEASUREMENT_FIELD_SIZE / 2.0  # 100.172
EDGE_DERIVED_CENTER_Y = MEASURED_FIELD_FRONT_EDGE_Y + MEASUREMENT_FIELD_SIZE / 2.0  # 107.672

# Authoritative calibration: the physical center of a cross commanded at (0, 0).
# The edge-derived values above are retained only to document the independent
# measurement and its disagreement with the direct zero-cross calibration.
MEASURED_ZERO_CROSS_X = 96.190
MEASURED_ZERO_CROSS_Y = 109.350
FIELD_CENTER_X = MEASURED_ZERO_CROSS_X
FIELD_CENTER_Y = MEASURED_ZERO_CROSS_Y
JIG_X_CORRECTION = 0.000
JIG_Y_CORRECTION = 0.000

# Wafer geometry, millimeters.
WAFER_DIAMETER = 100.000
PRIMARY_FLAT_LENGTH = 32.500
SECONDARY_FLAT_LENGTH = 18.000

# Printable PLA fixture geometry, millimeters.
BASE_THICKNESS = 2.000
SIDEWALL_HEIGHT = 1.500
SIDEWALL_THICKNESS = 3.000
TABLE_LIP_DROP = 5.000
STRUT_WIDTH = 8.000
STRUT_HEIGHT = 8.000
RADIAL_CLEARANCE = 0.500
PRIMARY_FLAT_CLEARANCE = 0.500
SECONDARY_DATUM_CLEARANCE = 0.100
PICKUP_GAP_WIDTH = 20.000

FRONT_BAR_DEPTH = 12.000
SIDE_BAR_THICKNESS = 8.000
SIDE_CONTACT_LENGTH = 65.000
BASE_BRIDGE_WIDTH = WAFER_DIAMETER
FRONT_BAR_BRIDGE_OVERLAP = 0.500

NEST_CENTER_X = FIELD_CENTER_X + JIG_X_CORRECTION
NEST_CENTER_Y = FIELD_CENTER_Y + JIG_Y_CORRECTION
SEGMENTS = 144


def cm(mm: float) -> float:
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


def beam_points(start, end, width: float):
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = math.hypot(dx, dy)
    nx = -dy * width / (2.0 * length)
    ny = dx * width / (2.0 * length)
    return [
        (start[0] + nx, start[1] + ny),
        (end[0] + nx, end[1] + ny),
        (end[0] - nx, end[1] - ny),
        (start[0] - nx, start[1] - ny),
    ]


def vertical_capsule_points(center_x, start_center_y, end_center_y, width, segments=24):
    radius = width / 2.0
    points = [(center_x - radius, start_center_y), (center_x - radius, end_center_y)]
    for index in range(1, segments + 1):
        angle = math.pi - index * math.pi / segments
        points.append(
            (
                center_x + radius * math.cos(angle),
                end_center_y + radius * math.sin(angle),
            )
        )
    points.append((center_x + radius, start_center_y))
    for index in range(1, segments):
        angle = -index * math.pi / segments
        points.append(
            (
                center_x + radius * math.cos(angle),
                start_center_y + radius * math.sin(angle),
            )
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


def extrude_polygon(component, plane, points_mm, distance_mm, operation, name):
    sketch = polygon_sketch(component, plane, points_mm, f"{name} Sketch")
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


def loft_polygons(component, first_plane, first_points, second_plane, second_points, operation, name):
    first = polygon_sketch(component, first_plane, first_points, f"{name} Lower Sketch")
    second = polygon_sketch(component, second_plane, second_points, f"{name} Upper Sketch")
    if first.profiles.count != 1 or second.profiles.count != 1:
        raise RuntimeError(f"{name}: expected one profile on each loft plane")
    lofts = component.features.loftFeatures
    loft_input = lofts.createInput(operation)
    loft_input.loftSections.add(first.profiles.item(0))
    loft_input.loftSections.add(second.profiles.item(0))
    loft_input.isSolid = True
    feature = lofts.add(loft_input)
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
    wall_plane = offset_plane(component, BASE_THICKNESS, "Top of Wafer Support Base")
    shoulder_plane = offset_plane(
        component,
        BASE_THICKNESS + SIDEWALL_HEIGHT,
        "Nest Wall and Rib Shoulder Height",
    )
    rib_top_plane = offset_plane(
        component,
        BASE_THICKNESS + STRUT_HEIGHT,
        "Top of Reinforcement Ribs",
    )
    front_notch_top_plane = offset_plane(
        component,
        BASE_THICKNESS + STRUT_HEIGHT + 0.2,
        "Top of 45 Degree Front Bar Notch",
    )
    pickup_top_plane = offset_plane(
        component,
        BASE_THICKNESS + SIDEWALL_HEIGHT + 0.2,
        "Top of Pickup Bevel Cut",
    )
    lip_plane = offset_plane(component, -TABLE_LIP_DROP, "Bottom of Table Lips")

    for name, value, comment in (
        ("tableWidth", TABLE_WIDTH, "Nominal table width"),
        ("insideStopSpan", INSIDE_STOP_SPAN, "Exact inside span between table side datums"),
        ("fieldCenterX", FIELD_CENTER_X, "Laser field center from table left"),
        ("fieldCenterY", FIELD_CENTER_Y, "Laser field center from table front"),
        ("jigXCorrection", JIG_X_CORRECTION, "Nest X calibration correction"),
        ("jigYCorrection", JIG_Y_CORRECTION, "Nest Y calibration correction"),
        ("baseThickness", BASE_THICKNESS, "Wafer support base"),
        ("sidewallHeight", SIDEWALL_HEIGHT, "Wall above support base"),
        ("strutWidth", STRUT_WIDTH, "Constant rib width"),
        ("strutHeight", STRUT_HEIGHT, "Rib height at frame"),
        ("pickupGapWidth", PICKUP_GAP_WIDTH, "Primary-flat pickup opening"),
    ):
        add_parameter(design, name, value, comment)

    outer = wafer_polygon(
        NEST_CENTER_X,
        NEST_CENTER_Y,
        radial_offset=SIDEWALL_THICKNESS,
        primary_relief=SIDEWALL_THICKNESS,
        secondary_relief=SIDEWALL_THICKNESS,
    )
    extrude_polygon(
        component,
        xy_plane,
        outer,
        BASE_THICKNESS,
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation,
        "Center Nest Base",
    )

    # Continue the 2 mm structural sheet from the front table bar to the
    # horizontal centerline of the single nest. It remains exactly one wafer
    # diameter wide.
    wafer_radius = WAFER_DIAMETER / 2.0
    primary_depth = math.sqrt(wafer_radius**2 - (PRIMARY_FLAT_LENGTH / 2.0) ** 2)
    base_bridge = rectangle_points(
        NEST_CENTER_X - BASE_BRIDGE_WIDTH / 2.0,
        -FRONT_BAR_BRIDGE_OVERLAP,
        BASE_BRIDGE_WIDTH,
        NEST_CENTER_Y + FRONT_BAR_BRIDGE_OVERLAP,
    )
    extrude_polygon(
        component,
        xy_plane,
        base_bridge,
        BASE_THICKNESS,
        adsk.fusion.FeatureOperations.JoinFeatureOperation,
        "100 mm Structural Sheet to Nest Centerline",
    )
    extrude_polygon(
        component,
        wall_plane,
        outer,
        SIDEWALL_HEIGHT,
        adsk.fusion.FeatureOperations.JoinFeatureOperation,
        "Center Nest Outer Wall",
    )

    lip_height = TABLE_LIP_DROP + BASE_THICKNESS
    bars = (
        (
            "Front Table Bar",
            rectangle_points(
                -SIDE_BAR_THICKNESS,
                -FRONT_BAR_DEPTH,
                INSIDE_STOP_SPAN + 2.0 * SIDE_BAR_THICKNESS,
                FRONT_BAR_DEPTH,
            ),
            lip_height,
        ),
        (
            "Left Full-Height Datum Bar",
            rectangle_points(
                -SIDE_BAR_THICKNESS,
                -FRONT_BAR_DEPTH,
                SIDE_BAR_THICKNESS,
                SIDE_CONTACT_LENGTH + FRONT_BAR_DEPTH,
            ),
            lip_height + STRUT_HEIGHT,
        ),
        (
            "Right Full-Height Datum Bar",
            rectangle_points(
                INSIDE_STOP_SPAN,
                -FRONT_BAR_DEPTH,
                SIDE_BAR_THICKNESS,
                SIDE_CONTACT_LENGTH + FRONT_BAR_DEPTH,
            ),
            lip_height + STRUT_HEIGHT,
        ),
    )
    for name, points, height in bars:
        extrude_polygon(
            component,
            lip_plane,
            points,
            height,
            adsk.fusion.FeatureOperations.JoinFeatureOperation,
            name,
        )

    extrude_polygon(
        component,
        wall_plane,
        rectangle_points(
            -SIDE_BAR_THICKNESS,
            -FRONT_BAR_DEPTH,
            INSIDE_STOP_SPAN + 2.0 * SIDE_BAR_THICKNESS,
            STRUT_WIDTH,
        ),
        STRUT_HEIGHT,
        adsk.fusion.FeatureOperations.JoinFeatureOperation,
        "Continuous Front Top Rib",
    )

    outer_radius = WAFER_DIAMETER / 2.0 + SIDEWALL_THICKNESS
    attach_dy = 20.0
    attach_dx = math.sqrt(outer_radius**2 - attach_dy**2)
    left_corner = (0.0, -FRONT_BAR_DEPTH + STRUT_WIDTH / 2.0)
    right_corner = (INSIDE_STOP_SPAN, -FRONT_BAR_DEPTH + STRUT_WIDTH / 2.0)
    ribs = (
        ("Left Front Rib", left_corner, (NEST_CENTER_X - attach_dx, NEST_CENTER_Y - attach_dy)),
        ("Left Rear Rib", left_corner, (NEST_CENTER_X - attach_dx, NEST_CENTER_Y + attach_dy)),
        ("Right Front Rib", right_corner, (NEST_CENTER_X + attach_dx, NEST_CENTER_Y - attach_dy)),
        ("Right Rear Rib", right_corner, (NEST_CENTER_X + attach_dx, NEST_CENTER_Y + attach_dy)),
    )
    taper_run = STRUT_HEIGHT - SIDEWALL_HEIGHT
    for name, start, end in ribs:
        footprint = beam_points(start, end, STRUT_WIDTH)
        extrude_polygon(
            component,
            wall_plane,
            footprint,
            SIDEWALL_HEIGHT,
            adsk.fusion.FeatureOperations.JoinFeatureOperation,
            f"{name} Lower Web",
        )
        dx, dy = end[0] - start[0], end[1] - start[1]
        length = math.hypot(dx, dy)
        upper_end = (
            end[0] - dx * taper_run / length,
            end[1] - dy * taper_run / length,
        )
        loft_polygons(
            component,
            shoulder_plane,
            footprint,
            rib_top_plane,
            beam_points(start, upper_end, STRUT_WIDTH),
            adsk.fusion.FeatureOperations.JoinFeatureOperation,
            f"{name} 45 Degree Thickness Taper",
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
        STRUT_HEIGHT + 0.1,
        adsk.fusion.FeatureOperations.CutFeatureOperation,
        "Final Wafer Pocket Clearance",
    )

    outer_flat_y = NEST_CENTER_Y - primary_depth - SIDEWALL_THICKNESS
    nominal_flat_y = NEST_CENTER_Y - primary_depth

    # Interrupt only the raised front reinforcement. The cut starts at the top
    # of the 2 mm floor, so the support base and lower table-contact lip remain
    # continuous exactly like the reference notch.
    front_bar_notch_bottom = rectangle_points(
        NEST_CENTER_X - PICKUP_GAP_WIDTH / 2.0,
        -FRONT_BAR_DEPTH - 0.1,
        PICKUP_GAP_WIDTH,
        FRONT_BAR_DEPTH + 0.2,
    )
    front_notch_expansion = STRUT_HEIGHT + 0.2
    front_bar_notch_top = rectangle_points(
        NEST_CENTER_X - PICKUP_GAP_WIDTH / 2.0 - front_notch_expansion,
        -FRONT_BAR_DEPTH - 0.1 - front_notch_expansion,
        PICKUP_GAP_WIDTH + 2.0 * front_notch_expansion,
        FRONT_BAR_DEPTH + 0.2 + 2.0 * front_notch_expansion,
    )
    loft_polygons(
        component,
        wall_plane,
        front_bar_notch_bottom,
        front_notch_top_plane,
        front_bar_notch_top,
        adsk.fusion.FeatureOperations.CutFeatureOperation,
        "20 mm Front Bar Notch with 45 Degree Sides",
    )

    pickup_bottom = vertical_capsule_points(
        NEST_CENTER_X,
        outer_flat_y,
        nominal_flat_y,
        PICKUP_GAP_WIDTH,
    )
    expansion = SIDEWALL_HEIGHT + 0.2
    pickup_top = vertical_capsule_points(
        NEST_CENTER_X,
        outer_flat_y - expansion,
        nominal_flat_y + expansion,
        PICKUP_GAP_WIDTH + 2.0 * expansion,
    )
    loft_polygons(
        component,
        wall_plane,
        pickup_bottom,
        pickup_top_plane,
        pickup_top,
        adsk.fusion.FeatureOperations.CutFeatureOperation,
        "20 mm Pickup Slot with 45 Degree Bevel",
    )

    for plane in (
        component.xYConstructionPlane,
        wall_plane,
        shoulder_plane,
        rib_top_plane,
        front_notch_top_plane,
        pickup_top_plane,
        lip_plane,
    ):
        plane.isLightBulbOn = False


def export_design(design, output_directory):
    manager = design.exportManager
    f3d_path = os.path.join(output_directory, "center_pass_wafer_jig.f3d")
    step_path = os.path.join(output_directory, "center_pass_wafer_jig.step")
    print_directory = os.path.join(os.path.dirname(output_directory), "print-files")
    os.makedirs(print_directory, exist_ok=True)
    stl_path = os.path.join(print_directory, "center_pass_wafer_jig.stl")
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
            "Center-pass wafer jig created.\n\n"
            f"Fusion archive:\n{f3d_path}\n\n"
            f"STEP file:\n{step_path}\n\n"
            f"High-quality binary STL:\n{stl_path}",
            "Center Pass Jig Complete",
        )
    except Exception:
        ui.messageBox(traceback.format_exc(), "Center Pass Jig Error")


def stop(_context):
    pass
