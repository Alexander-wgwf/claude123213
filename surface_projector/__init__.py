"""Surface Projector Modifier — Blender 5.0+ extension.

Adds a custom modifier that projects every point of the input geometry
onto the surface of a target object, either by snapping to the closest
point on the surface or by raycasting along the input normal.
"""

from __future__ import annotations

from . import node_group, operators


def register():
    operators.register()


def unregister():
    operators.unregister()
    node_group.remove_node_group()
