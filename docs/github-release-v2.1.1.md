# Node Orthogonalizer v2.1.1 — Blender 5.2 节点树布局与直角连线

Node Orthogonalizer v2.1.1 is a Blender 5.2 LTS extension for creating exact
90-degree node routes and organizing selected nodes as readable dependency trees.

## 本次更新

- 新增节点编辑器 `N` 侧栏中的 **Orthogonalizer** 标签。
- 新增树状布局、按距离紧凑布局和组输入/组输出优化工具。
- 支持进入节点组内部操作，以及选中 Frame 后整理框架内节点。
- 修复复杂节点组中自动模式不生效或反复触发导致卡顿的问题。
- 改进着色器、合成器和几何节点中的精确 90° 对齐。
- 保留 Frame 父子关系、节点数据、插口、链接及已有重路由约束。

## 安装

下载 `node-orthogonalizer-blender-5.2-v2.1.1.zip`，在 Blender 5.2 中打开：

**编辑 > 偏好设置 > 扩展 > 右上角菜单 > 从磁盘安装**

直接选择 ZIP，不要解压。覆盖旧版本后建议完整重启 Blender。

## 使用侧栏

把鼠标放在节点编辑器中，按 `N`，然后打开：

**Orthogonalizer > Node Orthogonalizer**

如果鼠标位于 3D 视图，`N` 键打开的是 3D 视图侧栏，不会显示本扩展标签。

## Compatibility

- Blender 5.2.0 LTS
- Shader Editor
- Compositor
- Geometry Nodes
- Nested node groups and Frame-parented nodes

License: GPL-3.0-or-later.
