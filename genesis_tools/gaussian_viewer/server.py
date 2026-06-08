"""
GenesisPortal — Gaussian Splat Web Viewer (powered by PlayCanvas SuperSplat)
Usage:
    python -m genesis_tools.gaussian_viewer.server --port 8765
    python -m genesis_tools.gaussian_viewer.server --ply /path/to/gsplat.ply
"""
import argparse
import webbrowser
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# SuperSplat viewer public dir (installed via npm)
_THIS_DIR = Path(__file__).parent
_TOOLS_ROOT = _THIS_DIR.parents[1]  # GenesisTools/
_SUPERSPLAT_PUBLIC = _THIS_DIR / "static" / "supersplat"

app = FastAPI(title="Genesis Splat Viewer")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

# Serve supersplat static assets at /viewer/
app.mount("/viewer", StaticFiles(directory=str(_SUPERSPLAT_PUBLIC), html=True), name="supersplat")

# Runtime-registered splat files: stem -> absolute path
_registry: dict[str, Path] = {}
_current_port = 8765


def _compute_scene_settings(ply_path: Path) -> dict:
    """Read PLY and compute camera position centered on scene."""
    import numpy as np
    try:
        with open(ply_path, 'rb') as f:
            props, n_verts = [], 0
            while True:
                line = f.readline().decode('utf-8').strip()
                if line.startswith('element vertex'):
                    n_verts = int(line.split()[-1])
                elif line.startswith('property float'):
                    props.append(line.split()[-1])
                elif line == 'end_header':
                    break
            data = np.frombuffer(f.read(n_verts * len(props) * 4),
                                 dtype=np.float32).reshape(n_verts, len(props))
        xi, yi, zi = props.index('x'), props.index('y'), props.index('z')
        xyz = data[:, [xi, yi, zi]]
        center = np.median(xyz, axis=0).tolist()
        lo = np.percentile(xyz, 5, axis=0)
        hi = np.percentile(xyz, 95, axis=0)
        size = float(np.linalg.norm(hi - lo))
        # Camera sits back along Z, slightly above center
        cam_pos = [center[0], center[1] + size * 0.15, center[2] + size * 0.7]
    except Exception:
        center, cam_pos = [0, 0, 0], [0, 1, 3]

    return {
        "version": 2,
        "tonemapping": "none",
        "highPrecisionRendering": False,
        "background": {"color": [0.1, 0.1, 0.1]},
        "postEffectSettings": {
            "sharpness": {"enabled": False, "amount": 0},
            "bloom":     {"enabled": False, "intensity": 1, "blurLevel": 2},
            "grading":   {"enabled": False, "brightness": 0, "contrast": 1,
                          "saturation": 1, "tint": [1, 1, 1]},
            "vignette":  {"enabled": False, "intensity": 0.5, "inner": 0.3,
                          "outer": 0.75, "curvature": 1},
            "fringing":  {"enabled": False, "intensity": 0.5}
        },
        "animTracks": [],
        "cameras": [],   # Let viewer auto-frame (same as clicking Fit)
        "annotations": [],
        "startMode": "default"
    }


@app.get("/api/settings")
def default_settings(ply: str | None = None):
    from fastapi.responses import JSONResponse
    if ply and ply in _registry:
        settings = _compute_scene_settings(_registry[ply])
    elif _registry:
        # Use first registered file
        settings = _compute_scene_settings(next(iter(_registry.values())))
    else:
        settings = {"version": 2, "tonemapping": "none", "highPrecisionRendering": False,
                    "background": {"color": [0.1, 0.1, 0.1]},
                    "postEffectSettings": {
                        "sharpness": {"enabled": False, "amount": 0},
                        "bloom": {"enabled": False, "intensity": 1, "blurLevel": 2},
                        "grading": {"enabled": False, "brightness": 0, "contrast": 1,
                                    "saturation": 1, "tint": [1, 1, 1]},
                        "vignette": {"enabled": False, "intensity": 0.5, "inner": 0.3,
                                     "outer": 0.75, "curvature": 1},
                        "fringing": {"enabled": False, "intensity": 0.5}},
                    "animTracks": [], "cameras": [{"initial": {"position": [0, 1, 3],
                    "target": [0, 0, 0], "fov": 60}}], "annotations": [],
                    "startMode": "default"}
    return JSONResponse(settings)


@app.get("/")
def root(ply: str | None = None):
    """Redirect to supersplat viewer with ?content= pointing at the splat file."""
    if ply and ply in _registry:
        ext = _registry[ply].suffix
        content_url = f"/splat/{ply}{ext}"
        url = f"/viewer/?content={content_url}&settings=/api/settings?ply={ply}"
        return HTMLResponse(
            f'<html><head><meta http-equiv="refresh" content="0;url={url}"></head>'
            f'<body><a href="{url}">Loading viewer...</a></body></html>'
        )
    # List available files
    files_html = "".join(
        f'<li><a href="/?ply={k}">{k}{v.suffix}</a> ({v.stat().st_size//1024//1024} MB)</li>'
        for k, v in _registry.items()
    )
    return HTMLResponse(
        f"<html><body><h2>Genesis Splat Viewer</h2>"
        f"<p>Available files:</p><ul>{files_html}</ul>"
        f"<p>No file loaded. Use <code>?ply=&lt;name&gt;</code></p></body></html>"
    )


@app.get("/splat/{name:path}")
def serve_splat(name: str):
    """Serve a registered splat/ply file."""
    stem = Path(name).stem
    key = name if name in _registry else (stem if stem in _registry else None)
    if not key:
        raise HTTPException(status_code=404, detail=f"File '{name}' not registered.")
    path = _registry[key]
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {path}")
    return FileResponse(str(path), media_type="application/octet-stream", filename=path.name)


@app.get("/api/files")
def list_files():
    return {"files": {k: str(v) for k, v in _registry.items()}}


def register(path: str | Path, name: str | None = None) -> str:
    p = Path(path).resolve()
    key = name or p.stem
    _registry[key] = p
    return f"http://localhost:{_current_port}/?ply={key}"


def start(port: int = 8765, ply_path: str | None = None,
          open_browser: bool = True, host: str = "0.0.0.0"):
    global _current_port
    _current_port = port

    if not _SUPERSPLAT_PUBLIC.exists():
        print(f"[ERROR] SuperSplat viewer not found at {_SUPERSPLAT_PUBLIC}")
        print("Run: cd GenesisTools && npm install @playcanvas/supersplat-viewer")
        return

    url = f"http://localhost:{port}/"
    if ply_path:
        register(ply_path)
        name = Path(ply_path).stem
        url = f"http://localhost:{port}/?ply={name}"

    print(f"[GenesisPortal] SuperSplat Viewer → {url}")
    if open_browser:
        webbrowser.open(url)

    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", type=str, default="0.0.0.0")
    parser.add_argument("--ply", type=str, default=None)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    start(port=args.port, ply_path=args.ply, open_browser=not args.no_browser, host=args.host)
