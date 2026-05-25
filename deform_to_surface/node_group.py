"""Construction of the Geometry Nodes group that backs the modifier.

High-level algorithm
====================

For every input point P:

1. Sample the closest interpolated position ``S_T`` and smooth normal
   ``N_T`` on the live Target surface using ``Sample Nearest Surface``.
2. If a Rest Target is bound, sample the closest interpolated position
   ``S_R`` and smooth normal ``N_R`` on the Rest Target as well.
3. Decompose the rest-pose offset ``P - S_R`` into the local tangent
   frame at ``S_R`` (signed normal distance + two tangent components).
4. Reconstruct that same offset in the live Target's tangent frame at
   ``S_T`` and add it to ``S_T`` to get the bound position. This is the
   same idea as Blender's built-in *Surface Deform* modifier: the
   geometry rides along the surface as the surface bends and stretches.
5. If no Rest Target is bound, fall back to plain projection onto the
   surface with an optional offset along the surface normal.
6. Blend with the original position by ``Factor``, optionally average
   the result over neighbouring vertices for extra smoothness, and only
   move points that pass the ``Selection`` mask.

The tangent frame at a surface normal ``N`` is built from a stable
reference vector — Z when ``N`` is not near-vertical, X otherwise —
which keeps the frame continuous across the surface and consistent
between rest and target as long as the surface does not contain a
large set of perfectly vertical normals.
"""

from __future__ import annotations

import bpy

NODE_GROUP_NAME = "Deform To Surface"


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def _new_socket(ng, *, name, in_out, socket_type, description="", default=None,
                min_value=None, max_value=None, subtype=None):
    sock = ng.interface.new_socket(
        name=name, in_out=in_out, socket_type=socket_type
    )
    if description:
        sock.description = description
    if subtype is not None and hasattr(sock, "subtype"):
        try:
            sock.subtype = subtype
        except (TypeError, AttributeError):
            pass
    if default is not None and hasattr(sock, "default_value"):
        try:
            sock.default_value = default
        except (TypeError, AttributeError):
            pass
    if min_value is not None and hasattr(sock, "min_value"):
        try:
            sock.min_value = min_value
        except (TypeError, AttributeError):
            pass
    if max_value is not None and hasattr(sock, "max_value"):
        try:
            sock.max_value = max_value
        except (TypeError, AttributeError):
            pass
    return sock


def _clear(ng):
    for node in list(ng.nodes):
        ng.nodes.remove(node)
    for item in list(ng.interface.items_tree):
        ng.interface.remove(item)


def _enabled_socket(sockets, name, sock_type=None):
    """Find the *enabled* socket with the given display name.

    Several Geometry Nodes (Mix, Sample Nearest Surface, Blur Attribute,
    Switch, …) declare multiple sockets with the same display name —
    one per data type — and enable only the one matching the node's
    ``data_type``/``input_type`` setting. ``inputs.get(name)`` returns
    the first match regardless of enable state, so we have to scan.
    """
    for s in sockets:
        if not s.enabled:
            continue
        if s.name != name:
            continue
        if sock_type is not None and s.type != sock_type:
            continue
        return s
    raise RuntimeError(
        f"No enabled socket {name!r}"
        + (f" of type {sock_type!r}" if sock_type else "")
        + f"; have {[(s.name, s.type, s.enabled) for s in sockets]!r}"
    )


def _switch_sockets(switch_node):
    """Return (condition, false, true, output) sockets for a Switch node.

    The Switch node has one (False, True, Output) triple per data type
    and enables only the one matching ``input_type``. The Switch input
    socket (index 0) is the boolean condition and is always enabled.
    """
    cond = switch_node.inputs[0]
    # Pick the enabled False/True inputs.
    false = true = None
    for s in switch_node.inputs:
        if not s.enabled or s is cond:
            continue
        if s.name == "False" and false is None:
            false = s
        elif s.name == "True" and true is None:
            true = s
    if false is None or true is None:
        raise RuntimeError(
            f"Switch node missing enabled False/True sockets; have "
            f"{[(s.name, s.enabled) for s in switch_node.inputs]!r}"
        )
    out = None
    for sock in switch_node.outputs:
        if sock.enabled:
            out = sock
            break
    if out is None:
        raise RuntimeError("Switch node has no enabled output")
    return cond, false, true, out


def _vector_math(nodes, op, location, *, scale=None):
    n = nodes.new("ShaderNodeVectorMath")
    n.operation = op
    n.location = location
    if scale is not None:
        # input 3 is the scalar "Scale" socket on SCALE/SCALE-like ops.
        n.inputs[3].default_value = scale
    return n


def _math(nodes, op, location, *, value=None):
    n = nodes.new("ShaderNodeMath")
    n.operation = op
    n.location = location
    if value is not None:
        n.inputs[1].default_value = value
    return n


def _new_switch(nodes, input_type, label, location):
    s = nodes.new("GeometryNodeSwitch")
    s.input_type = input_type
    s.label = label
    s.location = location
    return s


def _new_sample_nearest_surface(nodes, location, label=""):
    """Create a Sample Nearest Surface node sampling vector data."""
    n = nodes.new("GeometryNodeSampleNearestSurface")
    if hasattr(n, "data_type"):
        n.data_type = "FLOAT_VECTOR"
    n.location = location
    if label:
        n.label = label
    return n


# ──────────────────────────────────────────────────────────────────────
# Tangent-frame builder
# ──────────────────────────────────────────────────────────────────────

def _build_tangent_frame(nodes, links, normal_socket, location, label_prefix):
    """Build a stable orthonormal tangent frame from a normal field.

    Returns ``(t1_socket, t2_socket)``. The reference vector is Z when the
    normal is not near-vertical, X otherwise, which keeps the frame
    continuous and consistent across rest/target as long as the surface
    is not dominated by perfectly vertical normals.
    """
    x, y = location

    # Cross with Z.
    cross_z = _vector_math(nodes, "CROSS_PRODUCT", (x, y))
    cross_z.label = f"{label_prefix} N x Z"
    cross_z.inputs[1].default_value = (0.0, 0.0, 1.0)
    links.new(normal_socket, cross_z.inputs[0])

    # Length of N x Z (small ↔ N is near ±Z).
    len_z = _vector_math(nodes, "LENGTH", (x + 200, y))
    links.new(cross_z.outputs["Vector"], len_z.inputs[0])

    # Compare length > 0.1: stable enough to use Z reference.
    cmp_z = _math(nodes, "GREATER_THAN", (x + 380, y), value=0.1)
    links.new(len_z.outputs["Value"], cmp_z.inputs[0])

    # Cross with X (fallback reference).
    cross_x = _vector_math(nodes, "CROSS_PRODUCT", (x, y - 200))
    cross_x.label = f"{label_prefix} N x X"
    cross_x.inputs[1].default_value = (1.0, 0.0, 0.0)
    links.new(normal_socket, cross_x.inputs[0])

    # Pick the longer of the two cross results.
    sw_t1 = _new_switch(nodes, "VECTOR", f"{label_prefix} t1 raw", (x + 560, y - 80))
    cond, f, t, _ = _switch_sockets(sw_t1)
    links.new(cmp_z.outputs["Value"], cond)
    links.new(cross_x.outputs["Vector"], f)
    links.new(cross_z.outputs["Vector"], t)

    # Normalize t1.
    t1_norm = _vector_math(nodes, "NORMALIZE", (x + 760, y - 80))
    for sock in sw_t1.outputs:
        if sock.enabled:
            links.new(sock, t1_norm.inputs[0])
            break

    # t2 = N x t1 (already unit since N and t1 are unit and orthogonal).
    t2 = _vector_math(nodes, "CROSS_PRODUCT", (x + 960, y - 80))
    t2.label = f"{label_prefix} t2 = N x t1"
    links.new(normal_socket, t2.inputs[0])
    links.new(t1_norm.outputs["Vector"], t2.inputs[1])

    return t1_norm.outputs["Vector"], t2.outputs["Vector"]


# ──────────────────────────────────────────────────────────────────────
# Sample-on-surface block
# ──────────────────────────────────────────────────────────────────────

def _sample_surface(nodes, links, mesh_socket, sample_pos_socket, location, label):
    """Sample interpolated Position and Normal at the closest surface point.

    Returns ``(position_out, normal_out, is_valid_out)``.
    """
    x, y = location

    # Source-mesh fields to sample.
    pos_field = nodes.new("GeometryNodeInputPosition")
    pos_field.location = (x - 220, y + 120)
    pos_field.label = f"{label} src Position"

    nor_field = nodes.new("GeometryNodeInputNormal")
    nor_field.location = (x - 220, y - 60)
    nor_field.label = f"{label} src Normal"

    sns_pos = _new_sample_nearest_surface(nodes, (x, y + 120), f"{label} sample Pos")
    sns_nor = _new_sample_nearest_surface(nodes, (x, y - 80), f"{label} sample Nor")

    for sns, field in ((sns_pos, pos_field), (sns_nor, nor_field)):
        links.new(mesh_socket, sns.inputs["Mesh"])
        # Value to sample: provided by the source-mesh field. The node
        # exposes one "Value" socket per data type and enables only the
        # one matching ``data_type`` (set to FLOAT_VECTOR above).
        val_in = _enabled_socket(sns.inputs, "Value", sock_type="VECTOR")
        links.new(field.outputs[0], val_in)
        links.new(sample_pos_socket, sns.inputs["Sample Position"])

    pos_out = _enabled_socket(sns_pos.outputs, "Value", sock_type="VECTOR")
    nor_out = _enabled_socket(sns_nor.outputs, "Value", sock_type="VECTOR")

    # Re-normalize the sampled normal (vertex-interpolated normals can
    # have non-unit length on heavily curved surfaces).
    nor_norm = _vector_math(nodes, "NORMALIZE", (x + 220, y - 80))
    links.new(nor_out, nor_norm.inputs[0])

    # Validity flag (any of the two samples is enough; both should be
    # equivalent since the mesh is the same).
    is_valid = sns_pos.outputs.get("Is Valid")
    if is_valid is None:
        # Older node versions: assume valid.
        is_valid_const = nodes.new("FunctionNodeInputBool")
        is_valid_const.location = (x + 220, y + 220)
        is_valid_const.boolean = True
        is_valid = is_valid_const.outputs[0]

    return pos_out, nor_norm.outputs["Vector"], is_valid


# ──────────────────────────────────────────────────────────────────────
# Node group
# ──────────────────────────────────────────────────────────────────────

def ensure_node_group(force_rebuild: bool = False) -> bpy.types.NodeTree:
    """Create or refresh the Deform To Surface geometry node tree."""

    ng = bpy.data.node_groups.get(NODE_GROUP_NAME)
    if ng is not None and not force_rebuild:
        ng.is_modifier = True
        return ng

    if ng is None:
        ng = bpy.data.node_groups.new(NODE_GROUP_NAME, "GeometryNodeTree")
    else:
        _clear(ng)

    ng.is_modifier = True

    # ── Interface ──────────────────────────────────────────────────────
    _new_socket(
        ng, name="Geometry", in_out="INPUT",
        socket_type="NodeSocketGeometry",
        description="Geometry coming from the previous modifier",
    )
    _new_socket(
        ng, name="Target", in_out="INPUT",
        socket_type="NodeSocketObject",
        description="Live target surface — geometry is projected onto this object",
    )
    _new_socket(
        ng, name="Rest Target", in_out="INPUT",
        socket_type="NodeSocketObject",
        description=(
            "Optional rest-pose snapshot of the target. When set together "
            "with Use Bind, the geometry preserves its relative offset to "
            "the rest surface and follows the live Target's deformations"
        ),
    )
    _new_socket(
        ng, name="Use Bind", in_out="INPUT",
        socket_type="NodeSocketBool",
        description=(
            "Treat the rest-pose offset as a bound deformation. Disable "
            "for a plain projection onto Target's surface"
        ),
        default=False,
    )
    _new_socket(
        ng, name="Factor", in_out="INPUT",
        socket_type="NodeSocketFloat",
        description="0 = keep original position, 1 = full deformation",
        default=1.0, min_value=0.0, max_value=1.0, subtype="FACTOR",
    )
    _new_socket(
        ng, name="Normal Offset", in_out="INPUT",
        socket_type="NodeSocketFloat",
        description=(
            "Extra signed offset along the target surface normal. "
            "Positive pushes outward, negative pushes inward"
        ),
        default=0.0, subtype="DISTANCE",
    )
    _new_socket(
        ng, name="Strength", in_out="INPUT",
        socket_type="NodeSocketFloat",
        description=(
            "Scales the bound tangent-frame offset. 1 keeps the rest "
            "relief intact, 0 collapses the geometry onto the surface"
        ),
        default=1.0, min_value=0.0, max_value=4.0, subtype="FACTOR",
    )
    _new_socket(
        ng, name="Smooth Iterations", in_out="INPUT",
        socket_type="NodeSocketInt",
        description=(
            "Number of Blur Attribute passes applied to the projected "
            "position. Larger values give smoother wrapping but lose "
            "fine detail"
        ),
        default=0, min_value=0, max_value=64,
    )
    _new_socket(
        ng, name="Smooth Weight", in_out="INPUT",
        socket_type="NodeSocketFloat",
        description="Per-iteration blur weight (0 = no smoothing, 1 = max)",
        default=1.0, min_value=0.0, max_value=1.0, subtype="FACTOR",
    )
    _new_socket(
        ng, name="Selection", in_out="INPUT",
        socket_type="NodeSocketBool",
        description="Only deform points where the selection is true",
        default=True,
    )
    _new_socket(
        ng, name="Geometry", in_out="OUTPUT",
        socket_type="NodeSocketGeometry",
    )

    # ── Nodes ──────────────────────────────────────────────────────────
    nodes = ng.nodes
    links = ng.links

    n_in = nodes.new("NodeGroupInput")
    n_in.location = (-2000, 0)
    n_out = nodes.new("NodeGroupOutput")
    n_out.location = (2400, 0)

    # Object Info for Target and Rest Target. Both transform into the
    # modifier-object's local space so positions can be compared
    # directly with the input geometry.
    n_target = nodes.new("GeometryNodeObjectInfo")
    n_target.transform_space = "RELATIVE"
    n_target.location = (-1800, 350)
    n_target.label = "Target"

    n_rest = nodes.new("GeometryNodeObjectInfo")
    n_rest.transform_space = "RELATIVE"
    n_rest.location = (-1800, -350)
    n_rest.label = "Rest Target"

    links.new(n_in.outputs["Target"], n_target.inputs["Object"])
    links.new(n_in.outputs["Rest Target"], n_rest.inputs["Object"])

    n_position = nodes.new("GeometryNodeInputPosition")
    n_position.location = (-1800, 80)
    n_position.label = "Input Position"

    # Sample target and rest surfaces.
    tgt_pos, tgt_nor, tgt_valid = _sample_surface(
        nodes, links,
        mesh_socket=n_target.outputs["Geometry"],
        sample_pos_socket=n_position.outputs["Position"],
        location=(-1400, 350),
        label="Target",
    )
    rest_pos, rest_nor, rest_valid = _sample_surface(
        nodes, links,
        mesh_socket=n_rest.outputs["Geometry"],
        sample_pos_socket=n_position.outputs["Position"],
        location=(-1400, -350),
        label="Rest",
    )

    # ── Tangent frames at the sampled surface points ───────────────────
    t1_R, t2_R = _build_tangent_frame(
        nodes, links, rest_nor,
        location=(-900, -350), label_prefix="Rest",
    )
    t1_T, t2_T = _build_tangent_frame(
        nodes, links, tgt_nor,
        location=(-900, 350), label_prefix="Target",
    )

    # ── Rest-pose offset: O_R = P - S_R ────────────────────────────────
    offset_rest = _vector_math(nodes, "SUBTRACT", (-100, -350))
    offset_rest.label = "P - S_R"
    links.new(n_position.outputs["Position"], offset_rest.inputs[0])
    links.new(rest_pos, offset_rest.inputs[1])

    # Decompose O_R into (dn, dx, dy) using the rest tangent frame.
    dn = _vector_math(nodes, "DOT_PRODUCT", (120, -250))
    dn.label = "dn = O.N_R"
    links.new(offset_rest.outputs["Vector"], dn.inputs[0])
    links.new(rest_nor, dn.inputs[1])

    dx = _vector_math(nodes, "DOT_PRODUCT", (120, -370))
    dx.label = "dx = O.t1_R"
    links.new(offset_rest.outputs["Vector"], dx.inputs[0])
    links.new(t1_R, dx.inputs[1])

    dy = _vector_math(nodes, "DOT_PRODUCT", (120, -490))
    dy.label = "dy = O.t2_R"
    links.new(offset_rest.outputs["Vector"], dy.inputs[0])
    links.new(t2_R, dy.inputs[1])

    # Multiply scalar components by Strength so users can dial down the
    # rest relief without zeroing the projection.
    dn_s = _math(nodes, "MULTIPLY", (320, -250))
    dx_s = _math(nodes, "MULTIPLY", (320, -370))
    dy_s = _math(nodes, "MULTIPLY", (320, -490))
    for d_node, d_src in ((dn_s, dn), (dx_s, dx), (dy_s, dy)):
        links.new(d_src.outputs["Value"], d_node.inputs[0])
        links.new(n_in.outputs["Strength"], d_node.inputs[1])

    # ── Reconstruct in target tangent frame ────────────────────────────
    rec_n = _vector_math(nodes, "SCALE", (520, 100), scale=1.0)
    rec_n.label = "dn * N_T"
    links.new(tgt_nor, rec_n.inputs[0])
    links.new(dn_s.outputs["Value"], rec_n.inputs[3])

    rec_x = _vector_math(nodes, "SCALE", (520, -50), scale=1.0)
    rec_x.label = "dx * t1_T"
    links.new(t1_T, rec_x.inputs[0])
    links.new(dx_s.outputs["Value"], rec_x.inputs[3])

    rec_y = _vector_math(nodes, "SCALE", (520, -200), scale=1.0)
    rec_y.label = "dy * t2_T"
    links.new(t2_T, rec_y.inputs[0])
    links.new(dy_s.outputs["Value"], rec_y.inputs[3])

    sum_xy = _vector_math(nodes, "ADD", (740, -100))
    links.new(rec_x.outputs["Vector"], sum_xy.inputs[0])
    links.new(rec_y.outputs["Vector"], sum_xy.inputs[1])

    sum_all = _vector_math(nodes, "ADD", (940, 0))
    sum_all.label = "dn*N + dx*t1 + dy*t2"
    links.new(rec_n.outputs["Vector"], sum_all.inputs[0])
    links.new(sum_xy.outputs["Vector"], sum_all.inputs[1])

    # Bound position = S_T + reconstructed offset.
    bound_pos = _vector_math(nodes, "ADD", (1140, 100))
    bound_pos.label = "Bound position"
    links.new(tgt_pos, bound_pos.inputs[0])
    links.new(sum_all.outputs["Vector"], bound_pos.inputs[1])

    # Non-bound (plain projection) position. Naive closest-point
    # snapping collapses the input mesh against the surface and loses
    # all height: instead, project each input point onto the **line**
    # through S_T along N_T, which preserves the signed perpendicular
    # distance to the surface. Points above the surface stay above,
    # points below stay below, and only the tangent (parallel to the
    # surface) component is dropped:
    #
    #     d        = (P - S_T) · N_T
    #     new_pos  = S_T + (d + Normal Offset) * N_T
    plain_delta = _vector_math(nodes, "SUBTRACT", (200, 320))
    plain_delta.label = "P - S_T"
    links.new(n_position.outputs["Position"], plain_delta.inputs[0])
    links.new(tgt_pos, plain_delta.inputs[1])

    plain_d = _vector_math(nodes, "DOT_PRODUCT", (420, 320))
    plain_d.label = "d = (P - S_T) . N_T"
    links.new(plain_delta.outputs["Vector"], plain_d.inputs[0])
    links.new(tgt_nor, plain_d.inputs[1])

    plain_d_total = _math(nodes, "ADD", (620, 320))
    plain_d_total.label = "d + Normal Offset"
    links.new(plain_d.outputs["Value"], plain_d_total.inputs[0])
    links.new(n_in.outputs["Normal Offset"], plain_d_total.inputs[1])

    nor_offset_vec = _vector_math(nodes, "SCALE", (820, 280), scale=1.0)
    nor_offset_vec.label = "(d + Offset) * N_T"
    links.new(tgt_nor, nor_offset_vec.inputs[0])
    links.new(plain_d_total.outputs["Value"], nor_offset_vec.inputs[3])

    plain_pos = _vector_math(nodes, "ADD", (1140, 280))
    plain_pos.label = "Plain projected (perpendicular)"
    links.new(tgt_pos, plain_pos.inputs[0])
    links.new(nor_offset_vec.outputs["Vector"], plain_pos.inputs[1])

    # Pick bound vs plain based on Use Bind AND rest validity.
    use_bind_and = nodes.new("FunctionNodeBooleanMath")
    use_bind_and.operation = "AND"
    use_bind_and.label = "Use Bind AND Rest Valid"
    use_bind_and.location = (940, 200)
    links.new(n_in.outputs["Use Bind"], use_bind_and.inputs[0])
    links.new(rest_valid, use_bind_and.inputs[1])

    sw_bound = _new_switch(nodes, "VECTOR", "Bound or Plain", (1340, 180))
    cond, f, t, _ = _switch_sockets(sw_bound)
    links.new(use_bind_and.outputs["Boolean"], cond)
    links.new(plain_pos.outputs["Vector"], f)
    links.new(bound_pos.outputs["Vector"], t)
    sw_bound_out = None
    for sock in sw_bound.outputs:
        if sock.enabled:
            sw_bound_out = sock
            break

    # Factor blend: keep original ↔ go to projected position.
    mix = nodes.new("ShaderNodeMix")
    mix.data_type = "VECTOR"
    if hasattr(mix, "clamp_factor"):
        mix.clamp_factor = True
    mix.location = (1540, 180)

    # Locate enabled vector A/B/factor sockets.
    mix_a = mix_b = mix_factor = None
    for sock in mix.inputs:
        if not sock.enabled:
            continue
        if sock.type == "VECTOR" and sock.name == "A":
            mix_a = sock
        elif sock.type == "VECTOR" and sock.name == "B":
            mix_b = sock
        elif sock.type == "VALUE" and sock.name == "Factor":
            mix_factor = sock
    if mix_a is None or mix_b is None or mix_factor is None:
        raise RuntimeError("Could not locate Mix sockets for blending")

    links.new(n_in.outputs["Factor"], mix_factor)
    links.new(n_position.outputs["Position"], mix_a)
    links.new(sw_bound_out, mix_b)

    mix_result = None
    for sock in mix.outputs:
        if sock.enabled and sock.type == "VECTOR":
            mix_result = sock
            break

    # ── Smoothing pass (Blur Attribute) ────────────────────────────────
    # Multiply per-iteration weight by the iteration count to expose
    # both controls cleanly. The Blur Attribute node already accepts
    # an integer iteration count and a per-iteration weight as inputs.
    blur = nodes.new("GeometryNodeBlurAttribute")
    if hasattr(blur, "data_type"):
        blur.data_type = "FLOAT_VECTOR"
    blur.location = (1740, 180)
    blur.label = "Smooth Projection"

    # Vector input on Blur Attribute. The node has per-data-type
    # variants and only the FLOAT_VECTOR one is enabled here.
    try:
        blur_val_in = _enabled_socket(blur.inputs, "Value", sock_type="VECTOR")
    except RuntimeError:
        blur_val_in = None
    if blur_val_in is not None:
        links.new(mix_result, blur_val_in)
    if "Iterations" in blur.inputs:
        links.new(n_in.outputs["Smooth Iterations"], blur.inputs["Iterations"])
    if "Weight" in blur.inputs:
        links.new(n_in.outputs["Smooth Weight"], blur.inputs["Weight"])

    try:
        blur_out = _enabled_socket(blur.outputs, "Value", sock_type="VECTOR")
    except RuntimeError:
        # Older node versions: fall back to skipping blur.
        blur_out = mix_result

    # ── Selection: only move points that pass the mask AND have a
    #    valid target sample (mesh present and non-empty).
    sel_and = nodes.new("FunctionNodeBooleanMath")
    sel_and.operation = "AND"
    sel_and.location = (1940, 0)
    sel_and.label = "Selection AND Valid"
    links.new(n_in.outputs["Selection"], sel_and.inputs[0])
    links.new(tgt_valid, sel_and.inputs[1])

    n_set_position = nodes.new("GeometryNodeSetPosition")
    n_set_position.location = (2160, 0)
    links.new(n_in.outputs["Geometry"], n_set_position.inputs["Geometry"])
    links.new(sel_and.outputs["Boolean"], n_set_position.inputs["Selection"])
    links.new(blur_out, n_set_position.inputs["Position"])
    links.new(n_set_position.outputs["Geometry"], n_out.inputs["Geometry"])

    return ng


def remove_node_group() -> None:
    ng = bpy.data.node_groups.get(NODE_GROUP_NAME)
    if ng is not None and ng.users == 0:
        bpy.data.node_groups.remove(ng)
