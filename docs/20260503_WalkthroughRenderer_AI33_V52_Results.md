# AI33_001 Walkthrough — v52: 修复 aerial 模式的 camera_height 偏移

**Scene**: `AI33_001_280.blend` (unit_scale=0.01, 1 BU = 1 cm)
**Date**: 2026-05-03
**Render**: Windows Blender 4.5 + WORKBENCH (D3D GPU, ~0.01s/frame)

---

## 根本原因：camera_height 在 aerial 模式下不应叠加

`camera_animate.py` 和 `camera_orient.py` 无条件地将 `cam_h = camera_height / unit_scale = 170 BU` 叠加到每个路径点的 Z 坐标：

```python
cam_pos = path_pt + Vector((0, 0, cam_h))  # 之前：无论 aerial 与否均叠加
```

**非 aerial 模式**：路径点 = 地板 Z（walkable voxel 紧贴地板上方），叠加 cam_h 得到眼高，这是正确的。

**aerial 模式**：路径点 = 空中三维飞行位置（不是地板）。叠加 170 BU 后：

- walkable voxel 最高 z=12（中心 604 BU = 6.04m）
- camera Z = 604 + 170 = **774 BU = 7.74m**，超出整个建筑范围（grid max = 779 BU）

### 修复

```python
# camera_animate.py + camera_orient.py
if config.get("aerial"):
    cam_h = 0.0   # 路径点就是摄像机位置，无需叠加眼高偏移
else:
    cam_h = config.get("camera_height", 1.7) / unit_scale
```

修复后：camera Z = path point Z，始终在 walkable voxel 范围内（经 edge-mesh 验证为内部空气）。

---

## GIF

**v52 — 6-connected BFS + aerial cam_h=0 (waypoint gaze mode):**

![v52](assets/ai33_001_walkthrough_v52/ai33_v52_aerial.gif)

---

## Debug Visualization

**XY 俯视 (top view) — v52:**

![v52 top](assets/ai33_001_walkthrough_v52/debug_top.png)

**XZ 侧视 (side view) — v52:**

![v52 side](assets/ai33_001_walkthrough_v52/debug_side.png)

---

## v51 vs v52 对比

| 指标 | v51 (cam_h=170 BU 错误叠加) | v52 (aerial cam_h=0) |
|------|---------------------------|---------------------|
| walkable voxels | 5162 (z=1..12) | 5162 (z=1..12) |
| camera Z range | 224..774 BU (2.24..7.74m) | **54..604 BU (0.54..6.04m)** |
| camera 超出 walkable max | **+170 BU** | **0 BU** |
| 天棚穿模 | **严重**（774 BU 超出建筑）| **消除** |
| Frames | 1,405 | 1,405 |
| 路径段数/长度 | 1124 / 12.5 BU | 1124 / 12.5 BU |

---

## 文件

| 内容 | 路径 |
|------|------|
| GIF | `docs/assets/ai33_001_walkthrough_v52/ai33_v52_aerial.gif` |
| Debug top | `docs/assets/ai33_001_walkthrough_v52/debug_top.png` |
| Debug side | `docs/assets/ai33_001_walkthrough_v52/debug_side.png` |
| Run script | `run_ai33_v52.py` |
| Debug render | `render_debug_viz_v52.py` |
| GIF script | `make_gif_v52.py` |
