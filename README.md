# Node Orthogonalizer for Blender 5.2

> Automatically turns Blender node links into clean, exact right-angle routes.

Node Orthogonalizer is a maintained Blender add-on for organizing node links in Shader Editor, Compositor, Geometry Nodes, and other node-based editors. It adds reroute nodes where needed so connections remain horizontal, vertical, and easy to read.

## 中文简介

这是一个面向 Blender 5.2 的节点连线整理插件。它可以自动把着色器、合成器和几何节点中的连线整理成标准 90° 直角线路，适合复杂材质、MMD 模型材质和 Geometry Nodes 工程。

当前维护版重点修复了 Blender 5.2 的节点插口坐标变化，并对 Bake、合成器节点、Principled BSDF、Mapping、Noise、材质输出和 MMDShaderDev 等布局进行了适配。

## Features

- Automatic orthogonal routing after nodes or links change.
- Manual command from `F3`: **Node Orthogonalize**.
- Default shortcut: `Shift + ,`.
- Works in Shader Editor, Compositor, Geometry Nodes, and other node editors.
- Supports Blender 5.2 dynamic Geometry Nodes Bake sockets.
- Keeps existing reroute nodes aligned and adds new reroutes only where required.
- Preferences for automatic mode, delay, selected/all-node processing, tolerance, reroute nudging, and noodle spacing.

## Installation

1. Download the release ZIP from GitHub, or download this repository as a ZIP.
2. In Blender, open **Edit > Preferences > Add-ons**.
3. Click **Install**, then select `node_orthogonalizer.py`.
4. Enable **Node Orthogonalizer**.
5. Restart Blender after replacing an older installed copy so Blender unloads the previous module.

The ZIP release contains the entry file at its root, so it can be installed directly from Blender's Add-ons panel.

## Usage

Automatic routing is enabled by default. After moving nodes or changing links, the add-on waits briefly for the layout to settle and then processes the active node tree.

For a one-time operation, select the relevant nodes and use **F3 > Node Orthogonalize** or press `Shift + ,`. Press `F9` immediately afterward to adjust the operator settings.

Automatic behavior can be changed under **Edit > Preferences > Add-ons > Node Orthogonalizer**:

- **Automatic Orthogonalization**: enable or disable the watcher.
- **Automatic Delay**: wait time after a node-tree change.
- **Process All Linked Nodes**: process the complete active tree or only selected nodes.

The manual operator settings are:

- **Tolerance**: ignore links that are already close to horizontal or vertical.
- **Nudge Limit**: maximum movement allowed for an existing reroute node.
- **Noodle Margin**: spacing used when several outputs share a route.

## Blender 5.2 support

Version 2.0.0 was tested in Blender 5.2.0 LTS with:

- Shader nodes, including Principled BSDF, Mapping, Noise, Material Output, and MMDShaderDev groups.
- Compositor nodes with Blender 5.2's compositor tree API.
- Geometry Nodes with dynamic Bake sockets and Domain Size.
- A complex Geometry Nodes test containing geometry, value, and vector Bake data.

The complex automatic test produced 14 reroute nodes and 0 non-orthogonal link segments.

## Screenshots

### Shader node routing

![Shader node routing](docs/images/shader-node-routing.png)

### Geometry Nodes complex scene

![Geometry Nodes complex scene](docs/images/geometry-nodes-complex-scene.png)

### Compositor complex scene

![Compositor complex scene](docs/images/compositor-complex-scene.png)

## Changelog

### 2.0.0

- Renamed the public add-on to **Node Orthogonalizer**.
- Fixed Blender 5.2 Geometry Nodes Bake output-socket positioning.
- Added support for dynamic Bake data rows while preserving exact input/output alignment.
- Revalidated automatic routing in a complex Geometry Nodes tree.

### 1.4.2

- Made the automatic watcher persistent when opening or switching `.blend` files.

### 1.4.1

- Added Blender 5.2 compositor socket-layout handling.

## Credits and license

This project is a maintained rework of the older open-source **Square Noodles** add-on. Original upstream credit: Kai Christensen, [mkaic/square-noodles](https://github.com/mkaic/square-noodles).

This maintained version is distributed under the GNU General Public License v3.0. See [`LICENSE`](LICENSE).
