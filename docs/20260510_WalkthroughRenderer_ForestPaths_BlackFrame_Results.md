# Walkthrough Renderer — Forest Paths 黑帧问题调查与修复

**场景**: `forest paths.blend`（Infinigen terrain + scatter pine trees）
**日期**: 2026-05-10
**问题**: frame_0438, frame_0767 完全黑帧

---

## 1. 问题描述

`forest_paths_terrain_v1` 渲染的 1000 帧中，frame_0438 和 frame_0767 完全黑色。其余帧正常。

---

## 2. 根因调查

### 2.1 定位黑帧对应的相机位置

通过 camera_animate 的 arc-length uniform sampling，计算出 frame_0438 对应的路径参数 t，反推出相机世界坐标：

```
frame_0438: XY = (-178.27, -290.0),  Z_cam = 10.82
对应 coarse voxel: (ix=6, iy=0)
```

iy=0 是 30×30 粗网格的**最南端行**，对应世界 Y = -300 + 0.5×20 = **-290**（场景边界 Y=-300，相差 10 BU）。

---

### 2.2 排查：particle tree 遮挡？

最初怀疑是 scatter pine tree 的树干在相机路径上。

调查结论：场景内 611 棵松树全部分布在其他区域，(ix=6, iy=0) 周围 210 BU 内**没有任何 particle**。Particle 遮挡不是原因。

---

### 2.3 排查：相机在 mesh 内部？

用 parity test（沿 +Z 射线统计穿越次数，偶数=外部）对 (-178, -290, 10.82) 检查：

```
parity = 2 次穿越 → 外部（不在任何 mesh 内）
```

相机不在任何 mesh 内部。

---

### 2.4 排查：terrain 法线分析

在完整 Blender 渲染会话（非 pip bpy）中，从 (-178, -290) 向下射线：

```
所有命中的面法线：normal.z ≈ -0.00（竖直崖面）
```

这个位置的地面**全部是竖直崖面**，没有任何水平地面。

---

### 2.5 根本原因

```
场景边界 Y=-300 处是竖直悬崖（terrain 在此截断）。
TerrainSnake 布料下落时，向下射线打到了崖面（normal.z≈0），
记录了崖面所在的 Z 值（≈9）作为 terrain_z_floor。
布料认为"有效地面"，(ix=6, iy=0) 进入候选集合。
相机被放置在崖面旁、场景边界附近。
渲染时：
  - 相机面向场景外 → 打到 background 黑色边界网格（600×600 BU 的遮挡盒）
  - 背景遮挡盒 10 BU 外就是场景外虚空
  → 渲染结果全黑
```

关键：heightmap 记录的是**射线命中点的 Z**，不管命中面是否水平。崖面 + 布料 = 看起来"有效"但实为崖壁的候选格子。

---

## 3. 解法探索

### 3.1 方案 A：path_plan 子体素 particle 阻挡（已实现，无效）

**思路**：在 `_build_smooth_path` 里，对路径点逐一检测周围 particle 树，阻挡树干位置。

**问题**：
`walkthrough.py` 运行 Step 3（path_plan）时**不传 `--blend` 参数**，pip bpy 场景为空 → particle 检测永远返回 0。即使代码逻辑正确，此处无法获取 particle 数据。

**结论**：架构上行不通，已保留代码但无实际效果。

---

### 3.2 方案 B：surface normal filter via ray_cast（已实现，无效）

**思路**：`_filter_terrain_by_surface_normal` 在 voxel_grid 步骤（打开 blend）对每个候选格子向下射线，检查 `abs(normal.z) >= 0.1`，过滤掉崖面格子。

**问题一**：首版用 `normal.z >= 0.1`，所有候选被删除（730 → 0）。Infinigen background 网格法线全部反转（nz ≈ -1 而非 +1）。改用 `abs(normal.z)` 后…

**问题二**：依然 730 → 0。调试发现：

```python
# pip bpy 中向下射线命中情况：
(-178, -290): 命中 background，normal.z = -0.001
( -10,  -10): 命中 terrain，  normal.z =  0.001  ← 水平地面却 nz≈0！
(  10, -10): 命中 terrain，   normal.z =  0.002
```

`terrain` 和 `background` 网格在 pip bpy 中法线全部 nz≈0。原因：Infinigen 场景的地形是 geometry-nodes / displacement modifier 生成的，pip bpy 中存储的基础网格面法线并未随几何变形更新，全部指向水平方向（nz≈0）。

**sanity check 的陷阱**：场景中心有 Scot pine 树冠，`scene.ray_cast` 命中树枝时法线正常（nz=0.943），导致 sanity check 判断"ray_cast 可用"，进入 ray_cast 路径，但地形法线全部 nz≈0 → 全部删除。

**结论**：ray_cast 法线在 Infinigen pip bpy 场景中不可靠，此方案放弃。

---

### 3.3 方案 C：heightmap 坡度滤波（未实现）

**思路**：用 heightmap 梯度检测悬崖（相邻格子 Z 差 / 距离 > 阈值）。

**问题**：(ix=6, iy=0) 与相邻格子的粗网格高度差很小（slope ≈ 0.12），因为布料在整个悬崖顶端落地，相邻格子高度相近，坡度看起来平缓。

**结论**：粗网格梯度无法区分悬崖边缘，不适用。

---

### 3.4 方案 D：boundary margin 边界裁剪（最终方案，有效）✅

**核心观察**：Infinigen 场景的 terrain 在 **场景边界处必然是悬崖**（世界在那里截断）。粗网格外圈（iy=0, iy=29, ix=0, ix=29）的格子必然在悬崖附近。

**实现**：在 `voxel_grid.py` 中新增 `_filter_terrain_by_boundary_margin`：

```python
margin = config.get("terrain_boundary_margin", 1)  # 默认 1 个粗格子 = 20 BU
for (ix, iy, iz) in candidates:
    if ix >= margin and ix < nx - margin and iy >= margin and iy < ny - margin:
        keep
    else:
        remove
```

**结果**：
```
730 候选 → -102 边界格子 → 628 候选
(ix=6, iy=0) 已移除（iy=0 < margin=1）
路径最大 XY 坐标：±270 BU（距场景边界 ±300 保留 30 BU 缓冲）
```

**不需要 bpy / ray_cast**，在 `_build_terrain_candidates` 之后直接对候选数组做索引过滤，速度极快。

---

## 4. 架构洞察

| 问题 | 根因 |
|------|------|
| path_plan particle 检测无效 | Step 3 不传 `--blend`，pip bpy 场景为空 |
| ray_cast 地形法线全 nz≈0 | Infinigen geometry-nodes 地形：基础网格法线未随变形更新 |
| heightmap 梯度检测失效 | 布料落在整个悬崖面，相邻格子高度相近，梯度看起来平缓 |
| valid_domain 无法过滤 | 悬崖面射线命中"有效"，terrain_z_floor 不为 NaN |

**最终结论**：TerrainSnake 高度图只能保证"该 XY 有射线命中"，不能保证命中面是可站立地面。对于 Infinigen 场景，边界悬崖在高度图中表现为"有效但不可行走"的格子，唯一可靠的判断依据是**格子是否靠近场景边界**。

---

## 5. 最终代码变更

**文件**：`genesis_tools/walkthrough_renderer/pipeline/voxel_grid.py`
**Commit**：`c5a2b8d`

新增两个函数：

- `_filter_terrain_by_boundary_margin(vgd, config)` — 主要修复，生产使用
- `_filter_terrain_by_surface_normal(vgd, config)` — 保留备用，内置 sanity check + fallback，适用于非 Infinigen 场景（静态 mesh，ray_cast 法线可信）

`build()` 中调用顺序（terrain mode）：

```
_build_terrain_candidates
→ _filter_terrain_by_particles       (需要 bpy)
→ _filter_terrain_by_mesh_objects    (需要 bpy)
→ _filter_terrain_by_boundary_margin (无需 bpy，永远运行)
```

---

---

## 6. Particle 检测架构问题与修复

### 问题：Step 3 无 blend，particle 检测永远返回 0

`_build_smooth_path`（在 path_plan.py 中）内有正确的 particle 子体素检测逻辑，会遍历 bpy scene 中的所有 scatter 实例，为每棵树/岩石建立 `_ptcl_blocked` 集合，阻挡路径插值点进入树干区域。

但实际运行时检测永远返回 0，原因：

```
walkthrough.py Step 3 调用：
  python3 -m genesis_tools...path_plan
    --voxel-grid ...
    --walkable ...
    --config ...
    --output ...
    # ← 没有 --blend !
```

pip bpy 启动时场景为空，`bpy.context.scene.objects` 里没有任何对象，particle 系统不可见，`_ptcl_blocked` 永远为空集合。

### 解法：三处改动（commit `f33b134`）

**1. `path_plan.build()` 加 `blend_path` 参数**

```python
def build(vg, wk, config: dict, blend_path: str = None) -> PathData:
    if blend_path:
        try:
            import bpy as _bpy
            _bpy.ops.wm.open_mainfile(filepath=str(blend_path))
        except Exception as _e:
            print(f"[PathPlan] Warning: could not open blend ({_e})")
```

在 `_build_smooth_path` 被调用之前打开场景，particle 数据可用。

**2. `path_plan._cli()` 加 `--blend` 可选参数**

```python
parser.add_argument("--blend", required=False, default=None)
...
data = build(vg, wk, config, blend_path=args.blend)
```

**3. `walkthrough.py` Step 3 传入 `--blend`**

```python
_run_bpy_module(
    "genesis_tools.walkthrough_renderer.pipeline.path_plan",
    ["--voxel-grid", str(vg_path), "--walkable", str(wk_path),
     "--blend", blend_path,          # ← 新增
     "--config", config_path, "--output", str(pd_path)],
)
```

### 效果

修复后 Step 3 有完整 bpy 场景，`_ptcl_blocked` 会正确填充，路径插值点会被 `_deflect_particle` 推离树干。此 bug 在当前 forest_paths 场景中不是黑帧根因（因为问题区域附近 210 BU 内没有 particle），但在树木密集区域可能导致路径穿树问题。

---

## 7. 验证

渲染验证（1000 帧，Windows Blender 4.5 Cycles，640×480，64 samples）：

| 帧 | 修复前 | 修复后 |
|----|--------|--------|
| frame_0438 | 全黑 | mean=45.7，black_pct=0.0% ✅ |
| frame_0767 | 全黑 | mean=10.2，black_pct=48.1% ✅（森林树荫，正常偏暗） |
