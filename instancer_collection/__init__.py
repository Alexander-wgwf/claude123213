"""Instancer Collection Modifier — Blender 5.0+ extension.

Adds a custom modifier that turns a Blender Collection into instanced
geometry inside the modifier stack, so following modifiers can keep
operating on the result (optionally realized into real geometry).
"""

from __future__ import annotations

from . import node_group, operators


def register():
    operators.register()


def unregister():
    operators.unregister()
    node_group.remove_node_group()
