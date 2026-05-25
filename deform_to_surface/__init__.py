"""Deform To Surface Modifier — Blender 5.0+ extension.

Adds a custom modifier that projects every point of the input geometry
onto a target surface with very high quality:

* Smooth interpolated surface normals (Sample Nearest Surface), so the
  projection follows the *shaded* surface rather than the raw triangle
  fan and avoids the typical faceted artifacts of closest-point snapping.
* Optional rest-pose binding. When a Rest Target is supplied, each
  input vertex stores its offset to the *rest* surface in the rest
  surface's tangent frame, then reconstructs that offset on the live
  Target's tangent frame — so the geometry wraps and follows the
  Target's deformations like Blender's built-in Surface Deform.
* Post-projection smoothing pass (Blur Attribute) for clean wrapping
  even on coarse targets.
"""

from __future__ import annotations

from . import node_group, operators


def register():
    operators.register()


def unregister():
    operators.unregister()
    node_group.remove_node_group()
