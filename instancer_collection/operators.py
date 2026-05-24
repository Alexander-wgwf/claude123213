"""Operators that add the Instancer Collection modifier to an object."""

from __future__ import annotations

import bpy
from bpy.props import StringProperty
from bpy.types import Operator

from . import node_group as ng_mod


MODIFIER_DEFAULT_NAME = "Instancer Collection"


class OBJECT_OT_add_instancer_collection_modifier(Operator):
    """Add an Instancer Collection modifier on the active object.

    The modifier wraps a Geometry Nodes group that takes a collection as input
    and outputs the collection's objects as instances (optionally realized as
    real geometry so that following modifiers in the stack can edit it).
    """

    bl_idname = "object.instancer_collection_modifier_add"
    bl_label = "Add Instancer Collection Modifier"
    bl_options = {"REGISTER", "UNDO"}

    collection: StringProperty(
        name="Collection",
        description="Collection to instance (optional, can be set later)",
        default="",
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None:
            return False
        return obj.type in {
            "MESH",
            "CURVE",
            "CURVES",
            "POINTCLOUD",
            "VOLUME",
            "EMPTY",
        }

    def execute(self, context):
        obj = context.active_object
        if obj is None:
            self.report({"ERROR"}, "No active object")
            return {"CANCELLED"}

        ng = ng_mod.ensure_node_group()

        # Find a unique modifier name on the object.
        base = MODIFIER_DEFAULT_NAME
        name = base
        idx = 1
        while name in obj.modifiers:
            idx += 1
            name = f"{base}.{idx:03d}"

        mod = obj.modifiers.new(name=name, type="NODES")
        mod.node_group = ng

        if self.collection:
            coll = bpy.data.collections.get(self.collection)
            if coll is not None:
                _set_modifier_input(mod, "Collection", coll)

        self.report({"INFO"}, f"Added '{name}' modifier on {obj.name}")
        return {"FINISHED"}


def _set_modifier_input(mod, socket_name, value):
    """Assign a value to a Geometry Nodes modifier input by socket name.

    Modifier inputs are keyed by the interface socket identifier in newer
    Blender versions; we look it up from the node group's interface tree.
    """
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
        OBJECT_OT_add_instancer_collection_modifier.bl_idname,
        text="Instancer Collection",
        icon="OUTLINER_OB_GROUP_INSTANCE",
    )


_classes = (OBJECT_OT_add_instancer_collection_modifier,)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.OBJECT_MT_modifier_add_generate.append(_menu_func)


def unregister():
    try:
        bpy.types.OBJECT_MT_modifier_add_generate.remove(_menu_func)
    except (AttributeError, ValueError):
        pass
    for cls in reversed(_classes):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
