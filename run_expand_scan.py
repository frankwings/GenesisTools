"""Run ExpandTerrainScan on alpine_meadow_sunrise walkthrough scene."""
import importlib.util
from pathlib import Path

def _load(path):
    spec = importlib.util.spec_from_file_location("expand_terrain_scan", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

run_scan = _load("/home/kingy/Projects/Genesis/GenesisTools/genesis_tools/active_contour/expand_terrain_scan.py").run_scan

BASE = Path("/home/kingy/Projects/Genesis/GenesisTools/results/alpine_meadow_sunrise/walkthrough_veg_sa")

run_scan(
    output_path=str(BASE / "terrain_scan.npz"),
    res=10.0,
    cam_height=1.7,
    min_overlap_bu=1.0,
    max_cells=20_000,
    verbose=True,
)
