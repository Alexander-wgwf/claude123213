# Blender Modifier Extensions

This repo ships two small Blender 5.0+ extensions that add custom modifiers
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

Both extensions create their Geometry Nodes group lazily when the
modifier is first added, so they leave a clean scene if you never use
them.
