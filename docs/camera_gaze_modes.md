# Camera Gaze Modes — WalkthroughRenderer

Config key: `waypoint_gaze_mode`  
Source: `genesis_tools/walkthrough_renderer/pipeline/camera_animate.py`

---

## 1. `smooth_adaptive`（推荐用于 terrain 场景）

**原理**  
离线预计算所有帧的朝向，再写入关键帧。分两步：

- **Yaw（水平朝向）**：采样路径切线方向（lookahead），对 yaw 序列做 unwrap + 双向 Gaussian 平滑，消除抖动。
- **Pitch（仰俯角）**：在当前 yaw 方向前方 `smooth_pitch_lookahead_m` 处查询 cloth heightmap，用 atan2 计算仰俯角，clamp 到 `[smooth_pitch_min_deg, smooth_pitch_max_deg]`，再做 Gaussian 平滑。

因为是"离线"（全局）平滑，可以实现 zero-phase（对称 FIR），不引入时间延迟。

**相关参数**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `smooth_pitch_lookahead_m` | `15.0` | Pitch 向前看距离（米） |
| `smooth_pitch_min_deg` | `-15.0` | 最大下看角度（负 = 向下） |
| `smooth_pitch_max_deg` | `8.0` | 最大上看角度 |
| `smooth_yaw_sigma_s` | `1.5` | Yaw 高斯平滑 σ（秒） |
| `smooth_pitch_sigma_s` | `0.8` | Pitch 高斯平滑 σ（秒） |
| `lookahead_fraction` | `0.05` | Yaw 切线采样的 arc-length 前瞻比例 |

**特点**  
✅ 最自然的视角，适合起伏地形  
✅ 上坡自然仰头，下坡轻微低头  
⚠️ 仅在非 aerial 模式下生效

---

## 2. `waypoint`

**原理**  
预先计算每个路点的朝向（取该路点之后所有未到达路点的平均方向），在路点之间用 **Slerp** 插值。相机始终朝向"未来路点的平均方向"。

**特点**  
✅ 视角变化平滑，Slerp 保证最短路径旋转  
❌ 路点在地面上，视线会向下倾斜（视角偏低）  
❌ 不感知地形高度，只看路点位置

---

## 3. `eye_level`

**原理**  
每帧在路径上向前采样 `lookahead_fraction` 比例的弧长，取该点的 XY 坐标，但 **Z 固定为当前摄像机高度**，构造 look_target：

```python
look_target = Vector((floor_ahead.x, floor_ahead.y, cam_pos.z))
```

相机始终保持水平视线，不随地形上下俯仰。

**特点**  
✅ 视线永远水平，稳定感强  
✅ 适合平坦场景或不希望视角抖动的场景  
❌ 上下坡时视角与地面脱节（不自然）

---

## 4. `free`（默认值）

**原理**  
每帧在路径上向前采样，取 look_target = cam_pos + (路径前方点 - 当前路点)，**包含地形 Z 差值**：

```python
look_target = cam_pos + (floor_ahead - path_pt)
```

相当于沿路径切线方向看，地形坡度会直接影响 pitch。

**特点**  
✅ 无额外配置，开箱即用  
✅ 自然跟随路径方向  
❌ 没有平滑，陡坡会导致大角度俯仰  
❌ 比 `smooth_adaptive` 抖动更多

---

## 对比总结

| 模式 | Pitch 来源 | Yaw 平滑 | Pitch 平滑 | 适合场景 |
|------|-----------|---------|-----------|---------|
| `smooth_adaptive` | heightmap atan2 + clamp | ✅ Gaussian | ✅ Gaussian | 户外地形、起伏地貌 |
| `waypoint` | 路点方向 Slerp | ✅ Slerp | ❌（隐含） | 室内/平坦、需要看向目标点 |
| `eye_level` | 固定水平（cam_pos.z） | ❌ 逐帧 | ✅（强制水平） | 平坦场景、稳定感优先 |
| `free` | 路径切线 Z 差值 | ❌ 逐帧 | ❌ 逐帧 | 快速原型、无特殊需求 |

---

## 配置示例（terrain 场景推荐）

```json
{
  "waypoint_gaze_mode":       "smooth_adaptive",
  "smooth_pitch_min_deg":     -8.0,
  "smooth_pitch_max_deg":      5.0,
  "smooth_pitch_lookahead_m": 20.0,
  "smooth_pitch_sigma_s":      1.2,
  "smooth_yaw_sigma_s":        0.6
}
```

---

*Source: `genesis_tools/walkthrough_renderer/pipeline/camera_animate.py`*
