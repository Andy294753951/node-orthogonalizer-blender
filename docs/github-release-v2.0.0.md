# GitHub Release 文案：v2.0.0

## Release title

**v2.0.0 — Node Orthogonalizer for Blender 5.2**

## Release body

Node Orthogonalizer 2.0.0 is a Blender 5.2 maintenance release focused on automatic, exact right-angle routing across Shader Editor, Compositor, and Geometry Nodes.

### Highlights

- Renamed the public add-on to **Node Orthogonalizer**.
- Renamed the Blender entry module to `node_orthogonalizer.py`.
- Fixed Blender 5.2 Geometry Nodes Bake output-socket coordinates.
- Added alignment support for dynamic Bake geometry, value, and vector rows.
- Revalidated automatic routing in a complex Geometry Nodes tree: 14 reroutes, 0 diagonal segments.
- Retained the persistent automatic watcher for `.blend` file changes.

### Installation

Download `node-orthogonalizer-blender-5.2-v2.0.0.zip`, then install `node_orthogonalizer.py` from **Edit > Preferences > Add-ons > Install**.

Restart Blender after replacing an earlier build.

### Compatibility

Tested with Blender 5.2.0 LTS on Windows. Other Blender versions may work, but are not covered by this release's validation.

### Attribution

This project is a maintained rework of the older open-source Square Noodles add-on by Kai Christensen: https://github.com/mkaic/square-noodles

Licensed under GPL-3.0. See [`LICENSE`](../LICENSE).
