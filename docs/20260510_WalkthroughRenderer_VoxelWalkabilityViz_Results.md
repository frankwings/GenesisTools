# Voxel Walkability Overlay Visualization — Forest Paths Terrain V1

**场景**: `forest paths.blend`（Infinigen terrain + scatter pine trees）  
**日期**: 2026-05-10  
**目的**: 在 TerrainSnake heightmap 可视化上叠加 voxel walkability map，直观显示哪些 coarse voxel 可行走、哪些被过滤掉

---

## 1. 背景

`voxel_grid.npz` 保存了 walkthrough pipeline 过滤后的候选 voxel（`candidates` 数组）。此前 TerrainSnake visualization（figure 0–5）只展示 heightmap 和 camera path，无法直观看到 voxel 过滤的效果。

本次新增 **figure_6_voxel_walkability.png**，在 heightmap 背景上叠加颜色编码的 coarse voxel 格子，供调试 boundary margin、particle filter 等过滤步骤使用。

---

## 2. 实现

### 2.1 数据加载（`_load_terrain_data`）

在 `TerrainData` dataclass 新增 7 个字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `vg_walkable` | `(vg_nx, vg_ny) bool` | 通过所有过滤器的 walkable voxel |
| `vg_valid` | `(vg_nx, vg_ny) bool` | valid terrain domain（过滤前，通过 fine valid_floor 反推）|
| `vg_nx, vg_ny` | int | coarse grid 尺寸 |
| `vg_res` | float | coarse cell 边长（m） |
| `vg_bounds` | tuple | 6-元素世界坐标范围 |
| `has_voxels` | bool | 是否成功加载 voxel_grid.npz |

`vg_valid` 的重建方式：对每个 coarse cell `(ix_c, iy_c)`，检查对应的 fine grid 区块 `valid_floor[fx0:fx1, fy0:fy1]` 是否有任何 True，有则标记为 valid。

### 2.2 Figure 6（`terrain_figure_6`）

双面板布局（当 `has_path=True` 时）：

- **Panel A**：heightmap（terrain colormap）+ voxel walkability overlay
- **Panel B**：heightmap + overlay + path（plasma colormap，start→end）+ waypoints（numbered）

颜色方案：

| 颜色 | 含义 |
|------|------|
| 绿色 `(0, 0.75, 0, 0.45)` | walkable — 通过所有过滤器，进入候选集合 |
| 红色 `(0.9, 0, 0, 0.40)` | valid domain 内但被过滤掉（boundary margin、particle filter 等）|
| 透明 | 完全不在 valid terrain domain 内 |

Overlay 以 coarse voxel 分辨率（`vg_res` m/cell）生成 `(vg_ny, vg_nx, 4)` RGBA 数组，`imshow(interpolation="nearest")` 覆盖在 heightmap 上，extent 与 heightmap 相同。

---

## 3. Forest Paths Terrain V1 结果

**场景参数**：30×30 coarse grid，20 m/cell，world bounds ±300 BU  
**Commit**: [figure_6 implementation + vg_valid loading]  

### 统计

| 类别 | 数量 |
|------|------|
| 总 coarse cells | 900（30×30）|
| vg_valid（有地形命中）| 871 |
| walkable（过滤后候选）| 628 |
| 被过滤掉（valid but excluded）| 243 |

### Figure 6 — Voxel Walkability Overlay

![figure_6_voxel_walkability](../results/forest_paths_terrain_v1/viz/figure_6_voxel_walkability.png)

**解读**：
- 绿色格子 = 628 个 walkable voxel，相机路径只在这些格子内生成
- 红色格子 = 243 个被过滤掉的 voxel，包含：
  - 外圈 1 格（`terrain_boundary_margin=1`）共 ≈116 格 — boundary margin 过滤（修复黑帧的关键）
  - particle 遮挡的格子（scatter pine trees）
  - mesh object 遮挡的格子
- 右侧 Panel B 叠加了 camera path（plasma 颜色，blue=start, yellow=end）和编号 waypoints
- 路径完全在绿色区域内，无路径点落在红色区域 ✅

### 参考图（其他 figures）

| Figure | 文件 |
|--------|------|
| 0 — Initial vs Final Cloth | `../results/forest_paths_terrain_v1/viz/figure_0_initial_vs_final.png` |
| 1 — Top-Down Coverage | `../results/forest_paths_terrain_v1/viz/figure_1_top_down.png` |
| 2 — Side Profiles | `../results/forest_paths_terrain_v1/viz/figure_2_side_profiles.png` |
| 3 — Bridging Demo | `../results/forest_paths_terrain_v1/viz/figure_3_bridging_demo.png` |
| 4 — Convergence | `../results/forest_paths_terrain_v1/viz/figure_4_convergence.png` |
| 5 — Walkthrough Path | `../results/forest_paths_terrain_v1/viz/figure_5_walkthrough_path.png` |
| **6 — Voxel Walkability** | `../results/forest_paths_terrain_v1/viz/figure_6_voxel_walkability.png` |

---

## 4. 代码变更摘要

**文件**: `genesis_tools/active_contour/visualize.py`

1. `TerrainData` dataclass — 新增 7 个 voxel overlay 字段
2. `_load_terrain_data()` — 加载 `voxel_grid.npz`，构建 `vg_walkable` 和 `vg_valid`
3. `terrain_figure_6()` — 新函数：生成双面板 voxel walkability overlay figure
4. `run_terrain_snake()` — 新增调用 `terrain_figure_6(td, out_dir)`
5. 模块 docstring — 更新 figure 列表（figure 5/6）

当 `voxel_grid.npz` 不存在时，`terrain_figure_6` 静默跳过（`has_voxels=False`），不影响其他 figures。

---

## 5. 使用方法

```bash
# 生成所有 TerrainSnake figures（包括 figure 6）
python genesis_tools/active_contour/visualize.py terrain results/forest_paths_terrain_v1

# 输出到 results/forest_paths_terrain_v1/viz/
#   figure_6_voxel_walkability.png  ← 新增
```
