"""Build and export the single-jig wafer indexer in Autodesk Fusion.

Run from Fusion: Utilities > Add-Ins > Scripts and Add-Ins > Scripts.
The script creates an editable Fusion design and exports F3D and STEP files
beside this script.
"""

from __future__ import annotations

import math
import os
import traceback

import adsk.core
import adsk.fusion


# Machine geometry, millimeters.
TABLE_WIDTH = 200.000
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
INDEX_OFFSET = 25.000
INSIDE_STOP_SPAN = 250.000

# Wafer geometry, millimeters.
WAFER_DIAMETER = 100.000
PRIMARY_FLAT_LENGTH = 32.500       # front-facing; clearance only
SECONDARY_FLAT_LENGTH = 18.000     # left side; rotational datum

# Part geometry, millimeters.
BASE_THICKNESS = 2.000             # wafer-support floor
SIDEWALL_HEIGHT = 1.500            # height above support floor
SIDEWALL_THICKNESS = 3.000
TABLE_LIP_DROP = 5.000             # downward table-contact height
STRUT_WIDTH = 8.000                # reinforced PLA top-rib width
STRUT_HEIGHT = 8.000               # reinforced PLA top-rib height above base
PICKUP_CHAMFER = 8.000             # full-height 45 degree pickup-slot bevel
RADIAL_CLEARANCE = 0.500
PRIMARY_FLAT_CLEARANCE = 0.500
SECONDARY_DATUM_CLEARANCE = 0.100
PICKUP_GAP_WIDTH = 20.000          # centered opening at accessible primary flat

FRONT_BAR_DEPTH = 12.000
SIDE_BAR_THICKNESS = 8.000
SIDE_CONTACT_LENGTH = 65.000
BASE_BRIDGE_WIDTH = WAFER_DIAMETER
FRONT_BAR_BRIDGE_OVERLAP = 0.500

NEST_CENTER_X = FIELD_CENTER_X + INDEX_OFFSET  # 121.190; other X stop gives 71.190
FRONT_NEST_Y = FIELD_CENTER_Y - INDEX_OFFSET   # 84.350
REAR_NEST_Y = FIELD_CENTER_Y + INDEX_OFFSET    # 134.350

SEGMENTS = 144


def cm(mm: float) -> float:
    """Fusion API Point3D coordinates use centimeters internally."""
    return mm / 10.0


def clip_polygon(
    points: list[tuple[float, float]],
    axis: int,
    threshold: float,
    keep_greater: bool,
) -> list[tuple[float, float]]:
    if not points:
        return []

    result: list[tuple[float, float]] = []
    previous = points[-1]
    previous_inside = (
        previous[axis] >= threshold
        if keep_greater
        else previous[axis] <= threshold
    )

    for current in points:
        current_inside = (
            current[axis] >= threshold
            if keep_greater
            else current[axis] <= threshold
        )
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
) -> list[tuple[float, float]]:
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

    # Primary flat is toward table front (-Y); retain points behind its plane.
    points = clip_polygon(
        points,
        axis=1,
        threshold=center_y - primary_depth - primary_relief,
        keep_greater=True,
    )

    # Secondary flat is on left (-X); retain points right of its datum plane.
    points = clip_polygon(
        points,
        axis=0,
        threshold=center_x - secondary_depth - secondary_relief,
        keep_greater=True,
    )
    return points


def offset_plane(
    component: adsk.fusion.Component,
    offset_mm: float,
    name: str,
) -> adsk.fusion.ConstructionPlane:
    planes = component.constructionPlanes
    plane_input = planes.createInput()
    plane_input.setByOffset(
        component.xYConstructionPlane,
        adsk.core.ValueInput.createByString(f"{offset_mm} mm"),
    )
    plane = planes.add(plane_input)
    plane.name = name
    return plane


def polygon_sketch(
    component: adsk.fusion.Component,
    plane: adsk.core.Base,
    points_mm: list[tuple[float, float]],
    name: str,
) -> adsk.fusion.Sketch:
    sketch = component.sketches.add(plane)
    sketch.name = name
    lines = sketch.sketchCurves.sketchLines
    points = [adsk.core.Point3D.create(cm(x), cm(y), 0) for x, y in points_mm]
    for index, point in enumerate(points):
        lines.addByTwoPoints(point, points[(index + 1) % len(points)])
    return sketch


def rectangle_points(x: float, y: float, width: float, height: float) -> list[tuple[float, float]]:
    return [
        (x, y),
        (x + width, y),
        (x + width, y + height),
        (x, y + height),
    ]


def beam_points(
    start: tuple[float, float],
    end: tuple[float, float],
    start_width: float,
    end_width: float,
) -> list[tuple[float, float]]:
    """Return a four-sided beam profile centered on a line segment."""
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = math.hypot(dx, dy)
    if length <= 0:
        raise ValueError("Beam endpoints must be different")
    unit_nx = -dy / length
    unit_ny = dx / length
    start_nx = unit_nx * start_width / 2.0
    start_ny = unit_ny * start_width / 2.0
    end_nx = unit_nx * end_width / 2.0
    end_ny = unit_ny * end_width / 2.0
    return [
        (start[0] + start_nx, start[1] + start_ny),
        (end[0] + end_nx, end[1] + end_ny),
        (end[0] - end_nx, end[1] - end_ny),
        (start[0] - start_nx, start[1] - start_ny),
    ]


def vertical_capsule_points(
    center_x: float,
    start_center_y: float,
    end_center_y: float,
    width: float,
    segments_per_cap: int = 24,
) -> list[tuple[float, float]]:
    """Return a vertical round-ended slot polygon."""
    if end_center_y < start_center_y:
        raise ValueError("Capsule end must not precede its start")
    radius = width / 2.0
    points = [
        (center_x - radius, start_center_y),
        (center_x - radius, end_center_y),
    ]
    for index in range(1, segments_per_cap + 1):
        angle = math.pi - index * math.pi / segments_per_cap
        points.append(
            (
                center_x + radius * math.cos(angle),
                end_center_y + radius * math.sin(angle),
            )
        )
    points.append((center_x + radius, start_center_y))
    for index in range(1, segments_per_cap):
        angle = -index * math.pi / segments_per_cap
        points.append(
            (
                center_x + radius * math.cos(angle),
                start_center_y + radius * math.sin(angle),
            )
        )
    return points


def extrude_polygon(
    component: adsk.fusion.Component,
    plane: adsk.core.Base,
    points_mm: list[tuple[float, float]],
    distance_mm: float,
    operation: int,
    name: str,
) -> adsk.fusion.ExtrudeFeature:
    sketch = polygon_sketch(component, plane, points_mm, f"{name} Sketch")
    if sketch.profiles.count != 1:
        raise RuntimeError(f"{name}: expected one closed profile, found {sketch.profiles.count}")

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


def loft_polygons(
    component: adsk.fusion.Component,
    first_plane: adsk.core.Base,
    first_points_mm: list[tuple[float, float]],
    second_plane: adsk.core.Base,
    second_points_mm: list[tuple[float, float]],
    operation: int,
    name: str,
) -> adsk.fusion.LoftFeature:
    first_sketch = polygon_sketch(component, first_plane, first_points_mm, f"{name} Lower Sketch")
    second_sketch = polygon_sketch(component, second_plane, second_points_mm, f"{name} Upper Sketch")
    if first_sketch.profiles.count != 1 or second_sketch.profiles.count != 1:
        raise RuntimeError(f"{name}: expected one closed profile on each loft plane")

    lofts = component.features.loftFeatures
    loft_input = lofts.createInput(operation)
    loft_input.loftSections.add(first_sketch.profiles.item(0))
    loft_input.loftSections.add(second_sketch.profiles.item(0))
    loft_input.isSolid = True
    feature = lofts.add(loft_input)
    feature.name = name
    first_sketch.isVisible = False
    second_sketch.isVisible = False
    return feature


def add_user_parameter(
    design: adsk.fusion.Design,
    name: str,
    value_mm: float,
    comment: str,
) -> None:
    design.userParameters.add(
        name,
        adsk.core.ValueInput.createByString(f"{value_mm} mm"),
        "mm",
        comment,
    )


def build_model(design: adsk.fusion.Design) -> None:
    component = design.rootComponent

    if abs(INSIDE_STOP_SPAN - (TABLE_WIDTH + 2 * INDEX_OFFSET)) > 1e-9:
        raise RuntimeError("Inside stop span must equal table width plus 50 mm")

    # Named dimensions remain visible in Fusion's Parameters dialog.
    add_user_parameter(design, "tableWidth", TABLE_WIDTH, "Assumed table width")
    add_user_parameter(design, "insideStopSpan", INSIDE_STOP_SPAN, "Side-stop inside span")
    add_user_parameter(design, "baseThickness", BASE_THICKNESS, "Wafer support base")
    add_user_parameter(design, "sidewallHeight", SIDEWALL_HEIGHT, "Wall above support base")
    add_user_parameter(design, "tableLipDrop", TABLE_LIP_DROP, "Table contact below base")
    add_user_parameter(design, "strutWidth", STRUT_WIDTH, "PLA top-rib width")
    add_user_parameter(design, "strutHeight", STRUT_HEIGHT, "PLA top-rib height above base")
    add_user_parameter(design, "ribEndHeight", SIDEWALL_HEIGHT, "Rib height where it meets nest")
    add_user_parameter(design, "pickupChamfer", PICKUP_CHAMFER, "45 degree pickup-slot bevel")
    add_user_parameter(design, "pickupGapWidth", PICKUP_GAP_WIDTH, "Primary-flat pickup opening")

    xy_plane = component.xYConstructionPlane
    wall_plane = offset_plane(component, BASE_THICKNESS, "Top of 2 mm Base")
    rib_shoulder_plane = offset_plane(
        component,
        BASE_THICKNESS + SIDEWALL_HEIGHT,
        "Rib Shoulder at Nest Wall Height",
    )
    rib_top_plane = offset_plane(
        component,
        BASE_THICKNESS + STRUT_HEIGHT,
        "Top of 8 mm Ribs",
    )
    pickup_top_plane = offset_plane(
        component,
        BASE_THICKNESS + STRUT_HEIGHT + 0.2,
        "Top of Pickup Chamfer Cut",
    )
    lip_plane = offset_plane(component, -TABLE_LIP_DROP, "Bottom of 5 mm Table Lips")

    # Two overlapping 2 mm base lobes.
    for index, nest_y in enumerate((FRONT_NEST_Y, REAR_NEST_Y)):
        outer = wafer_polygon(
            NEST_CENTER_X,
            nest_y,
            radial_offset=SIDEWALL_THICKNESS,
            primary_relief=SIDEWALL_THICKNESS,
            secondary_relief=SIDEWALL_THICKNESS,
        )
        operation = (
            adsk.fusion.FeatureOperations.NewBodyFeatureOperation
            if index == 0
            else adsk.fusion.FeatureOperations.JoinFeatureOperation
        )
        extrude_polygon(
            component,
            xy_plane,
            outer,
            BASE_THICKNESS,
            operation,
            f"{'Front' if index == 0 else 'Rear'} Nest Base",
        )

    # Continue the 2 mm structural sheet from the front table bar through the
    # lower nest and up to the horizontal centerline of the upper/rear nest.
    # It remains exactly one wafer diameter wide.
    wafer_radius = WAFER_DIAMETER / 2.0
    primary_flat_depth = math.sqrt(
        wafer_radius**2 - (PRIMARY_FLAT_LENGTH / 2.0) ** 2
    )
    base_bridge = rectangle_points(
        NEST_CENTER_X - BASE_BRIDGE_WIDTH / 2.0,
        -FRONT_BAR_BRIDGE_OVERLAP,
        BASE_BRIDGE_WIDTH,
        REAR_NEST_Y + FRONT_BAR_BRIDGE_OVERLAP,
    )
    extrude_polygon(
        component,
        xy_plane,
        base_bridge,
        BASE_THICKNESS,
        adsk.fusion.FeatureOperations.JoinFeatureOperation,
        "100 mm Structural Sheet to Rear Nest Centerline",
    )

    # Add full outer wall solids from Z=2.0 to Z=3.25.
    for index, nest_y in enumerate((FRONT_NEST_Y, REAR_NEST_Y)):
        outer = wafer_polygon(
            NEST_CENTER_X,
            nest_y,
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
            f"{'Front' if index == 0 else 'Rear'} Outer Wall",
        )

    # Front and side table-contact bars extend 5 mm below the table surface
    # and continue through the 2 mm base so every feature is one solid body.
    lip_extrude = TABLE_LIP_DROP + BASE_THICKNESS
    bars = [
        (
            "Front Table Bar",
            rectangle_points(
                -SIDE_BAR_THICKNESS,
                -FRONT_BAR_DEPTH,
                INSIDE_STOP_SPAN + 2 * SIDE_BAR_THICKNESS,
                FRONT_BAR_DEPTH,
            ),
            lip_extrude,
        ),
        (
            "Left Table Bar",
            rectangle_points(
                -SIDE_BAR_THICKNESS,
                -FRONT_BAR_DEPTH,
                SIDE_BAR_THICKNESS,
                SIDE_CONTACT_LENGTH + FRONT_BAR_DEPTH,
            ),
            lip_extrude + STRUT_HEIGHT,
        ),
        (
            "Right Table Bar",
            rectangle_points(
                INSIDE_STOP_SPAN,
                -FRONT_BAR_DEPTH,
                SIDE_BAR_THICKNESS,
                SIDE_CONTACT_LENGTH + FRONT_BAR_DEPTH,
            ),
            lip_extrude + STRUT_HEIGHT,
        ),
    ]
    for name, points, height in bars:
        extrude_polygon(
            component,
            lip_plane,
            points,
            height,
            adsk.fusion.FeatureOperations.JoinFeatureOperation,
            name,
        )

    # Eight-by-eight top ribs stiffen the long PLA span. The front rib is
    # continuous; four diagonals transfer load from the two nest lobes into
    # the short table-contact arms.
    outer_radius = WAFER_DIAMETER / 2.0 + SIDEWALL_THICKNESS
    rib_attach_dy = 20.0
    rib_attach_dx = math.sqrt(outer_radius**2 - rib_attach_dy**2)
    left_attach_x = NEST_CENTER_X - rib_attach_dx
    right_attach_x = NEST_CENTER_X + rib_attach_dx
    attach_dy = rib_attach_dy

    extrude_polygon(
        component,
        wall_plane,
        rectangle_points(
            -SIDE_BAR_THICKNESS,
            -FRONT_BAR_DEPTH,
            INSIDE_STOP_SPAN + 2 * SIDE_BAR_THICKNESS,
            STRUT_WIDTH,
        ),
        STRUT_HEIGHT,
        adsk.fusion.FeatureOperations.JoinFeatureOperation,
        "Continuous Front Top Rib",
    )

    diagonal_ribs = [
        (
            "Left Front Diagonal Rib",
            (0.0, -FRONT_BAR_DEPTH + STRUT_WIDTH / 2.0),
            (left_attach_x, FRONT_NEST_Y - attach_dy),
        ),
        (
            "Right Front Diagonal Rib",
            (INSIDE_STOP_SPAN, -FRONT_BAR_DEPTH + STRUT_WIDTH / 2.0),
            (right_attach_x, FRONT_NEST_Y - attach_dy),
        ),
        (
            "Left Rear Diagonal Rib",
            (0.0, -FRONT_BAR_DEPTH + STRUT_WIDTH / 2.0),
            (left_attach_x, REAR_NEST_Y + attach_dy),
        ),
        (
            "Right Rear Diagonal Rib",
            (INSIDE_STOP_SPAN, -FRONT_BAR_DEPTH + STRUT_WIDTH / 2.0),
            (right_attach_x, REAR_NEST_Y + attach_dy),
        ),
    ]
    taper_run = STRUT_HEIGHT - SIDEWALL_HEIGHT
    for name, start, end in diagonal_ribs:
        full_footprint = beam_points(start, end, STRUT_WIDTH, STRUT_WIDTH)
        extrude_polygon(
            component,
            wall_plane,
            full_footprint,
            SIDEWALL_HEIGHT,
            adsk.fusion.FeatureOperations.JoinFeatureOperation,
            f"{name} Lower Web",
        )

        dx = end[0] - start[0]
        dy = end[1] - start[1]
        length = math.hypot(dx, dy)
        upper_end = (
            end[0] - dx * taper_run / length,
            end[1] - dy * taper_run / length,
        )
        upper_footprint = beam_points(start, upper_end, STRUT_WIDTH, STRUT_WIDTH)
        loft_polygons(
            component,
            rib_shoulder_plane,
            full_footprint,
            rib_top_plane,
            upper_footprint,
            adsk.fusion.FeatureOperations.JoinFeatureOperation,
            f"{name} 45 Degree Thickness Taper",
        )

    # Cut the pockets last and through the full rib height. This guarantees
    # that wide reinforcement can never protrude into the wafer seating area.
    pocket_cut_height = max(SIDEWALL_HEIGHT, STRUT_HEIGHT) + 0.1
    for index, nest_y in enumerate((FRONT_NEST_Y, REAR_NEST_Y)):
        pocket = wafer_polygon(
            NEST_CENTER_X,
            nest_y,
            radial_offset=RADIAL_CLEARANCE,
            primary_relief=PRIMARY_FLAT_CLEARANCE,
            secondary_relief=SECONDARY_DATUM_CLEARANCE,
        )
        extrude_polygon(
            component,
            wall_plane,
            pocket,
            pocket_cut_height,
            adsk.fusion.FeatureOperations.CutFeatureOperation,
            f"{'Front' if index == 0 else 'Rear'} Wafer Pocket - Final Clearance",
        )

    # Open the center of the accessible primary-flat wall and its top rib for
    # wafer pickup. The cut starts at Z=2, leaving the support floor and the
    # continuous below-base table-contact bar intact.
    nominal_flat_y = FRONT_NEST_Y - primary_flat_depth
    pickup_bottom = vertical_capsule_points(
        NEST_CENTER_X,
        -FRONT_BAR_DEPTH,
        nominal_flat_y,
        PICKUP_GAP_WIDTH,
    )
    pickup_cut_expansion = PICKUP_CHAMFER + 0.2
    pickup_top = vertical_capsule_points(
        NEST_CENTER_X,
        -FRONT_BAR_DEPTH - pickup_cut_expansion,
        nominal_flat_y + pickup_cut_expansion,
        PICKUP_GAP_WIDTH + 2.0 * pickup_cut_expansion,
    )
    loft_polygons(
        component,
        wall_plane,
        pickup_bottom,
        pickup_top_plane,
        pickup_top,
        adsk.fusion.FeatureOperations.CutFeatureOperation,
        "20 mm Pickup Opening with Full-Height 45 Degree Bevel",
    )

    component.xYConstructionPlane.isLightBulbOn = False
    wall_plane.isLightBulbOn = False
    rib_shoulder_plane.isLightBulbOn = False
    rib_top_plane.isLightBulbOn = False
    pickup_top_plane.isLightBulbOn = False
    lip_plane.isLightBulbOn = False


def export_design(design: adsk.fusion.Design, output_directory: str) -> tuple[str, str, str]:
    export_manager = design.exportManager
    f3d_path = os.path.join(output_directory, "single_jig_wafer_indexer.f3d")
    step_path = os.path.join(output_directory, "single_jig_wafer_indexer.step")
    print_directory = os.path.join(os.path.dirname(output_directory), "print-files")
    os.makedirs(print_directory, exist_ok=True)
    stl_path = os.path.join(print_directory, "single_jig_wafer_indexer.stl")

    f3d_options = export_manager.createFusionArchiveExportOptions(f3d_path)
    if not export_manager.execute(f3d_options):
        raise RuntimeError("Fusion archive export failed")

    step_options = export_manager.createSTEPExportOptions(step_path)
    if not export_manager.execute(step_options):
        raise RuntimeError("STEP export failed")

    stl_options = export_manager.createSTLExportOptions(
        design.rootComponent,
        stl_path,
    )
    stl_options.isBinaryFormat = True
    stl_options.isOneFilePerBody = False
    stl_options.sendToPrintUtility = False
    stl_options.unitType = adsk.fusion.DistanceUnits.MillimeterDistanceUnits
    stl_options.meshRefinement = adsk.fusion.MeshRefinementSettings.MeshRefinementHigh
    if not export_manager.execute(stl_options):
        raise RuntimeError("STL export failed")

    return f3d_path, step_path, stl_path


def run(_context) -> None:
    app = adsk.core.Application.get()
    ui = app.userInterface
    try:
        document = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
        design = adsk.fusion.Design.cast(app.activeProduct)
        if not design:
            raise RuntimeError("Could not create a Fusion design")

        design.designType = adsk.fusion.DesignTypes.ParametricDesignType
        build_model(design)
        app.activeViewport.fit()

        output_directory = os.path.dirname(os.path.realpath(__file__))
        f3d_path, step_path, stl_path = export_design(design, output_directory)
        ui.messageBox(
            "Single-jig wafer indexer created.\n\n"
            f"Fusion archive:\n{f3d_path}\n\n"
            f"STEP file:\n{step_path}\n\n"
            f"High-quality binary STL:\n{stl_path}",
            "Wafer Indexer Complete",
        )
    except Exception:
        ui.messageBox(traceback.format_exc(), "Wafer Indexer Error")


def stop(_context) -> None:
    pass
