// Single-jig 100 mm wafer indexer
// Coordinate system:
//   X: right across table
//   Y: away from operator / toward table rear
//   Z: above table surface
//   Table front-left corner is (0, 0) in either indexed jig position.
//
// Open in OpenSCAD, press F6, then File > Export > Export as STL.
// Set render_2d = true to export a plan-view DXF instead.

$fn = 240;

// ---------- Measured machine geometry ----------
table_width = 200.000;
// Directly measured physical location of a cross commanded at (0, 0).
// The edge-derived reference center was (100.172, 107.672) mm.
field_center_x = 96.190;
field_center_y = 109.350;
full_field_size = 78.485;
qualified_field_size = 60.000;

// ---------- Four-position indexing geometry ----------
index_offset = 25.000;
index_travel = 2 * index_offset;              // 50.000
inside_stop_span = table_width + index_travel; // 250.000

// The nest center is measured from the left inside stop surface.
// When the left stop touches the table, wafer X = 121.190 mm.
// When the right stop touches the table, the jig shifts 50 mm to wafer X = 71.190 mm.
nest_center_x = field_center_x + index_offset; // 121.190; other X stop gives 71.190
front_nest_y = field_center_y - index_offset;  // 84.350
rear_nest_y = field_center_y + index_offset;   // 134.350

// ---------- Wafer geometry ----------
wafer_diameter = 100.000;
wafer_radius = wafer_diameter / 2;
primary_flat_length = 32.500;   // faces table front; clearance only
secondary_flat_length = 18.000; // left side; rotational datum

primary_flat_depth = sqrt(
    wafer_radius * wafer_radius -
    (primary_flat_length / 2) * (primary_flat_length / 2)
);
secondary_flat_depth = sqrt(
    wafer_radius * wafer_radius -
    (secondary_flat_length / 2) * (secondary_flat_length / 2)
);

// ---------- Printable fixture parameters ----------
base_thickness = 2.00;        // wafer rests on top of this base
sidewall_height = 1.25;       // wall height above wafer-support surface
sidewall_thickness = 3.00;
radial_clearance = 0.25;      // clearance on circular wafer edge
primary_flat_clearance = 0.30;
secondary_datum_clearance = 0.00; // tune after test print or use a shim
pickup_gap_width = 20.00;    // centered opening at accessible primary flat

front_bar_depth = 12.0;
side_bar_thickness = 8.0;
side_contact_length = 65.0;   // first 2.56 inches of either table side
table_lip_drop = 5.0;         // vertical table-contact surface below base
strut_width = 8.0;            // reinforced PLA top-rib width
strut_height = 8.0;           // reinforced PLA top-rib height above base
pickup_chamfer = 8.0;         // full-height 45 degree pickup-slot bevel

// Output controls.
render_2d = false;
show_machine_reference = true;

assert(abs(inside_stop_span - 250.000) < 0.001,
       "Inside stop span must be exactly 250.000 mm");
assert(abs(rear_nest_y - front_nest_y - 50.000) < 0.001,
       "Nest center spacing must be exactly 50.000 mm");

echo(str("Inside side-stop span: ", inside_stop_span, " mm"));
echo(str("Nest center X from left stop: ", nest_center_x, " mm"));
echo(str("Front/rear nest Y: ", front_nest_y, " / ", rear_nest_y, " mm"));
echo(str("Secondary-flat common datum X: ",
         nest_center_x - secondary_flat_depth, " mm"));


// Wafer profile: primary flat at front (-Y), secondary flat at left (-X).
module wafer_profile_2d(
    radial = 0,
    primary_clearance = 0,
    secondary_clearance = 0
) {
    intersection() {
        circle(r = wafer_radius + radial);

        // Keep material to the right of the left secondary-flat plane.
        translate([
            -secondary_flat_depth - secondary_clearance,
            -wafer_radius - radial - 2
        ])
            square([
                2 * wafer_radius + 2 * radial + 4,
                2 * wafer_radius + 2 * radial + 4
            ]);

        // Keep material behind the front primary-flat plane.
        translate([
            -wafer_radius - radial - 2,
            -primary_flat_depth - primary_clearance
        ])
            square([
                2 * wafer_radius + 2 * radial + 4,
                2 * wafer_radius + 2 * radial + 4
            ]);
    }
}


module both_nests_2d(
    radial = 0,
    primary_clearance = 0,
    secondary_clearance = 0
) {
    for (nest_y = [front_nest_y, rear_nest_y])
        translate([nest_center_x, nest_y])
            wafer_profile_2d(
                radial,
                primary_clearance,
                secondary_clearance
            );
}


module nest_plate() {
    // Two-millimeter figure-eight floor supporting the full wafer backside.
    linear_extrude(height = base_thickness)
        offset(delta = sidewall_thickness)
            both_nests_2d();

    // Walls rise 1.25 mm above the floor. Both nests share the same left
    // secondary-flat datum plane; the front primary flat receives clearance.
    translate([0, 0, base_thickness])
        linear_extrude(height = sidewall_height)
            difference() {
                offset(delta = sidewall_thickness)
                    both_nests_2d();
                both_nests_2d(
                    radial_clearance,
                    primary_flat_clearance,
                    secondary_datum_clearance
                );
            }
}


module edge_reference_frame() {
    // Front lip: its inside surface at Y=0 contacts the table front.
    translate([
        -side_bar_thickness,
        -front_bar_depth,
        -table_lip_drop
    ])
        cube([
            inside_stop_span + 2 * side_bar_thickness,
            front_bar_depth,
            table_lip_drop + base_thickness
        ]);

    // Left and right lips: inside faces are exactly 250.000 mm apart.
    translate([
        -side_bar_thickness,
        -front_bar_depth,
        -table_lip_drop
    ])
        cube([
            side_bar_thickness,
            side_contact_length + front_bar_depth,
            table_lip_drop + base_thickness + strut_height
        ]);

    translate([
        inside_stop_span,
        -front_bar_depth,
        -table_lip_drop
    ])
        cube([
            side_bar_thickness,
            side_contact_length + front_bar_depth,
            table_lip_drop + base_thickness + strut_height
        ]);
}


module beam_profile_2d(p1, p2, width) {
    hull() {
        translate(p1) circle(d = width);
        translate(p2) circle(d = width);
    }
}


module top_beam(p1, p2, width, height) {
    dx = p2[0] - p1[0];
    dy = p2[1] - p1[1];
    beam_length = sqrt(dx * dx + dy * dy);
    taper_height = height - sidewall_height;
    taper_start = [
        p2[0] - dx * taper_height / beam_length,
        p2[1] - dy * taper_height / beam_length
    ];

    // Constant-width lower web lands at the nest-wall height.
    translate([0, 0, base_thickness])
        linear_extrude(height = sidewall_height)
            beam_profile_2d(p1, p2, width);

    // Full-height constant-width portion before the 45 degree end cut.
    translate([0, 0, base_thickness + sidewall_height])
        linear_extrude(height = taper_height)
            beam_profile_2d(p1, taper_start, width);

    // Constant-width wedge: vertical drop equals horizontal run.
    hull() {
        translate([
            taper_start[0],
            taper_start[1],
            base_thickness + sidewall_height
        ])
            cylinder(d = width, h = taper_height);
        translate([
            p2[0],
            p2[1],
            base_thickness + sidewall_height
        ])
            cylinder(d = width, h = 0.01);
    }
}


module pickup_slot_2d(expansion = 0) {
    hull() {
        translate([
            nest_center_x,
            -front_bar_depth - expansion
        ])
            circle(d = pickup_gap_width + 2 * expansion);
        translate([
            nest_center_x,
            front_nest_y - primary_flat_depth + expansion
        ])
            circle(d = pickup_gap_width + 2 * expansion);
    }
}


module top_reinforcement() {
    outer_radius = wafer_radius + sidewall_thickness;
    attach_dy_nominal = 20.0;
    attach_dx_nominal = sqrt(
        outer_radius * outer_radius -
        attach_dy_nominal * attach_dy_nominal
    );
    attach_dx = attach_dx_nominal;
    attach_dy = attach_dy_nominal;

    // Continuous front rib, seated on the top face of the front datum bar.
    translate([
        -side_bar_thickness,
        -front_bar_depth,
        base_thickness
    ])
        cube([
            inside_stop_span + 2 * side_bar_thickness,
            strut_width,
            strut_height
        ]);

    // Four diagonals connect the nest lobes to the short side arms. The final
    // pocket cut trims their attachment caps flush with the wafer envelopes.
    top_beam(
        [0, -front_bar_depth + strut_width / 2],
        [nest_center_x - attach_dx, front_nest_y - attach_dy],
        strut_width,
        strut_height
    );
    top_beam(
        [inside_stop_span, -front_bar_depth + strut_width / 2],
        [nest_center_x + attach_dx, front_nest_y - attach_dy],
        strut_width,
        strut_height
    );
    top_beam(
        [0, -front_bar_depth + strut_width / 2],
        [nest_center_x - attach_dx, rear_nest_y + attach_dy],
        strut_width,
        strut_height
    );
    top_beam(
        [inside_stop_span, -front_bar_depth + strut_width / 2],
        [nest_center_x + attach_dx, rear_nest_y + attach_dy],
        strut_width,
        strut_height
    );
}


module top_reinforcement_plan_2d() {
    outer_radius = wafer_radius + sidewall_thickness;
    attach_dy_nominal = 20.0;
    attach_dx_nominal = sqrt(
        outer_radius * outer_radius -
        attach_dy_nominal * attach_dy_nominal
    );
    attach_dx = attach_dx_nominal;
    attach_dy = attach_dy_nominal;

    translate([-side_bar_thickness, -front_bar_depth])
        square([
            inside_stop_span + 2 * side_bar_thickness,
            strut_width
        ]);

    hull() {
        translate([0, -front_bar_depth + strut_width / 2])
            circle(d = strut_width);
        translate([nest_center_x - attach_dx, front_nest_y - attach_dy])
            circle(d = strut_width);
    }
    hull() {
        translate([inside_stop_span, -front_bar_depth + strut_width / 2])
            circle(d = strut_width);
        translate([nest_center_x + attach_dx, front_nest_y - attach_dy])
            circle(d = strut_width);
    }
    hull() {
        translate([0, -front_bar_depth + strut_width / 2])
            circle(d = strut_width);
        translate([nest_center_x - attach_dx, rear_nest_y + attach_dy])
            circle(d = strut_width);
    }
    hull() {
        translate([inside_stop_span, -front_bar_depth + strut_width / 2])
            circle(d = strut_width);
        translate([nest_center_x + attach_dx, rear_nest_y + attach_dy])
            circle(d = strut_width);
    }
}


module jig() {
    difference() {
        union() {
            nest_plate();
            edge_reference_frame();
            top_reinforcement();
        }

        // Re-cut pockets through the complete rib height so reinforcement
        // never projects into either wafer seating envelope.
        translate([0, 0, base_thickness])
            linear_extrude(height = strut_height + 0.1)
                both_nests_2d(
                    radial_clearance,
                    primary_flat_clearance,
                    secondary_datum_clearance
                );

        // Full-height 45 degree bevel around the round-ended pickup slot. The
        // 2 mm support floor and below-base table-contact bar stay continuous.
        hull() {
            translate([0, 0, base_thickness])
                linear_extrude(height = 0.01)
                    pickup_slot_2d(0);
            translate([0, 0, base_thickness + strut_height + 0.2])
                linear_extrude(height = 0.01)
                    pickup_slot_2d(pickup_chamfer + 0.2);
        }
    }
}


module jig_plan_2d() {
    difference() {
        union() {
            offset(delta = sidewall_thickness)
                both_nests_2d();
            translate([-side_bar_thickness, -front_bar_depth])
                square([
                    inside_stop_span + 2 * side_bar_thickness,
                    front_bar_depth
                ]);
            translate([-side_bar_thickness, -front_bar_depth])
                square([
                    side_bar_thickness,
                    side_contact_length + front_bar_depth
                ]);
            translate([inside_stop_span, -front_bar_depth])
                square([
                    side_bar_thickness,
                    side_contact_length + front_bar_depth
                ]);
            top_reinforcement_plan_2d();
        }

        both_nests_2d(
            radial_clearance,
            primary_flat_clearance,
            secondary_datum_clearance
        );

        pickup_slot_2d(pickup_chamfer);
    }
}


module machine_reference() {
    // Background-only reference; '%' objects are not exported.
    %color([0.70, 0.72, 0.75, 0.35])
        translate([0, 0, -2])
            cube([table_width, 155, 2]);

    // Fixed 78.485 mm usable galvo field.
    %color([0.15, 0.55, 0.95, 0.20])
        translate([
            field_center_x - full_field_size / 2,
            field_center_y - full_field_size / 2,
            base_thickness + sidewall_height + 0.5
        ])
            cube([full_field_size, full_field_size, 0.4]);

    // Qualified central 60 mm field.
    %color([0.20, 0.75, 0.35, 0.25])
        translate([
            field_center_x - qualified_field_size / 2,
            field_center_y - qualified_field_size / 2,
            base_thickness + sidewall_height + 1.0
        ])
            cube([qualified_field_size, qualified_field_size, 0.4]);
}


if (render_2d) {
    jig_plan_2d();
} else {
    jig();
    if (show_machine_reference)
        machine_reference();
}
