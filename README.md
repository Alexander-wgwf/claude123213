# Instancer Collection Modifier

A Blender 5.0+ extension that adds an **Instancer Collection** modifier to
the modifier stack.

The modifier turns a Blender [Collection](https://docs.blender.org/manual/en/latest/scene_layout/collections/introduction.html)
into instanced geometry inside the modifier stack, so any modifiers placed
after it (Array, Bevel, Subdivision Surface, Geometry Nodes, etc.) keep
operating on the resulting geometry.

Under the hood it is a small Geometry Nodes tree exposed as a modifier — the
same mechanism Blender itself uses for built-in geometry-nodes-based
modifiers since 4.x.

## Inputs

| Socket             | Default | Description                                                                                              |
|--------------------|---------|----------------------------------------------------------------------------------------------------------|
| `Geometry`         | —       | The geometry coming from the previous modifier in the stack.                                              |
| `Collection`       | —       | Collection of objects to instance.                                                                        |
| `Separate Children`| ✅      | Instance each child of the collection separately (otherwise the collection becomes one merged instance). |
| `Reset Children`   | ❌      | Reset the transforms of the children before instancing them.                                              |
| `Realize Instances`| ✅      | Turn the instances into real geometry so subsequent modifiers can edit it. Turn off to keep instances.    |
| `Replace Input`    | ❌      | Replace the input geometry with the collection (instead of joining the collection on top of it).         |

## Installation

1. Zip the `instancer_collection/` folder.
2. In Blender 5.0+ open **Edit → Preferences → Get Extensions → Install from Disk…** and select the zip.
3. Enable the extension.

## Usage

1. Select a target object (mesh, curve, empty…).
2. In the Properties editor open the **Modifier** tab and click
   **Add Modifier → Generate → Instancer Collection**.
3. Pick a collection in the modifier's *Collection* field.
4. Add further modifiers below it as usual.
