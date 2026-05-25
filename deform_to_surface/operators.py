"""Operators and UI for the Deform To Surface modifier.

The modifier itself is a Geometry Nodes group built lazily by
``node_group.ensure_node_group``. On top of that this module provides
three operators:

* **Add** the modifier on the active object.
* **Bind** — evaluate the current Target object and snapshot its
  deformed mesh into a hidden Rest Target object. From then on the
  modifier preserves the input geometry's offset to the rest surface
  and follows the live target's deformations (Surface-Deform style).
* **Unbind** — remove a snapshot created by Bind and clear the
  Rest Target socket.

A small sidebar panel in the 3D view exposes the Bind / Unbind buttons
and the most useful modifier inputs without having to dig through the
Properties editor.
"""

from __future__ import annotations

from typing import Optional

import bpy
from bpy.props import StringProperty
from bpy.types import Operator, Panel

from . import node_group as ng_mod


MODIFIER_DEFAULT_NAME = "Deform To Surface"
SNAPSHOT_TAG = "deform_to_surface_rest"


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def _is_our_modifier(mod) -> bool:
    return (
        mod is not None
        and mod.type == "NODES"
        and mod.node_group is not None
        and mod.node_group.name == ng_mod.NODE_GROUP_NAME
    )


def _active_our_modifier(obj) -> Optional[bpy.types.Modifier]:
    if obj is None:
        return None
    mod = obj.modifiers.active
    if _is_our_modifier(mod):
        return mod
    for m in obj.modifiers:
        if _is_our_modifier(m):
            return m
    return None


def _socket_identifier(node_group, socket_name: str) -> Optional[str]:
    for item in node_group.interface.items_tree:
        if (
            getattr(item, "item_type", "SOCKET") == "SOCKET"
            and getattr(item, "in_out", "INPUT") == "INPUT"
            and item.name == socket_name
        ):
            return item.identifier
    return None


def _set_modifier_input(mod, socket_name, value):
    ident = _socket_identifier(mod.node_group, socket_name) if mod.node_group else None
    if ident is None:
        return False
    try:
        mod[ident] = value
    except (TypeError, KeyError):
        return False
    return True


def _get_modifier_input(mod, socket_name):
    ident = _socket_identifier(mod.node_group, socket_name) if mod.node_group else None
    if ident is None:
        return None
    try:
        return mod[ident]
    except (KeyError, TypeError):
        return None


def _snapshot_target(context, target: bpy.types.Object, owner_name: str) -> bpy.types.Object:
    """Create a hidden mesh object holding the evaluated target geometry.

    The snapshot is placed at the target's current world transform so
    that, in the modifier-object's local space, it overlaps the live
    target exactly at bind time.
    """
    depsgraph = context.evaluated_depsgraph_get()
    eval_target = target.evaluated_get(depsgraph)

    # ``new_from_object`` returns a *new* Mesh datablock with all
    # modifiers/shape keys applied (i.e. what the target looks like on
    # screen right now).
    mesh = bpy.data.meshes.new_from_object(
        eval_target, preserve_all_data_layers=False, depsgraph=depsgraph
    )
    mesh.name = f"{target.name}_RestMesh"

    snap_name = f"{owner_name}_RestTarget"
    snap = bpy.data.objects.new(snap_name, mesh)
    snap.matrix_world = target.matrix_world.copy()
    # NOTE: do NOT use ``snap.hide_viewport = True`` here — that's the
    # *monitor* icon which removes the object from depsgraph evaluation,
    # so ``Sample Nearest Surface`` on the rest target would return
    # ``Is Valid = False`` and the bound branch would silently fall back
    # to plain (flattening) projection. Hide via the view-layer eye icon
    # and minimise the display instead, both of which keep the object
    # fully evaluated.
    snap.hide_render = True
    snap.hide_select = True
    snap.display_type = "WIRE"
    snap[SNAPSHOT_TAG] = True

    # Link into the same collection as the modifier owner, or fall back
    # to the scene's root collection.
    coll = None
    owner = bpy.data.objects.get(owner_name)
    if owner is not None and owner.users_collection:
        coll = owner.users_collection[0]
    if coll is None:
        coll = context.scene.collection
    coll.objects.link(snap)

    # View-layer hide (eye icon) — keeps depsgraph evaluation alive.
    try:
        snap.hide_set(True)
    except (RuntimeError, AttributeError):
        # ``hide_set`` may fail in odd contexts (e.g. when called from a
        # script outside the active view layer). The snapshot will still
        # work; it will just be visible. ``display_type='WIRE'`` keeps
        # the visual noise minimal.
        pass

    return snap


def _remove_snapshot(snap: bpy.types.Object) -> None:
    """Delete a snapshot object and its mesh datablock if we own it."""
    if snap is None or not snap.get(SNAPSHOT_TAG):
        return
    mesh = snap.data
    bpy.data.objects.remove(snap, do_unlink=True)
    if isinstance(mesh, bpy.types.Mesh) and mesh.users == 0:
        bpy.data.meshes.remove(mesh)


def _bind_modifier(context, obj, mod):
    """Snapshot the current Target into a Rest Target on ``mod``.

    Returns ``(ok, message)`` so callers can surface errors via ``report``.
    Removes any existing snapshot owned by us so re-binding is safe.
    """
    if not _is_our_modifier(mod):
        return False, "Not a Deform To Surface modifier"

    target = _get_modifier_input(mod, "Target")
    if target is None:
        return False, "Set a Target object before binding"
    if target is obj:
        return False, "Target cannot be the deformed object itself"
    if target.type != "MESH":
        return False, "Target must be a mesh object"

    old_rest = _get_modifier_input(mod, "Rest Target")
    if old_rest is not None and old_rest.get(SNAPSHOT_TAG):
        _remove_snapshot(old_rest)

    snap = _snapshot_target(context, target, obj.name)
    _set_modifier_input(mod, "Rest Target", snap)
    _set_modifier_input(mod, "Use Bind", True)
    return True, f"Bound to '{target.name}' (rest: '{snap.name}')"


# ──────────────────────────────────────────────────────────────────────
# Operators
# ──────────────────────────────────────────────────────────────────────

class OBJECT_OT_add_deform_to_surface_modifier(Operator):
    """Add a Deform To Surface modifier on the active object."""

    bl_idname = "object.deform_to_surface_modifier_add"
    bl_label = "Add Deform To Surface Modifier"
    bl_options = {"REGISTER", "UNDO"}

    target: StringProperty(
        name="Target Object",
        description="Object to deform onto (optional, can be set later)",
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

        bound_msg = None
        if self.target:
            target = bpy.data.objects.get(self.target)
            if target is not None and target is not obj:
                _set_modifier_input(mod, "Target", target)
                # Auto-bind: without binding the modifier projects every
                # point onto the closest surface point, which flattens
                # the input mesh against the target. With a snapshot of
                # the target as the rest pose, the modifier behaves
                # like Surface Deform and preserves the input's relief.
                if target.type == "MESH":
                    ok, bound_msg = _bind_modifier(context, obj, mod)
                    if not ok:
                        self.report({"WARNING"}, bound_msg)

        # Make the new modifier active so the sidebar panel picks it up.
        try:
            obj.modifiers.active = mod
        except AttributeError:
            pass

        if bound_msg and "Bound" in bound_msg:
            self.report({"INFO"}, f"Added '{name}' on {obj.name} — {bound_msg}")
        else:
            self.report({"INFO"}, f"Added '{name}' modifier on {obj.name}")
        return {"FINISHED"}


class OBJECT_OT_deform_to_surface_bind(Operator):
    """Bind the modifier: snapshot the current target into a Rest Target.

    After binding, the modifier preserves the offset of every input
    point relative to the rest surface and follows the live target's
    deformations.
    """

    bl_idname = "object.deform_to_surface_bind"
    bl_label = "Bind"
    bl_options = {"REGISTER", "UNDO"}

    modifier: StringProperty(default="")

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return _active_our_modifier(obj) is not None

    def execute(self, context):
        obj = context.active_object
        mod = (
            obj.modifiers.get(self.modifier) if self.modifier else None
        ) or _active_our_modifier(obj)
        if mod is None:
            self.report({"ERROR"}, "No Deform To Surface modifier on active object")
            return {"CANCELLED"}

        ok, msg = _bind_modifier(context, obj, mod)
        self.report({"INFO" if ok else "ERROR"}, msg)
        return {"FINISHED" if ok else "CANCELLED"}


class OBJECT_OT_deform_to_surface_unbind(Operator):
    """Unbind the modifier and remove the rest-pose snapshot."""

    bl_idname = "object.deform_to_surface_unbind"
    bl_label = "Unbind"
    bl_options = {"REGISTER", "UNDO"}

    modifier: StringProperty(default="")

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        mod = _active_our_modifier(obj)
        if mod is None:
            return False
        return _get_modifier_input(mod, "Use Bind") or (
            _get_modifier_input(mod, "Rest Target") is not None
        )

    def execute(self, context):
        obj = context.active_object
        mod = (
            obj.modifiers.get(self.modifier) if self.modifier else None
        ) or _active_our_modifier(obj)
        if mod is None:
            self.report({"ERROR"}, "No Deform To Surface modifier on active object")
            return {"CANCELLED"}

        rest = _get_modifier_input(mod, "Rest Target")
        _set_modifier_input(mod, "Use Bind", False)
        _set_modifier_input(mod, "Rest Target", None)
        if rest is not None and rest.get(SNAPSHOT_TAG):
            _remove_snapshot(rest)
        self.report({"INFO"}, "Unbound")
        return {"FINISHED"}


# ──────────────────────────────────────────────────────────────────────
# Sidebar panel
# ──────────────────────────────────────────────────────────────────────

class VIEW3D_PT_deform_to_surface(Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Deform"
    bl_label = "Deform To Surface"

    @classmethod
    def poll(cls, context):
        return context.active_object is not None

    def draw(self, context):
        layout = self.layout
        obj = context.active_object
        mod = _active_our_modifier(obj)

        if mod is None:
            layout.label(text="No Deform To Surface modifier")
            layout.operator(
                OBJECT_OT_add_deform_to_surface_modifier.bl_idname,
                text="Add Modifier",
                icon="MOD_MESHDEFORM",
            )
            return

        layout.label(text=mod.name, icon="MOD_MESHDEFORM")

        ng = mod.node_group
        col = layout.column(align=True)
        for socket_name in (
            "Target", "Factor", "Normal Offset", "Strength",
            "Smooth Iterations", "Smooth Weight",
        ):
            ident = _socket_identifier(ng, socket_name)
            if ident is None:
                continue
            try:
                col.prop(mod, f'["{ident}"]', text=socket_name)
            except TypeError:
                continue

        bound = bool(_get_modifier_input(mod, "Use Bind"))
        row = layout.row(align=True)
        if bound:
            row.operator(
                OBJECT_OT_deform_to_surface_unbind.bl_idname,
                text="Unbind", icon="UNLINKED",
            )
        else:
            row.operator(
                OBJECT_OT_deform_to_surface_bind.bl_idname,
                text="Bind", icon="LINKED",
            )

        rest = _get_modifier_input(mod, "Rest Target")
        if rest is not None:
            layout.label(text=f"Rest: {rest.name}", icon="MESH_DATA")


# ──────────────────────────────────────────────────────────────────────
# Registration
# ──────────────────────────────────────────────────────────────────────

def _menu_func(self, context):
    self.layout.operator(
        OBJECT_OT_add_deform_to_surface_modifier.bl_idname,
        text="Deform To Surface",
        icon="MOD_MESHDEFORM",
    )


_classes = (
    OBJECT_OT_add_deform_to_surface_modifier,
    OBJECT_OT_deform_to_surface_bind,
    OBJECT_OT_deform_to_surface_unbind,
    VIEW3D_PT_deform_to_surface,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
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
