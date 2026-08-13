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
PIN_EDGE_FILL = 7.000            # solid material kept radially out from every dowel-hole edge
BOSS_DIAMETER = DOWEL_HOLE_DIAMETER + 2.0 * PIN_EDGE_FILL  # corner footprint that sets the flush plate edge
BOSS_HEIGHT = 0.000              # no raised boss; the thick base gives the engagement and a solid bore wall

# Platform and wafer nest. The plate is a tight bounding box computed in
# build_model, not centered on the nest: the corner bosses sit flush to the left
# and rear edges, and the right/front edges come in to the nest wall plus a small
# margin. There is no perimeter bar -- the 12.5 mm base is stiff enough on its own
# -- so PLATFORM_NEST_GAP is just the base kept beyond the nest wall where the nest
# (not a boss) is the outermost feature.
PLATFORM_NEST_GAP = 1.000
BASE_THICKNESS = 12.500          # thick slab to resist warping and give the dowel bore a solid wall
SIDEWALL_HEIGHT = 2.000          # tall enough to retain a short stack of wafers
SIDEWALL_THICKNESS = 3.000

# Small pickup tabs centered on the left and right edges, so the plate can be
# lifted straight off the pins without prying at the wafer or the nest wall. Each is
# a flange whose top is flush with the base top, leaving the base thickness minus the
# tab as the undercut to hook under.
SIDE_TAB_PROTRUSION = 10.000
SIDE_TAB_LENGTH = 24.000
SIDE_TAB_HEIGHT = 4.000  # flange thickness at the base top (was tied to the removed bar)

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
# platform onto the wafer without having to bridge the 2 mm wall. The wafer is
# pushed against the secondary flat and taped down; the pocket only locates it,
# it does not retain it. Both cut the raised wall only -- the solid base stays
# continuous under the wafer.
#
# Both are 15 mm. They stay separate constants so either can be tuned alone.
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

    # --- Minimal platform: a tight bounding box, not centered on the nest ---
    # Each edge sits at whichever is outermost: a corner boss (flush) or the nest
    # wall plus a small gap. No perimeter bar (the 12.5 mm base is stiff enough), so
    # the plate packs to the bosses on the left/rear and to the nest wall on the
    # right/front.
    _wafer_r = WAFER_DIAMETER / 2.0
    _primary_depth = math.sqrt(_wafer_r ** 2 - (PRIMARY_FLAT_LENGTH / 2.0) ** 2)
    _secondary_depth = math.sqrt(_wafer_r ** 2 - (SECONDARY_FLAT_LENGTH / 2.0) ** 2)
    _boss_reach = OUTER_PIN_PATTERN_SPAN / 2.0 + BOSS_DIAMETER / 2.0
    _nest_left = NEST_CENTER_X - _secondary_depth - SIDEWALL_THICKNESS
    _nest_right = NEST_CENTER_X + _wafer_r + SIDEWALL_THICKNESS
    _nest_rear = NEST_CENTER_Y + _wafer_r + SIDEWALL_THICKNESS
    _nest_front = NEST_CENTER_Y - _primary_depth - SIDEWALL_THICKNESS
    platform_left = min(-_boss_reach, _nest_left - PLATFORM_NEST_GAP)
    platform_right = max(_boss_reach, _nest_right + PLATFORM_NEST_GAP)
    platform_rear = max(_boss_reach, _nest_rear + PLATFORM_NEST_GAP)
    platform_front = min(-_boss_reach, _nest_front - PLATFORM_NEST_GAP)
    platform_size_x = platform_right - platform_left
    platform_size_y = platform_rear - platform_front

    for name, value, comment in (
        ("gridPitch", GRID_PITCH, "Table hole-grid pitch"),
        ("indexMove", INDEX_MOVE, "Two-grid-space indexing move"),
        ("outerPinPatternSpan", OUTER_PIN_PATTERN_SPAN, "Four-space outer pin span"),
        ("dowelDiameter", DOWEL_DIAMETER, "3/16 in steel locating dowel diameter"),
        ("dowelHoleDiameter", DOWEL_HOLE_DIAMETER, "Press-fit bore for the dowel"),
        ("bossHeight", BOSS_HEIGHT, "Dowel boss height above platform"),
        ("bossDiameter", BOSS_DIAMETER, "Corner fill footprint diameter"),
        ("platformSizeX", platform_size_x, "Overall plate width"),
        ("platformSizeY", platform_size_y, "Overall plate depth"),
        ("baseThickness", BASE_THICKNESS, "Wafer platform thickness"),
        ("sideTabHeight", SIDE_TAB_HEIGHT, "Pickup-tab flange thickness"),
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

    # Pickup tabs, one per side, centered on the nest Y center (the wafer center line). Each is a
    # SIDE_TAB_HEIGHT-thick flange whose top is flush with the base top, cantilevered
    # out past the plate edge. The open space below it (base thickness minus the tab)
    # is the undercut a fingernail or tweezer tip hooks into to lift the plate straight
    # off its pins, instead of prying against the wafer or the nest wall.
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
            -SIDE_TAB_HEIGHT,
            adsk.fusion.FeatureOperations.JoinFeatureOperation,
            tab_name,
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
        "2 mm Raised Wafer Nest",
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
