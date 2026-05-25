# Blender Modifier Extensions

This repo ships three small Blender 5.0+ extensions that add custom modifiers
implemented as Geometry Nodes groups.

## `instancer_collection/` — Instancer Collection Modifier

Turns a Blender [Collection](https://docs.blender.org/manual/en/latest/scene_layout/collections/introduction.html)
into instanced geometry inside the modifier stack so any following
modifiers (Array, Bevel, Subdivision Surface, Geometry Nodes, …) keep
operating on the result.

Inputs: `Geometry`, `Collection`, `Separate Children`, `Reset Children`,
`Realize Instances`, `Replace Input`.

## `surface_projector/` — Surface Projector Modifier

Projects every point of the input geometry onto the surface of a target
object, similar in spirit to the built-in *Shrinkwrap* / *Surface Deform*
modifiers but as a Geometry Nodes asset that you can stack and re-order
freely.

Modes:

- **Closest Point** (default) — every input point snaps to the closest
  point on the target surface.
- **Raycast** — every input point is raycast along its own (optionally
  inverted) normal; the surface hit becomes the new position. Points
  whose ray misses the target stay where they were.

Inputs: `Geometry`, `Target`, `Use Raycast`, `Invert Ray`, `Ray Length`,
`Factor` (0 = keep original, 1 = fully project), `Offset` (signed
distance along the surface normal), `Selection` (per-point mask).

## `deform_to_surface/` — Deform To Surface Modifier

High-quality projection of one mesh onto another, with optional
**bind-pose** wrapping that mimics Blender's built-in *Surface Deform*:

- Samples the target with `Sample Nearest Surface` so the projected
  positions and normals are smoothly **interpolated across faces**
  instead of snapping to triangle centres — no faceted artifacts.
- Optional **Bind**: snapshots the live target, then for each input
  vertex stores its offset to that rest surface in the rest surface's
  **tangent frame** (signed normal distance + two tangent components).
  When the live target deforms, the offsets are reconstructed in the
  new tangent frames so the geometry wraps and follows the target
  surface like cloth — preserving the relief of the original mesh.
- Built-in **post-blur smoothing pass** (Blur Attribute) to clean up
  high-frequency noise even on coarse targets.

Inputs: `Geometry`, `Target`, `Rest Target`, `Use Bind`, `Factor`,
`Normal Offset`, `Strength` (rest relief scale), `Smooth Iterations`,
`Smooth Weight`, `Selection`.

A sidebar panel (`3D View → Sidebar → Deform`) exposes **Bind** /
**Unbind** buttons and the common modifier inputs without having to
dig through the Properties editor. Bind creates a snapshot of the
evaluated target, sets it as `Rest Target`, and flips `Use Bind` on.
Unbind removes the snapshot and clears the socket.

Without binding, each point is offset along the surface normal by its
signed perpendicular distance to the closest surface point, which
preserves the input mesh's height/thickness above the target instead
of flattening everything onto the surface — Bind is still required to
preserve full tangent-direction relief.

## Installation

Each extension lives in its own folder. To install:

1. Zip the extension's folder (e.g. `instancer_collection/` →
   `instancer_collection.zip`).
2. In Blender 5.0+ open **Edit → Preferences → Get Extensions → Install
   from Disk…** and select the zip.
3. Enable the extension.

## Usage

In the Properties editor open the **Modifier** tab:

- **Add Modifier → Generate → Instancer Collection** for the collection
  instancer.
- **Add Modifier → Deform → Surface Projector** for the surface
  projector.
- **Add Modifier → Deform → Deform To Surface** for the bind-based
  surface deformer.

All three extensions create their Geometry Nodes group lazily when the
modifier is first added, so they leave a clean scene if you never use
them.
