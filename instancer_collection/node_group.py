"""Construction of the Geometry Nodes group that backs the modifier."""

from __future__ import annotations

import bpy

NODE_GROUP_NAME = "Instancer Collection"


def _new_socket(ng, *, name, in_out, socket_type, description="", default=None):
    sock = ng.interface.new_socket(
        name=name, in_out=in_out, socket_type=socket_type
    )
    if description:
        sock.description = description
    if default is not None and hasattr(sock, "default_value"):
        try:
            sock.default_value = default
        except (TypeError, AttributeError):
            pass
    return sock


def _clear(ng):
    for node in list(ng.nodes):
        ng.nodes.remove(node)
    for item in list(ng.interface.items_tree):
        ng.interface.remove(item)


def ensure_node_group(force_rebuild: bool = False) -> bpy.types.NodeTree:
    """Create or refresh the Instancer Collection geometry node tree.

    If a node group with this name already exists it is returned as-is so
    that any modifiers already using it keep their input values. Pass
    ``force_rebuild=True`` to wipe and rebuild it.
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

    _new_socket(
        ng,
        name="Geometry",
        in_out="INPUT",
        socket_type="NodeSocketGeometry",
        description="Geometry coming from the previous modifier",
    )
    _new_socket(
        ng,
        name="Collection",
        in_out="INPUT",
        socket_type="NodeSocketCollection",
        description="Collection of objects to instance",
    )
    _new_socket(
        ng,
        name="Separate Children",
        in_out="INPUT",
        socket_type="NodeSocketBool",
        description="Instance each child of the collection separately",
        default=True,
    )
    _new_socket(
        ng,
        name="Reset Children",
        in_out="INPUT",
        socket_type="NodeSocketBool",
        description="Reset the transforms of the children before instancing",
        default=False,
    )
    _new_socket(
        ng,
        name="Realize Instances",
        in_out="INPUT",
        socket_type="NodeSocketBool",
        description=(
            "Convert the instances to real geometry so following modifiers "
            "can edit them (otherwise they stay as instances)"
        ),
        default=True,
    )
    _new_socket(
        ng,
        name="Replace Input",
        in_out="INPUT",
        socket_type="NodeSocketBool",
        description=(
            "Replace the input geometry with the collection instead of "
            "joining the collection on top of it"
        ),
        default=False,
    )

    _new_socket(
        ng,
        name="Geometry",
        in_out="OUTPUT",
        socket_type="NodeSocketGeometry",
    )

    nodes = ng.nodes
    links = ng.links

    n_in = nodes.new("NodeGroupInput")
    n_in.location = (-700, 0)

    n_out = nodes.new("NodeGroupOutput")
    n_out.location = (700, 0)

    n_info = nodes.new("GeometryNodeCollectionInfo")
    n_info.transform_space = "ORIGINAL"
    n_info.location = (-400, -150)

    n_replace_switch = nodes.new("GeometryNodeSwitch")
    n_replace_switch.input_type = "GEOMETRY"
    n_replace_switch.label = "Replace or Join"
    n_replace_switch.location = (-100, 80)

    n_join = nodes.new("GeometryNodeJoinGeometry")
    n_join.location = (-250, 80)

    n_realize = nodes.new("GeometryNodeRealizeInstances")
    n_realize.location = (200, -100)

    n_realize_switch = nodes.new("GeometryNodeSwitch")
    n_realize_switch.input_type = "GEOMETRY"
    n_realize_switch.label = "Realize?"
    n_realize_switch.location = (450, 0)

    # Wire collection info inputs.
    links.new(n_in.outputs["Collection"], n_info.inputs["Collection"])
    links.new(
        n_in.outputs["Separate Children"], n_info.inputs["Separate Children"]
    )
    links.new(n_in.outputs["Reset Children"], n_info.inputs["Reset Children"])

    # Join input geometry with collection instances.
    links.new(n_in.outputs["Geometry"], n_join.inputs["Geometry"])
    links.new(n_info.outputs["Instances"], n_join.inputs["Geometry"])

    # Switch between (input + collection) and (collection only).
    sw_switch_in = n_replace_switch.inputs[0]
    sw_false = _find_socket(n_replace_switch.inputs, ("False", "Switch_001"))
    sw_true = _find_socket(n_replace_switch.inputs, ("True", "Switch_002"))
    links.new(n_in.outputs["Replace Input"], sw_switch_in)
    links.new(n_join.outputs["Geometry"], sw_false)
    links.new(n_info.outputs["Instances"], sw_true)

    sw_replace_out = _find_socket(
        n_replace_switch.outputs, ("Output", "Geometry")
    )

    # Optional realize.
    links.new(sw_replace_out, n_realize.inputs["Geometry"])

    rs_switch_in = n_realize_switch.inputs[0]
    rs_false = _find_socket(n_realize_switch.inputs, ("False", "Switch_001"))
    rs_true = _find_socket(n_realize_switch.inputs, ("True", "Switch_002"))
    links.new(n_in.outputs["Realize Instances"], rs_switch_in)
    links.new(sw_replace_out, rs_false)
    links.new(n_realize.outputs["Geometry"], rs_true)

    rs_out = _find_socket(n_realize_switch.outputs, ("Output", "Geometry"))
    links.new(rs_out, n_out.inputs["Geometry"])

    return ng


def _find_socket(sockets, candidates):
    """Pick the first matching socket by name across Blender versions."""
    for name in candidates:
        sock = sockets.get(name)
        if sock is not None:
            return sock
    raise RuntimeError(
        f"Could not find any of {candidates!r} on switch node "
        f"(have {[s.name for s in sockets]!r})"
    )


def remove_node_group() -> None:
    ng = bpy.data.node_groups.get(NODE_GROUP_NAME)
    if ng is not None and ng.users == 0:
        bpy.data.node_groups.remove(ng)
