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

Projects a whole object onto the surface of another while **keeping its
original shape and volume** — inspired by the *Deform To Surface* /
*Surface Deform* family of tools.

For every vertex it raycasts a *single, shared projection axis* against
the target. The vertex's offset along the axis is preserved, so the
source rides along the target's surface contour rather than collapsing
flat onto it.

### Projection modes

The `Wrap` slider (0..1) continuously blends between three behaviours:

- **Project** (`Wrap = 0`) — every vertex is translated *parallel to the
  axis*. The source keeps its silhouette; great for "drop" workflows.
- **Target Normal** (`Wrap = 1`) — every vertex is lifted along the
  *target's* surface normal at the hit point. The source wraps the
  surface.
- **Flow to Surface** (`0 < Wrap < 1`) — smooth blend of the two; the
  object bends along the surface without fully aligning to it.

`Preserve Shape = false` falls back to a flat "decal/squish" behaviour
where every vertex is snapped directly onto the surface.

### Automatic axis

`Auto Axis = true` (default) computes the projection axis as the world
axis pointing from the source bounding-box centre to the target
bounding-box centre — so the projector works no matter where the source
sits relative to the target. Disable it to use the explicit
`Manual Axis` vector instead. `Invert Axis` flips whichever axis is
active.

### Inputs

| Socket          | Default            | Description                                            |
|-----------------|--------------------|--------------------------------------------------------|
| `Geometry`      | —                  | Source geometry to project.                            |
| `Target`        | —                  | Object whose surface is the target.                    |
| `Preserve Shape`| ✅                 | Keep the source's volume (lift each vertex).           |
| `Wrap`          | 0.0                | 0 = Project, 1 = Target Normal, in-between = Flow.     |
| `Auto Axis`     | ✅                 | Detect projection axis from bbox positions.            |
| `Manual Axis`   | `(0, 0, -1)`       | Used when Auto Axis is off.                            |
| `Invert Axis`   | ❌                 | Flip the active axis.                                  |
| `Factor`        | 1.0                | 0 = original position, 1 = fully projected.            |
| `Offset`        | 0.0                | Signed distance above the surface (effective normal).  |
| `Ray Length`    | 1000               | Maximum raycast distance.                              |
| `Selection`     | ✅                 | Per-point selection mask.                              |

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
