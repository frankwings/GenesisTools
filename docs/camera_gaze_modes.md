# Camera Gaze Modes — WalkthroughRenderer

Config key: `waypoint_gaze_mode`  
Source: `genesis_tools/walkthrough_renderer/pipeline/camera_animate.py`

---

## 1. `smooth_adaptive` (recommended for terrain scenes)

**How it works**  
All frame orientations are precomputed offline before any keyframes are written. Two stages:

- **Yaw (horizontal heading)**: sample the path tangent direction (lookahead), then unwrap the yaw sequence and apply bidirectional Gaussian smoothing to remove jitter.
- **Pitch (vertical angle)**: query the cloth heightmap at `smooth_pitch_lookahead_m` ahead in the current yaw direction, compute the pitch via atan2, clamp to `[smooth_pitch_min_deg, smooth_pitch_max_deg]`, then apply Gaussian smoothing.

Because the smoothing is offline (global), a zero-phase symmetric FIR kernel can be used — no temporal lag is introduced.

**Parameters**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `smooth_pitch_lookahead_m` | `15.0` | Pitch lookahead distance (meters) |
| `smooth_pitch_min_deg` | `-15.0` | Maximum downward angle (negative = down) |
| `smooth_pitch_max_deg` | `8.0` | Maximum upward angle |
| `smooth_yaw_sigma_s` | `1.5` | Yaw Gaussian smoothing σ (seconds) |
| `smooth_pitch_sigma_s` | `0.8` | Pitch Gaussian smoothing σ (seconds) |
| `lookahead_fraction` | `0.05` | Arc-length lookahead fraction for yaw tangent sampling |

**Characteristics**  
✅ Most natural viewing angle; ideal for undulating terrain  
✅ Naturally looks up on ascents, slightly down on descents  
⚠️ Only active in non-aerial mode

### What "Gaussian smoothing" means here

The smoothing is **temporal — across frames**. Each frame's yaw/pitch is replaced
by a Gaussian-weighted average of the surrounding frames, both **past and
future**:

```python
# camera_animate.py — _gauss_smooth()
radius = ceil(4.0 * sigma)              # window: ±4σ frames
x = arange(-radius, radius + 1)
k = exp(-0.5 * (x / sigma)**2)          # Gaussian kernel
k /= k.sum()                            # normalize weights to 1
smoothed = convolve(padded_signal, k)   # symmetric convolution
```

**Concrete example.** With `smooth_yaw_sigma_s = 0.6` at 12 fps:

- σ = 0.6 s × 12 fps = **7.2 frames**
- window radius = 4σ ≈ **29 frames** on each side
- → each frame's yaw becomes a weighted average of **~58 surrounding frames**,
  with weights falling off as a bell curve (the current frame counts most,
  frames 29 away contribute almost nothing).

The σ parameters are specified in **seconds** (not frames) so the smoothing
strength is independent of the render fps.

**Why both past AND future frames (zero-phase)?**
A real-time filter could only average over *past* frames, which shifts the
signal later in time — the camera would start turning *after* the path bends
(visible lag). Because `smooth_adaptive` precomputes the entire trajectory
offline, it can use a symmetric window centered on each frame. A symmetric FIR
kernel has **zero phase delay**: the smoothed camera turns exactly *at* the
bend, just more gradually. This is the main reason the mode must run offline.

**Why unwrap yaw before smoothing?**
Yaw is a circular quantity that wraps at ±180°. Naively averaging 179° and
−179° gives 0° — the camera would whip around the wrong way. `np.unwrap()`
first converts the sequence to a continuous signal (… 179°, 181°, 183° …) so
the convolution averages along the short arc; the result is re-wrapped
afterwards.

**Edge handling.** The first/last `radius` frames don't have enough neighbours
on one side, so the signal is padded by repeating the boundary value
(nearest-edge padding). This keeps the camera stable at the start and end of
the walkthrough instead of drifting toward 0.

**Order of operations for pitch.** Pitch is clamped to
`[smooth_pitch_min_deg, smooth_pitch_max_deg]` *before* Gaussian smoothing, so
a brief extreme spike (e.g. the lookahead point falling off a cliff edge) is
first capped, then blended away — the spike never leaks into neighbouring
frames at full amplitude.

---

## 2. `waypoint`

**How it works**  
Each waypoint's gaze direction is precomputed as the average direction toward all future (not-yet-visited) waypoints. Between waypoints the camera orientation is interpolated via **Slerp**. The camera always faces the "average direction of upcoming waypoints."

**Characteristics**  
✅ Smooth orientation changes; Slerp guarantees shortest-arc rotation  
❌ Waypoints sit on the ground, so the gaze tilts downward (low viewing angle)  
❌ Terrain-height unaware — only waypoint positions matter

---

## 3. `eye_level`

**How it works**  
Each frame samples the path `lookahead_fraction` of arc-length ahead, takes that point's XY coordinates, but **fixes Z to the current camera height** to build the look target:

```python
look_target = Vector((floor_ahead.x, floor_ahead.y, cam_pos.z))
```

The camera gaze stays perfectly horizontal and never pitches with the terrain.

**Characteristics**  
✅ Gaze is always level — very stable feel  
✅ Good for flat scenes or when pitch jitter must be avoided  
❌ On slopes the gaze disconnects from the ground (looks unnatural)

---

## 4. `free` (default)

**How it works**  
Each frame samples the path ahead and sets look_target = cam_pos + (point ahead − current path point), **including the terrain Z delta**:

```python
look_target = cam_pos + (floor_ahead - path_pt)
```

Effectively looks along the path tangent; terrain slope directly drives the pitch.

**Characteristics**  
✅ No extra configuration — works out of the box  
✅ Naturally follows the path direction  
❌ No smoothing — steep slopes cause large pitch swings  
❌ More jitter than `smooth_adaptive`

---

## Comparison

| Mode | Pitch source | Yaw smoothing | Pitch smoothing | Best for |
|------|-------------|---------------|-----------------|----------|
| `smooth_adaptive` | heightmap atan2 + clamp | ✅ Gaussian | ✅ Gaussian | Outdoor terrain, rolling landscapes |
| `waypoint` | waypoint-direction Slerp | ✅ Slerp | ❌ (implicit) | Indoor / flat scenes, target-focused gaze |
| `eye_level` | fixed horizontal (cam_pos.z) | ❌ per-frame | ✅ (forced level) | Flat scenes, stability first |
| `free` | path-tangent Z delta | ❌ per-frame | ❌ per-frame | Quick prototypes, no special requirements |

---

## Example config (recommended for terrain scenes)

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
