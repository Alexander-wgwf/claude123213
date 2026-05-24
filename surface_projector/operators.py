"""Operators that add the Surface Projector modifier to an object."""

from __future__ import annotations

import bpy
from bpy.props import StringProperty
from bpy.types import Operator

from . import node_group as ng_mod


MODIFIER_DEFAULT_NAME = "Surface Projector"


class OBJECT_OT_add_surface_projector_modifier(Operator):
    """Add a Surface Projector modifier on the active object.

    The modifier wraps a Geometry Nodes group that projects every input
    point onto the surface of a target object — either by snapping to the
    closest point or by raycasting along the input normal.
    """

    bl_idname = "object.surface_projector_modifier_add"
    bl_label = "Add Surface Projector Modifier"
    bl_options = {"REGISTER", "UNDO"}

    target: StringProperty(
        name="Target Object",
        description="Object to project onto (optional, can be set later)",
        default="",
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None:
            return False
        return obj.type in {"MESH", "CURVE", "CURVES", "POINTCLOUD"}

    def execute(self, context):
        obj = context.active_object
        if obj is None:
            self.report({"ERROR"}, "No active object")
            return {"CANCELLED"}

        ng = ng_mod.ensure_node_group()

        base = MODIFIER_DEFAULT_NAME
        name = base
        idx = 1
        while name in obj.modifiers:
            idx += 1
            name = f"{base}.{idx:03d}"

        mod = obj.modifiers.new(name=name, type="NODES")
        mod.node_group = ng

        if self.target:
            target = bpy.data.objects.get(self.target)
            if target is not None and target is not obj:
                _set_modifier_input(mod, "Target", target)

        self.report({"INFO"}, f"Added '{name}' modifier on {obj.name}")
        return {"FINISHED"}


def _set_modifier_input(mod, socket_name, value):
    """Assign a value to a Geometry Nodes modifier input by socket name."""
    ng = mod.node_group
    if ng is None:
        return
    for item in ng.interface.items_tree:
        if (
            getattr(item, "item_type", "SOCKET") == "SOCKET"
            and getattr(item, "in_out", "INPUT") == "INPUT"
            and item.name == socket_name
        ):
            try:
                mod[item.identifier] = value
            except (TypeError, KeyError):
                pass
            return


def _menu_func(self, context):
    self.layout.operator(
        OBJECT_OT_add_surface_projector_modifier.bl_idname,
        text="Surface Projector",
        icon="MOD_SHRINKWRAP",
    )


_classes = (OBJECT_OT_add_surface_projector_modifier,)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    # The Deform submenu is where Shrinkwrap and Surface Deform live —
    # the projector belongs there as well.
    bpy.types.OBJECT_MT_modifier_add_deform.append(_menu_func)


def unregister():
    try:
        bpy.types.OBJECT_MT_modifier_add_deform.remove(_menu_func)
    except (AttributeError, ValueError):
        pass
    for cls in reversed(_classes):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
