"""Construction of the Geometry Nodes group that backs the modifier.

The projector keeps the source object's shape and volume by computing a
per-vertex *height along a projection axis*, raycasting the axis against
the target surface, and re-anchoring each vertex above the surface hit
point at its original height. Three behaviours are exposed:

* **Project** (``Wrap = 0``)
    Each vertex is translated parallel to the projection axis so the
    bottom of the source's bounding box lies on the surface. The
    source keeps its silhouette along the axis.

* **Target Normal** (``Wrap = 1``)
    Each vertex is lifted along the *target's* surface normal at its
    projection point. The source wraps the surface.

* **Flow to Surface** (``0 < Wrap < 1``)
    Linear blend between the two above — produces a smooth bend that
    follows the surface without fully aligning with it.

When ``Preserve Shape`` is off, every vertex collapses to its raycast
hit point (the old "squish" behaviour) — useful for stencil/decal
workflows.

Auto-axis: enabled by default. Picks the world axis pointing from the
input bounding-box centre to the target bounding-box centre.
"""

from __future__ import annotations

import bpy

NODE_GROUP_NAME = "Surface Projector"


# ── interface helpers ─────────────────────────────────────────────────


def _new_socket(ng, *, name, in_out, socket_type, description="",
                default=None, min_value=None, max_value=None, subtype=None):
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


def _find_socket(sockets, candidates):
    for name in candidates:
        sock = sockets.get(name)
        if sock is not None:
            return sock
    raise RuntimeError(
        f"Could not find any of {candidates!r}; have "
        f"{[s.name for s in sockets]!r}"
    )


def _switch_inputs(switch_node):
    """Return the (selector, false, true) sockets of a Switch node."""
    inp = switch_node.inputs
    selector = inp[0]
    false_sock = _find_socket(inp, ("False", "Switch_001"))
    true_sock = _find_socket(inp, ("True", "Switch_002"))
    return selector, false_sock, true_sock


def _switch_output(switch_node):
    return _find_socket(
        switch_node.outputs, ("Output", "Vector", "Geometry", "Boolean")
    )


def _enabled_socket(sockets, *, kind, name=None):
    """Return the first enabled socket whose ``type`` is ``kind`` (and
    optionally whose ``name`` matches). The Mix node has duplicate
    A/B/Result sockets per data type — only the enabled ones drive the
    selected data type."""
    for sock in sockets:
        if not sock.enabled:
            continue
        if sock.type != kind:
            continue
        if name is not None and sock.name != name:
            continue
        return sock
    raise RuntimeError(
        f"No enabled {kind} socket named {name!r}; have "
        f"{[(s.name, s.type, s.enabled) for s in sockets]!r}"
    )


# ── builders ──────────────────────────────────────────────────────────


def _build_auto_axis(ng, n_in, src_bbox, tgt_bbox):
    """Build the sub-graph that snaps the centre-to-centre direction to
    the nearest signed world axis and switches it against ``Manual Axis``.

    Returns the socket carrying the final unit-length axis vector.
    """
    nodes = ng.nodes
    links = ng.links

    src_min = _find_socket(src_bbox.outputs, ("Min",))
    src_max = _find_socket(src_bbox.outputs, ("Max",))
    tgt_min = _find_socket(tgt_bbox.outputs, ("Min",))
    tgt_max = _find_socket(tgt_bbox.outputs, ("Max",))

    # Source centre = (src_min + src_max) * 0.5.
    src_sum = nodes.new("ShaderNodeVectorMath")
    src_sum.operation = "ADD"
    src_sum.location = (-1700, -550)
    links.new(src_min, src_sum.inputs[0])
    links.new(src_max, src_sum.inputs[1])

    src_centre = nodes.new("ShaderNodeVectorMath")
    src_centre.operation = "SCALE"
    src_centre.location = (-1500, -550)
    src_centre.inputs[3].default_value = 0.5
    links.new(src_sum.outputs["Vector"], src_centre.inputs[0])

    tgt_sum = nodes.new("ShaderNodeVectorMath")
    tgt_sum.operation = "ADD"
    tgt_sum.location = (-1700, -700)
    links.new(tgt_min, tgt_sum.inputs[0])
    links.new(tgt_max, tgt_sum.inputs[1])

    tgt_centre = nodes.new("ShaderNodeVectorMath")
    tgt_centre.operation = "SCALE"
    tgt_centre.location = (-1500, -700)
    tgt_centre.inputs[3].default_value = 0.5
    links.new(tgt_sum.outputs["Vector"], tgt_centre.inputs[0])

    # Direction = tgt - src.
    direction = nodes.new("ShaderNodeVectorMath")
    direction.operation = "SUBTRACT"
    direction.location = (-1300, -625)
    links.new(tgt_centre.outputs["Vector"], direction.inputs[0])
    links.new(src_centre.outputs["Vector"], direction.inputs[1])

    sep = nodes.new("ShaderNodeSeparateXYZ")
    sep.location = (-1100, -625)
    links.new(direction.outputs["Vector"], sep.inputs[0])

    def _abs(node_x_in, y):
        n = nodes.new("ShaderNodeMath")
        n.operation = "ABSOLUTE"
        n.location = (-925, y)
        links.new(node_x_in, n.inputs[0])
        return n

    abs_x = _abs(sep.outputs["X"], -550)
    abs_y = _abs(sep.outputs["Y"], -625)
    abs_z = _abs(sep.outputs["Z"], -700)

    def _sign(node_in, y):
        """Return +1 if input >= 0, else -1."""
        ge = nodes.new("ShaderNodeMath")
        ge.operation = "GREATER_THAN"
        ge.location = (-925, y)
        ge.inputs[1].default_value = 0.0
        links.new(node_in, ge.inputs[0])
        scale = nodes.new("ShaderNodeMath")
        scale.operation = "MULTIPLY_ADD"
        scale.location = (-780, y)
        scale.inputs[1].default_value = 2.0   # ge * 2
        scale.inputs[2].default_value = -1.0  # ge * 2 - 1
        links.new(ge.outputs["Value"], scale.inputs[0])
        return scale

    sign_x = _sign(sep.outputs["X"], -400)
    sign_y = _sign(sep.outputs["Y"], -475)
    sign_z = _sign(sep.outputs["Z"], -325)

    # Unit axis candidates: (±1, 0, 0), (0, ±1, 0), (0, 0, ±1).
    zero = nodes.new("ShaderNodeValue")
    zero.location = (-600, -800)
    zero.outputs[0].default_value = 0.0

    axis_x = nodes.new("ShaderNodeCombineXYZ")
    axis_x.location = (-500, -400)
    links.new(sign_x.outputs["Value"], axis_x.inputs["X"])
    links.new(zero.outputs[0], axis_x.inputs["Y"])
    links.new(zero.outputs[0], axis_x.inputs["Z"])

    axis_y = nodes.new("ShaderNodeCombineXYZ")
    axis_y.location = (-500, -475)
    links.new(zero.outputs[0], axis_y.inputs["X"])
    links.new(sign_y.outputs["Value"], axis_y.inputs["Y"])
    links.new(zero.outputs[0], axis_y.inputs["Z"])

    axis_z = nodes.new("ShaderNodeCombineXYZ")
    axis_z.location = (-500, -325)
    links.new(zero.outputs[0], axis_z.inputs["X"])
    links.new(zero.outputs[0], axis_z.inputs["Y"])
    links.new(sign_z.outputs["Value"], axis_z.inputs["Z"])

    # Choose between X and Y axes based on |x| vs |y|.
    xy_to_bool = nodes.new("FunctionNodeCompare")
    xy_to_bool.data_type = "FLOAT"
    xy_to_bool.operation = "GREATER_EQUAL"
    xy_to_bool.location = (-540, -550)
    links.new(abs_x.outputs["Value"], xy_to_bool.inputs[0])
    links.new(abs_y.outputs["Value"], xy_to_bool.inputs[1])

    xy_axis_switch = nodes.new("GeometryNodeSwitch")
    xy_axis_switch.input_type = "VECTOR"
    xy_axis_switch.label = "X or Y"
    xy_axis_switch.location = (-320, -425)
    sel, f, t = _switch_inputs(xy_axis_switch)
    links.new(xy_to_bool.outputs["Result"], sel)
    links.new(axis_y.outputs["Vector"], f)
    links.new(axis_x.outputs["Vector"], t)

    # |z| vs max(|x|,|y|).
    abs_xy_max = nodes.new("ShaderNodeMath")
    abs_xy_max.operation = "MAXIMUM"
    abs_xy_max.location = (-540, -680)
    links.new(abs_x.outputs["Value"], abs_xy_max.inputs[0])
    links.new(abs_y.outputs["Value"], abs_xy_max.inputs[1])

    z_ge_xy = nodes.new("FunctionNodeCompare")
    z_ge_xy.data_type = "FLOAT"
    z_ge_xy.operation = "GREATER_EQUAL"
    z_ge_xy.location = (-380, -680)
    links.new(abs_z.outputs["Value"], z_ge_xy.inputs[0])
    links.new(abs_xy_max.outputs["Value"], z_ge_xy.inputs[1])

    auto_axis_switch = nodes.new("GeometryNodeSwitch")
    auto_axis_switch.input_type = "VECTOR"
    auto_axis_switch.label = "Auto Axis"
    auto_axis_switch.location = (-140, -480)
    sel, f, t = _switch_inputs(auto_axis_switch)
    links.new(z_ge_xy.outputs["Result"], sel)
    links.new(_switch_output(xy_axis_switch), f)
    links.new(axis_z.outputs["Vector"], t)

    # Switch between auto and manual axis based on "Auto Axis" boolean.
    manual_or_auto = nodes.new("GeometryNodeSwitch")
    manual_or_auto.input_type = "VECTOR"
    manual_or_auto.label = "Auto vs Manual"
    manual_or_auto.location = (60, -400)
    sel, f, t = _switch_inputs(manual_or_auto)
    links.new(n_in.outputs["Auto Axis"], sel)
    links.new(n_in.outputs["Manual Axis"], f)
    links.new(_switch_output(auto_axis_switch), t)

    # Normalise (manual axis might not be unit-length).
    norm = nodes.new("ShaderNodeVectorMath")
    norm.operation = "NORMALIZE"
    norm.location = (240, -400)
    links.new(_switch_output(manual_or_auto), norm.inputs[0])

    # Optional inversion (×-1) for the "Invert Axis" boolean.
    neg = nodes.new("ShaderNodeVectorMath")
    neg.operation = "SCALE"
    neg.location = (240, -540)
    neg.inputs[3].default_value = -1.0
    links.new(norm.outputs["Vector"], neg.inputs[0])

    invert_switch = nodes.new("GeometryNodeSwitch")
    invert_switch.input_type = "VECTOR"
    invert_switch.label = "Invert Axis"
    invert_switch.location = (440, -460)
    sel, f, t = _switch_inputs(invert_switch)
    links.new(n_in.outputs["Invert Axis"], sel)
    links.new(norm.outputs["Vector"], f)
    links.new(neg.outputs["Vector"], t)

    return _switch_output(invert_switch)


def _build_max_height(ng, axis_socket, src_bbox):
    """``max(dot(src_max, axis), dot(src_min, axis))``.

    For an axis-aligned axis this equals the largest projection of any
    bounding-box corner onto the axis (since the extreme corner along an
    axis-aligned direction is necessarily one of `min` or `max`).
    """
    nodes = ng.nodes
    links = ng.links

    src_min = _find_socket(src_bbox.outputs, ("Min",))
    src_max = _find_socket(src_bbox.outputs, ("Max",))

    dot_max = nodes.new("ShaderNodeVectorMath")
    dot_max.operation = "DOT_PRODUCT"
    dot_max.location = (640, -200)
    links.new(src_max, dot_max.inputs[0])
    links.new(axis_socket, dot_max.inputs[1])

    dot_min = nodes.new("ShaderNodeVectorMath")
    dot_min.operation = "DOT_PRODUCT"
    dot_min.location = (640, -340)
    links.new(src_min, dot_min.inputs[0])
    links.new(axis_socket, dot_min.inputs[1])

    max_node = nodes.new("ShaderNodeMath")
    max_node.operation = "MAXIMUM"
    max_node.location = (820, -270)
    links.new(dot_max.outputs["Value"], max_node.inputs[0])
    links.new(dot_min.outputs["Value"], max_node.inputs[1])

    return max_node.outputs["Value"]


# ── main builder ──────────────────────────────────────────────────────


def ensure_node_group(force_rebuild: bool = False) -> bpy.types.NodeTree:
    """Create or refresh the Surface Projector geometry node tree."""

    ng = bpy.data.node_groups.get(NODE_GROUP_NAME)
    if ng is not None and not force_rebuild:
        ng.is_modifier = True
        return ng

    if ng is None:
        ng = bpy.data.node_groups.new(NODE_GROUP_NAME, "GeometryNodeTree")
    else:
        _clear(ng)

    ng.is_modifier = True

    # ── interface ─────────────────────────────────────────────────────
    _new_socket(
        ng, name="Geometry", in_out="INPUT",
        socket_type="NodeSocketGeometry",
        description="Source geometry to project",
    )
    _new_socket(
        ng, name="Target", in_out="INPUT",
        socket_type="NodeSocketObject",
        description="Object whose surface is the projection target",
    )
    _new_socket(
        ng, name="Preserve Shape", in_out="INPUT",
        socket_type="NodeSocketBool",
        description=(
            "Keep the source's volume (lift each vertex above the surface "
            "by its original height along the axis). Disable to snap every "
            "vertex onto the surface (flat decal/squish behaviour)."
        ),
        default=True,
    )
    _new_socket(
        ng, name="Wrap", in_out="INPUT",
        socket_type="NodeSocketFloat",
        description=(
            "0 = Project along axis (no rotation), 1 = align with target "
            "normal at each hit point (Target Normal), in-between values "
            "blend smoothly between the two (Flow to Surface)."
        ),
        default=0.0, min_value=0.0, max_value=1.0, subtype="FACTOR",
    )
    _new_socket(
        ng, name="Auto Axis", in_out="INPUT",
        socket_type="NodeSocketBool",
        description=(
            "Detect the projection axis automatically from the relative "
            "position of the source and target bounding boxes"
        ),
        default=True,
    )
    _new_socket(
        ng, name="Manual Axis", in_out="INPUT",
        socket_type="NodeSocketVector",
        description="Projection axis used when Auto Axis is off",
        default=(0.0, 0.0, -1.0),
    )
    _new_socket(
        ng, name="Invert Axis", in_out="INPUT",
        socket_type="NodeSocketBool",
        description="Flip the projection axis (useful for stuck auto-axis)",
        default=False,
    )
    _new_socket(
        ng, name="Factor", in_out="INPUT",
        socket_type="NodeSocketFloat",
        description="Blend between the original and the projected position",
        default=1.0, min_value=0.0, max_value=1.0, subtype="FACTOR",
    )
    _new_socket(
        ng, name="Offset", in_out="INPUT",
        socket_type="NodeSocketFloat",
        description=(
            "Extra distance above the surface (along the effective normal). "
            "Negative values sink the source into the target."
        ),
        default=0.0, subtype="DISTANCE",
    )
    _new_socket(
        ng, name="Ray Length", in_out="INPUT",
        socket_type="NodeSocketFloat",
        description="Maximum raycast distance — cap to keep performance sane",
        default=1000.0, min_value=0.0, subtype="DISTANCE",
    )
    _new_socket(
        ng, name="Selection", in_out="INPUT",
        socket_type="NodeSocketBool",
        description="Per-point selection mask",
        default=True,
    )

    _new_socket(
        ng, name="Geometry", in_out="OUTPUT",
        socket_type="NodeSocketGeometry",
    )

    nodes = ng.nodes
    links = ng.links

    # ── core nodes ────────────────────────────────────────────────────
    n_in = nodes.new("NodeGroupInput");        n_in.location = (-2100, 0)
    n_out = nodes.new("NodeGroupOutput");      n_out.location = (1900, 0)

    n_object_info = nodes.new("GeometryNodeObjectInfo")
    n_object_info.transform_space = "RELATIVE"
    n_object_info.location = (-1900, -250)
    links.new(n_in.outputs["Target"], n_object_info.inputs["Object"])

    # Bounding boxes for the auto-axis sub-graph and for max_height.
    n_src_bbox = nodes.new("GeometryNodeBoundingBox")
    n_src_bbox.location = (-1900, -50)
    links.new(n_in.outputs["Geometry"], n_src_bbox.inputs["Geometry"])

    n_tgt_bbox = nodes.new("GeometryNodeBoundingBox")
    n_tgt_bbox.location = (-1900, -450)
    links.new(n_object_info.outputs["Geometry"], n_tgt_bbox.inputs["Geometry"])

    # ── axis ──────────────────────────────────────────────────────────
    axis_out = _build_auto_axis(ng, n_in, n_src_bbox, n_tgt_bbox)
    max_height_out = _build_max_height(ng, axis_out, n_src_bbox)

    # ── per-vertex height = dot(position, axis) ───────────────────────
    n_position = nodes.new("GeometryNodeInputPosition")
    n_position.location = (640, 250)

    n_height = nodes.new("ShaderNodeVectorMath")
    n_height.operation = "DOT_PRODUCT"
    n_height.location = (820, 250)
    links.new(n_position.outputs["Position"], n_height.inputs[0])
    links.new(axis_out, n_height.inputs[1])

    # depth = max_height - height
    n_depth = nodes.new("ShaderNodeMath")
    n_depth.operation = "SUBTRACT"
    n_depth.location = (1000, 50)
    links.new(max_height_out, n_depth.inputs[0])
    links.new(n_height.outputs["Value"], n_depth.inputs[1])

    # depth + offset
    n_lift = nodes.new("ShaderNodeMath")
    n_lift.operation = "ADD"
    n_lift.location = (1180, 50)
    links.new(n_depth.outputs["Value"], n_lift.inputs[0])
    links.new(n_in.outputs["Offset"], n_lift.inputs[1])

    # ── raycast along axis from each vertex ───────────────────────────
    n_raycast = nodes.new("GeometryNodeRaycast")
    if hasattr(n_raycast, "mapping"):
        n_raycast.mapping = "INTERPOLATED"
    if hasattr(n_raycast, "data_type"):
        n_raycast.data_type = "FLOAT_VECTOR"
    n_raycast.location = (640, 0)
    links.new(n_object_info.outputs["Geometry"],
              n_raycast.inputs["Target Geometry"])
    links.new(n_position.outputs["Position"],
              n_raycast.inputs["Source Position"])
    links.new(axis_out, n_raycast.inputs["Ray Direction"])
    links.new(n_in.outputs["Ray Length"], n_raycast.inputs["Ray Length"])

    # ── effective surface normal: lerp(-axis, hit_normal, Wrap) ──────
    n_neg_axis = nodes.new("ShaderNodeVectorMath")
    n_neg_axis.operation = "SCALE"
    n_neg_axis.location = (820, -50)
    n_neg_axis.inputs[3].default_value = -1.0
    links.new(axis_out, n_neg_axis.inputs[0])

    n_wrap_mix = nodes.new("ShaderNodeMix")
    n_wrap_mix.data_type = "VECTOR"
    if hasattr(n_wrap_mix, "clamp_factor"):
        n_wrap_mix.clamp_factor = True
    n_wrap_mix.location = (1000, -100)
    links.new(
        n_in.outputs["Wrap"],
        _enabled_socket(n_wrap_mix.inputs, kind="VALUE", name="Factor"),
    )
    wrap_a = _enabled_socket(n_wrap_mix.inputs, kind="VECTOR", name="A")
    wrap_b = _enabled_socket(n_wrap_mix.inputs, kind="VECTOR", name="B")
    links.new(n_neg_axis.outputs["Vector"], wrap_a)
    links.new(n_raycast.outputs["Hit Normal"], wrap_b)
    wrap_out = _enabled_socket(n_wrap_mix.outputs, kind="VECTOR")

    n_eff_normal = nodes.new("ShaderNodeVectorMath")
    n_eff_normal.operation = "NORMALIZE"
    n_eff_normal.location = (1180, -100)
    links.new(wrap_out, n_eff_normal.inputs[0])

    # ── preserved position: hit + eff_normal * lift ───────────────────
    n_offset_vec = nodes.new("ShaderNodeVectorMath")
    n_offset_vec.operation = "SCALE"
    n_offset_vec.location = (1360, -100)
    links.new(n_eff_normal.outputs["Vector"], n_offset_vec.inputs[0])
    links.new(n_lift.outputs["Value"], n_offset_vec.inputs[3])

    n_preserve_pos = nodes.new("ShaderNodeVectorMath")
    n_preserve_pos.operation = "ADD"
    n_preserve_pos.location = (1540, -50)
    links.new(n_raycast.outputs["Hit Position"], n_preserve_pos.inputs[0])
    links.new(n_offset_vec.outputs["Vector"], n_preserve_pos.inputs[1])

    # ── squish position: hit + hit_normal * offset ───────────────────
    n_squish_offset = nodes.new("ShaderNodeVectorMath")
    n_squish_offset.operation = "SCALE"
    n_squish_offset.location = (1360, -260)
    links.new(n_raycast.outputs["Hit Normal"], n_squish_offset.inputs[0])
    links.new(n_in.outputs["Offset"], n_squish_offset.inputs[3])

    n_squish_pos = nodes.new("ShaderNodeVectorMath")
    n_squish_pos.operation = "ADD"
    n_squish_pos.location = (1540, -210)
    links.new(n_raycast.outputs["Hit Position"], n_squish_pos.inputs[0])
    links.new(n_squish_offset.outputs["Vector"], n_squish_pos.inputs[1])

    # ── switch between preserve and squish via "Preserve Shape" ──────
    n_mode = nodes.new("GeometryNodeSwitch")
    n_mode.input_type = "VECTOR"
    n_mode.label = "Preserve vs Squish"
    n_mode.location = (1700, -110)
    sel, f, t = _switch_inputs(n_mode)
    links.new(n_in.outputs["Preserve Shape"], sel)
    links.new(n_squish_pos.outputs["Vector"], f)
    links.new(n_preserve_pos.outputs["Vector"], t)
    chosen_pos = _switch_output(n_mode)

    # ── Factor blend with original position ──────────────────────────
    n_factor_mix = nodes.new("ShaderNodeMix")
    n_factor_mix.data_type = "VECTOR"
    if hasattr(n_factor_mix, "clamp_factor"):
        n_factor_mix.clamp_factor = True
    n_factor_mix.location = (1700, 150)
    links.new(
        n_in.outputs["Factor"],
        _enabled_socket(n_factor_mix.inputs, kind="VALUE", name="Factor"),
    )
    f_a = _enabled_socket(n_factor_mix.inputs, kind="VECTOR", name="A")
    f_b = _enabled_socket(n_factor_mix.inputs, kind="VECTOR", name="B")
    links.new(n_position.outputs["Position"], f_a)
    links.new(chosen_pos, f_b)
    final_pos = _enabled_socket(n_factor_mix.outputs, kind="VECTOR")

    # ── effective selection: Selection AND Is Hit ────────────────────
    n_and = nodes.new("FunctionNodeBooleanMath")
    n_and.operation = "AND"
    n_and.location = (1540, 350)
    links.new(n_in.outputs["Selection"], n_and.inputs[0])
    links.new(n_raycast.outputs["Is Hit"], n_and.inputs[1])

    # ── Set Position ─────────────────────────────────────────────────
    n_set = nodes.new("GeometryNodeSetPosition")
    n_set.location = (1850, 100)
    links.new(n_in.outputs["Geometry"], n_set.inputs["Geometry"])
    links.new(n_and.outputs["Boolean"], n_set.inputs["Selection"])
    links.new(final_pos, n_set.inputs["Position"])

    links.new(n_set.outputs["Geometry"], n_out.inputs["Geometry"])

    return ng


def remove_node_group() -> None:
    ng = bpy.data.node_groups.get(NODE_GROUP_NAME)
    if ng is not None and ng.users == 0:
        bpy.data.node_groups.remove(ng)
