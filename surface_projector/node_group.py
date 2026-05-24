"""Construction of the Geometry Nodes group that backs the modifier."""

from __future__ import annotations

import bpy

NODE_GROUP_NAME = "Surface Projector"


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


def _find_socket(sockets, candidates):
    for name in candidates:
        sock = sockets.get(name)
        if sock is not None:
            return sock
    raise RuntimeError(
        f"Could not find any of {candidates!r}; have "
        f"{[s.name for s in sockets]!r}"
    )


def _enabled_socket(sockets, name):
    for sock in sockets:
        if sock.enabled and sock.name == name:
            return sock
    raise RuntimeError(
        f"Could not find enabled socket {name!r}; have "
        f"{[s.name for s in sockets if s.enabled]!r}"
    )


def ensure_node_group(force_rebuild: bool = False) -> bpy.types.NodeTree:
    """Create or refresh the Surface Projector geometry node tree.

    Two projection modes are exposed:
      * Closest Point  — every input point snaps to the closest point on the
        target surface.
      * Raycast        — every input point is raycast along its own normal;
        the surface hit becomes the target position. Points that miss are
        left at their original position.

    Both modes support a 0..1 ``Factor`` blend with the original position
    and a signed ``Offset`` along the surface normal so users can keep a
    small gap (positive) or push the result inside the target (negative).
    """

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
        description="Object whose surface the geometry is projected onto",
    )
    _new_socket(
        ng, name="Use Raycast", in_out="INPUT",
        socket_type="NodeSocketBool",
        description=(
            "Raycast along the input normal instead of snapping to the "
            "closest point on the target"
        ),
        default=False,
    )
    _new_socket(
        ng, name="Invert Ray", in_out="INPUT",
        socket_type="NodeSocketBool",
        description="Raycast along the inverted normal (opposite direction)",
        default=False,
    )
    _new_socket(
        ng, name="Ray Length", in_out="INPUT",
        socket_type="NodeSocketFloat",
        description="Maximum ray distance (raycast mode only)",
        default=100.0, min_value=0.0, subtype="DISTANCE",
    )
    _new_socket(
        ng, name="Factor", in_out="INPUT",
        socket_type="NodeSocketFloat",
        description="0 = keep original position, 1 = fully project",
        default=1.0, min_value=0.0, max_value=1.0, subtype="FACTOR",
    )
    _new_socket(
        ng, name="Offset", in_out="INPUT",
        socket_type="NodeSocketFloat",
        description="Offset along the surface normal at the projection point",
        default=0.0, subtype="DISTANCE",
    )
    _new_socket(
        ng, name="Selection", in_out="INPUT",
        socket_type="NodeSocketBool",
        description="Only project points where the selection is true",
        default=True,
    )

    _new_socket(
        ng, name="Geometry", in_out="OUTPUT",
        socket_type="NodeSocketGeometry",
    )

    # ── Nodes ──────────────────────────────────────────────────────────
    nodes = ng.nodes
    links = ng.links

    n_in = nodes.new("NodeGroupInput");           n_in.location = (-1100, 0)
    n_out = nodes.new("NodeGroupOutput");         n_out.location = (1200, 0)

    n_object_info = nodes.new("GeometryNodeObjectInfo")
    n_object_info.transform_space = "RELATIVE"
    n_object_info.location = (-850, -250)

    n_position = nodes.new("GeometryNodeInputPosition")
    n_position.location = (-850, 250)

    n_normal = nodes.new("GeometryNodeInputNormal")
    n_normal.location = (-850, 120)

    # Invert ray direction depending on "Invert Ray" boolean.
    n_neg_normal = nodes.new("ShaderNodeVectorMath")
    n_neg_normal.operation = "SCALE"
    n_neg_normal.location = (-650, 30)
    n_neg_normal.inputs[3].default_value = -1.0  # Scale factor

    n_ray_dir_switch = nodes.new("GeometryNodeSwitch")
    n_ray_dir_switch.input_type = "VECTOR"
    n_ray_dir_switch.label = "Ray Dir"
    n_ray_dir_switch.location = (-450, 80)

    # Closest-point projection.
    n_proximity = nodes.new("GeometryNodeProximity")
    if hasattr(n_proximity, "target_element"):
        n_proximity.target_element = "FACES"
    n_proximity.location = (-450, -200)

    # Raycast projection along the (possibly inverted) input normal.
    n_raycast = nodes.new("GeometryNodeRaycast")
    if hasattr(n_raycast, "mapping"):
        n_raycast.mapping = "INTERPOLATED"
    if hasattr(n_raycast, "data_type"):
        n_raycast.data_type = "FLOAT_VECTOR"
    n_raycast.location = (-200, -100)

    # When the ray misses, fall back to the source position so the point
    # stays where it was.
    n_hit_pos_fallback = nodes.new("GeometryNodeSwitch")
    n_hit_pos_fallback.input_type = "VECTOR"
    n_hit_pos_fallback.label = "Hit or Source"
    n_hit_pos_fallback.location = (50, -50)

    # Pick projected position based on Use Raycast.
    n_mode_pos = nodes.new("GeometryNodeSwitch")
    n_mode_pos.input_type = "VECTOR"
    n_mode_pos.label = "Projected Position"
    n_mode_pos.location = (300, 60)

    # Pick normal at projected point: hit_normal for raycast, input normal
    # for closest-point (cheap fallback that avoids needing a Sample Index).
    n_mode_normal = nodes.new("GeometryNodeSwitch")
    n_mode_normal.input_type = "VECTOR"
    n_mode_normal.label = "Surface Normal"
    n_mode_normal.location = (300, -160)

    # Lerp: source → projected by Factor.
    n_mix = nodes.new("ShaderNodeMix")
    n_mix.data_type = "VECTOR"
    if hasattr(n_mix, "clamp_factor"):
        n_mix.clamp_factor = True
    n_mix.location = (550, 100)

    # Add offset along surface normal.
    n_scaled_normal = nodes.new("ShaderNodeVectorMath")
    n_scaled_normal.operation = "SCALE"
    n_scaled_normal.location = (550, -120)

    n_add_offset = nodes.new("ShaderNodeVectorMath")
    n_add_offset.operation = "ADD"
    n_add_offset.location = (800, 0)

    # Final selection: only move points where Selection is true AND
    # (in raycast mode) the ray actually hit something. In closest-point
    # mode the proximity always returns a valid position so selection is
    # taken as-is.
    n_and = nodes.new("FunctionNodeBooleanMath")
    n_and.operation = "AND"
    n_and.location = (550, -320)

    n_sel_switch = nodes.new("GeometryNodeSwitch")
    n_sel_switch.input_type = "BOOLEAN"
    n_sel_switch.label = "Effective Selection"
    n_sel_switch.location = (800, -260)

    n_set_position = nodes.new("GeometryNodeSetPosition")
    n_set_position.location = (1000, 0)

    # ── Links ──────────────────────────────────────────────────────────

    # Ray direction = normal or -normal.
    links.new(n_normal.outputs["Normal"], n_neg_normal.inputs[0])
    dir_false = _find_socket(n_ray_dir_switch.inputs, ("False", "Switch_001"))
    dir_true = _find_socket(n_ray_dir_switch.inputs, ("True", "Switch_002"))
    links.new(n_in.outputs["Invert Ray"], n_ray_dir_switch.inputs[0])
    links.new(n_normal.outputs["Normal"], dir_false)
    links.new(n_neg_normal.outputs["Vector"], dir_true)
    ray_dir_out = _find_socket(
        n_ray_dir_switch.outputs, ("Output", "Vector")
    )

    # Geometry Proximity inputs.
    links.new(n_object_info.outputs["Geometry"], n_proximity.inputs["Target"])
    prox_source = _find_socket(
        n_proximity.inputs, ("Source Position", "Sample Position")
    )
    links.new(n_position.outputs["Position"], prox_source)
    prox_pos = _find_socket(n_proximity.outputs, ("Position",))

    # Raycast inputs.
    links.new(n_object_info.outputs["Geometry"],
              n_raycast.inputs["Target Geometry"])
    links.new(n_position.outputs["Position"],
              n_raycast.inputs["Source Position"])
    links.new(ray_dir_out, n_raycast.inputs["Ray Direction"])
    links.new(n_in.outputs["Ray Length"], n_raycast.inputs["Ray Length"])

    # If the ray hits, use hit position; otherwise keep source position.
    hp_false = _find_socket(n_hit_pos_fallback.inputs, ("False", "Switch_001"))
    hp_true = _find_socket(n_hit_pos_fallback.inputs, ("True", "Switch_002"))
    links.new(n_raycast.outputs["Is Hit"], n_hit_pos_fallback.inputs[0])
    links.new(n_position.outputs["Position"], hp_false)
    links.new(n_raycast.outputs["Hit Position"], hp_true)
    hp_out = _find_socket(n_hit_pos_fallback.outputs, ("Output", "Vector"))

    # Mode switch (Use Raycast).
    mp_false = _find_socket(n_mode_pos.inputs, ("False", "Switch_001"))
    mp_true = _find_socket(n_mode_pos.inputs, ("True", "Switch_002"))
    links.new(n_in.outputs["Use Raycast"], n_mode_pos.inputs[0])
    links.new(prox_pos, mp_false)
    links.new(hp_out, mp_true)
    mp_out = _find_socket(n_mode_pos.outputs, ("Output", "Vector"))

    mn_false = _find_socket(n_mode_normal.inputs, ("False", "Switch_001"))
    mn_true = _find_socket(n_mode_normal.inputs, ("True", "Switch_002"))
    links.new(n_in.outputs["Use Raycast"], n_mode_normal.inputs[0])
    links.new(n_normal.outputs["Normal"], mn_false)
    links.new(n_raycast.outputs["Hit Normal"], mn_true)
    mn_out = _find_socket(n_mode_normal.outputs, ("Output", "Vector"))

    # Lerp source → projected position by Factor. The Mix node has one
    # A/B pair per data type; only the vector ones are enabled here.
    mix_factor = _enabled_socket(n_mix.inputs, "Factor")
    mix_a, mix_b = _vector_mix_inputs(n_mix)
    links.new(n_in.outputs["Factor"], mix_factor)
    links.new(n_position.outputs["Position"], mix_a)
    links.new(mp_out, mix_b)
    mix_result = _vector_mix_result(n_mix)

    # Offset along surface normal.
    links.new(mn_out, n_scaled_normal.inputs[0])
    links.new(n_in.outputs["Offset"], n_scaled_normal.inputs[3])
    links.new(mix_result, n_add_offset.inputs[0])
    links.new(n_scaled_normal.outputs["Vector"], n_add_offset.inputs[1])

    # Effective selection (so misses in raycast mode are skipped).
    links.new(n_in.outputs["Selection"], n_and.inputs[0])
    links.new(n_raycast.outputs["Is Hit"], n_and.inputs[1])

    sel_false = _find_socket(n_sel_switch.inputs, ("False", "Switch_001"))
    sel_true = _find_socket(n_sel_switch.inputs, ("True", "Switch_002"))
    links.new(n_in.outputs["Use Raycast"], n_sel_switch.inputs[0])
    links.new(n_in.outputs["Selection"], sel_false)
    links.new(n_and.outputs["Boolean"], sel_true)
    sel_out = _find_socket(n_sel_switch.outputs, ("Output", "Boolean"))

    # Set Position.
    links.new(n_in.outputs["Geometry"], n_set_position.inputs["Geometry"])
    links.new(sel_out, n_set_position.inputs["Selection"])
    links.new(n_add_offset.outputs["Vector"],
              n_set_position.inputs["Position"])

    links.new(n_set_position.outputs["Geometry"], n_out.inputs["Geometry"])

    # Plug Target object into Object Info (drives the modifier input).
    links.new(n_in.outputs["Target"], n_object_info.inputs["Object"])

    return ng


def _vector_mix_inputs(mix_node):
    """Return the (A, B) sockets of the *vector* pair of a Mix node.

    The Mix node in Blender 4.x has several A/B socket pairs (one per data
    type); only the one matching ``data_type`` is enabled. Filter to the
    enabled vector pair.
    """
    a = b = None
    for sock in mix_node.inputs:
        if sock.enabled and sock.type == "VECTOR" and sock.name in {"A", "B"}:
            if sock.name == "A" and a is None:
                a = sock
            elif sock.name == "B" and b is None:
                b = sock
    if a is None or b is None:
        raise RuntimeError(
            "Could not locate enabled vector A/B sockets on Mix node"
        )
    return a, b


def _vector_mix_result(mix_node):
    for sock in mix_node.outputs:
        if sock.enabled and sock.type == "VECTOR":
            return sock
    raise RuntimeError("Mix node has no enabled vector output socket")


def remove_node_group() -> None:
    ng = bpy.data.node_groups.get(NODE_GROUP_NAME)
    if ng is not None and ng.users == 0:
        bpy.data.node_groups.remove(ng)
