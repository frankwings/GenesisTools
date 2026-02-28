"""Blender subprocess runner for Genesis modules.

Provides BlenderRunner, a class that executes Blender Python scripts in a
background Blender process, manages .blend file snapshots for undo support,
and collects rendered outputs.

All dependencies are stdlib-only (no openai, PIL, or other third-party imports).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Union


# ---------------------------------------------------------------------------
# Internal runner script embedded as a module-level constant.
# This script is written to a temp file at runtime and passed to Blender's
# --python argument.  It receives two positional args after "--":
#   1. script_path  -- the user script to exec()
#   2. render_dir   -- directory to scan for PNG/JPG renders, or "NONE"
# ---------------------------------------------------------------------------
_RUNNER_SCRIPT = '''
import bpy
import json
import sys
import os

script_path = sys.argv[sys.argv.index("--") + 1]
render_dir = sys.argv[sys.argv.index("--") + 2]

try:
    with open(script_path, "r") as f:
        code = f.read()
    exec(compile(code, script_path, "exec"), {"__file__": script_path})

    if render_dir != "NONE" and os.path.isdir(render_dir):
        renders = sorted([
            f for f in os.listdir(render_dir)
            if f.endswith(".png") or f.endswith(".jpg")
        ])
        print("GENESIS_RESULT:" + json.dumps({"status": "success", "renders": renders}))
    else:
        print("GENESIS_RESULT:" + json.dumps({"status": "success", "renders": []}))
except Exception as e:
    import traceback
    print("GENESIS_RESULT:" + json.dumps({"status": "error", "message": str(e), "traceback": traceback.format_exc()}))
'''

# Internal script used by get_scene_info() to dump scene state as JSON.
_SCENE_INFO_SCRIPT = '''
import bpy
import json
import sys
import os

output_path = sys.argv[sys.argv.index("--") + 1]

scene = bpy.context.scene

objects = []
for obj in scene.objects:
    objects.append({
        "name": obj.name,
        "type": obj.type,
        "location": list(obj.location),
    })

materials = [mat.name for mat in bpy.data.materials]

cameras = [obj.name for obj in scene.objects if obj.type == "CAMERA"]
camera_info = {"count": len(cameras), "names": cameras}

lights = [obj.name for obj in scene.objects if obj.type == "LIGHT"]

info = {
    "objects": objects,
    "materials": materials,
    "camera": camera_info,
    "light_count": len(lights),
}

with open(output_path, "w") as f:
    json.dump(info, f)
'''


class BlenderRunner:
    """Execute Blender Python scripts against a .blend file.

    Manages a working directory with:
    - ``scripts/``   -- numbered user scripts written before each run
    - ``renders/``   -- subdirectories of PNG/JPG renders per run
    - ``snapshots/`` -- .blend snapshots (0 = initial, N = after run N)

    Parameters
    ----------
    blend_file:
        Path to the .blend file to operate on.
    work_dir:
        Directory for temp scripts, renders, and snapshots.
    blender_command:
        Path to the Blender executable.  If *None*, auto-detected via
        :meth:`find_blender`.
    gpu_devices:
        Value to set as ``CUDA_VISIBLE_DEVICES`` in the subprocess
        environment (e.g. ``"0,1"``).  *None* means the variable is not
        overridden.
    """

    def __init__(
        self,
        blend_file: Union[str, Path],
        work_dir: Union[str, Path],
        blender_command: Optional[str] = None,
        gpu_devices: Optional[str] = None,
    ) -> None:
        self._blend_file = Path(blend_file).resolve()
        if not self._blend_file.exists():
            raise FileNotFoundError(f"blend_file not found: {self._blend_file}")
        self._work_dir = Path(work_dir)
        self._blender = blender_command or self.find_blender()
        self._gpu_devices = gpu_devices
        self._count: int = 0

        # Create required subdirectories.
        (self._work_dir / "scripts").mkdir(parents=True, exist_ok=True)
        (self._work_dir / "renders").mkdir(parents=True, exist_ok=True)
        snapshots_dir = self._work_dir / "snapshots"
        snapshots_dir.mkdir(parents=True, exist_ok=True)

        # Snapshot the initial .blend as snapshot 0.
        shutil.copy2(self._blend_file, snapshots_dir / "0.blend")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, script: str) -> Dict:
        """Execute *script* inside Blender and return a result dict.

        Parameters
        ----------
        script:
            Python source code to run inside Blender.

        Returns
        -------
        dict
            ``{"status": "success"|"error", "stdout": str, "stderr": str}``
            On error, an additional ``"message"`` key may be present.
        """
        return self._execute(script, render_dir=None)

    def run_and_render(self, script: str) -> Dict:
        """Execute *script* and collect rendered PNG/JPG files.

        A render directory ``{work_dir}/renders/{count}/`` is created and
        passed to the internal runner.  Any files written there by the
        script are returned in the result.

        Returns
        -------
        dict
            ``{"status": ..., "renders": [list of absolute paths], "stdout": str, "stderr": str}``
        """
        render_dir = self._work_dir / "renders" / str(self._count)
        render_dir.mkdir(parents=True, exist_ok=True)
        result = self._execute(script, render_dir=render_dir)

        # Resolve render filenames to absolute paths.
        if result.get("status") == "success":
            render_names: List[str] = result.get("renders", [])
            result["renders"] = [
                str(render_dir / name) for name in render_names
            ]
        return result

    def undo(self) -> Dict:
        """Restore the .blend file to the previous snapshot.

        Decrements the internal counter and copies the matching snapshot
        back to ``self._blend_file``.

        Returns
        -------
        dict
            ``{"status": "success"}`` or ``{"status": "error", "message": str}``
        """
        if self._count == 0:
            return {"status": "error", "message": "Nothing to undo: already at initial state."}

        self._count -= 1
        snapshot = self._work_dir / "snapshots" / f"{self._count}.blend"
        if not snapshot.exists():
            return {
                "status": "error",
                "message": f"Snapshot not found: {snapshot}",
            }

        try:
            shutil.copy2(snapshot, self._blend_file)
        except OSError as exc:
            return {"status": "error", "message": str(exc)}

        return {"status": "success"}

    def get_scene_info(self) -> Dict:
        """Dump scene metadata (objects, materials, cameras, lights) as JSON.

        Executes a built-in Blender script that writes scene info to a
        temporary file, then reads and returns that file.

        Returns
        -------
        dict
            ``{"status": "success", "scene": {...}}`` or
            ``{"status": "error", "message": str}``
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            output_path = tmp_path / "scene_info.json"

            # Write the scene-info runner to a temp file.
            runner_path = tmp_path / "_scene_info_runner.py"
            with open(runner_path, "w", encoding="utf-8") as fh:
                fh.write(_SCENE_INFO_SCRIPT)

            stdout_path = tmp_path / "stdout.txt"
            stderr_path = tmp_path / "stderr.txt"

            cmd = self._build_cmd(str(runner_path), extra_args=[str(output_path)])
            env = self._build_env()

            try:
                with open(stdout_path, "w") as out, open(stderr_path, "w") as err:
                    subprocess.run(
                        cmd,
                        stdout=out,
                        stderr=err,
                        env=env,
                        shell=(sys.platform == "win32"),
                        timeout=300,
                    )
            except (OSError, subprocess.SubprocessError) as exc:
                return {"status": "error", "message": str(exc)}

            if not output_path.exists():
                stderr_text = ""
                if stderr_path.exists():
                    with open(stderr_path, "r", encoding="utf-8", errors="replace") as fh:
                        stderr_text = fh.read()
                return {
                    "status": "error",
                    "message": "Scene info file was not produced by Blender.",
                    "stderr": stderr_text,
                }

            try:
                with open(output_path, "r", encoding="utf-8") as fh:
                    scene_data = json.load(fh)
            except (OSError, json.JSONDecodeError) as exc:
                return {"status": "error", "message": str(exc)}

            # Copy scene_data out before TemporaryDirectory is cleaned up.
            result_scene = dict(scene_data)

        return {"status": "success", "scene": result_scene}

    @staticmethod
    def find_blender() -> str:
        """Locate the Blender executable.

        Search order:

        1. ``GENESIS_BLENDER_PATH`` environment variable.
        2. Platform-specific common install paths.
        3. ``shutil.which("blender")``.
        4. Fallback: ``"blender"`` (relies on ``PATH``).

        Returns
        -------
        str
            Path to the Blender executable (or ``"blender"`` as a fallback).
        """
        env_path = os.environ.get("GENESIS_BLENDER_PATH")
        if env_path:
            return env_path

        if sys.platform.startswith("linux"):
            candidates = [
                "/usr/local/bin/blender",
                "/usr/bin/blender",
                os.path.expanduser("~/blender/blender"),
            ]
        elif sys.platform == "darwin":
            candidates = [
                "/Applications/Blender.app/Contents/MacOS/Blender",
            ]
        elif sys.platform == "win32":
            candidates = [
                r"C:\Program Files\Blender Foundation\Blender 4.5\blender.exe",
                r"C:\Program Files\Blender Foundation\Blender 4.3\blender.exe",
            ]
        else:
            candidates = []

        for path in candidates:
            if os.path.isfile(path):
                return path

        which_result = shutil.which("blender")
        if which_result:
            return which_result

        return "blender"

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _execute(self, script: str, render_dir: Optional[Path]) -> Dict:
        """Core execution helper shared by run() and run_and_render()."""
        count = self._count
        script_path = self._work_dir / "scripts" / f"{count}.py"
        try:
            script_path.write_text(script, encoding="utf-8")
        except OSError as e:
            return {"status": "error", "stdout": "", "stderr": str(e)}

        render_arg = str(render_dir) if render_dir is not None else "NONE"

        with tempfile.TemporaryDirectory() as tmp:
            runner_path = os.path.join(tmp, "_runner.py")
            with open(runner_path, "w", encoding="utf-8") as fh:
                fh.write(_RUNNER_SCRIPT)

            stdout_path = os.path.join(tmp, "stdout.txt")
            stderr_path = os.path.join(tmp, "stderr.txt")

            cmd = self._build_cmd(runner_path, extra_args=[str(script_path), render_arg])
            env = self._build_env()

            try:
                with open(stdout_path, "w") as out, open(stderr_path, "w") as err:
                    subprocess.run(
                        cmd,
                        stdout=out,
                        stderr=err,
                        env=env,
                        shell=(sys.platform == "win32"),
                        timeout=300,
                    )
            except (OSError, subprocess.SubprocessError) as exc:
                return {
                    "status": "error",
                    "message": str(exc),
                    "stdout": "",
                    "stderr": "",
                    "renders": [],
                }

            stdout_text = ""
            stderr_text = ""
            if os.path.exists(stdout_path):
                with open(stdout_path, "r", encoding="utf-8", errors="replace") as fh:
                    stdout_text = fh.read()
            if os.path.exists(stderr_path):
                with open(stderr_path, "r", encoding="utf-8", errors="replace") as fh:
                    stderr_text = fh.read()

        # Parse GENESIS_RESULT: from stdout.
        result_data = self._parse_result(stdout_text)

        if result_data.get("status") == "success":
            # Take a snapshot of the updated .blend file.
            self._count += 1
            snapshot = self._work_dir / "snapshots" / f"{self._count}.blend"
            try:
                shutil.copy2(self._blend_file, snapshot)
            except OSError:
                pass  # Non-fatal; undo may not work for this step.

        result_data["stdout"] = stdout_text
        result_data["stderr"] = stderr_text
        return result_data

    def _parse_result(self, stdout: str) -> Dict:
        """Extract the JSON result dict from Blender stdout."""
        prefix = "GENESIS_RESULT:"
        for line in stdout.splitlines():
            if line.startswith(prefix):
                json_str = line[len(prefix):]
                try:
                    return json.loads(json_str)
                except json.JSONDecodeError:
                    return {
                        "status": "error",
                        "message": f"Could not parse GENESIS_RESULT JSON: {json_str!r}",
                        "renders": [],
                    }
        # No result line found -- Blender likely crashed or was not found.
        return {
            "status": "error",
            "message": "No GENESIS_RESULT line found in Blender output.",
            "renders": [],
        }

    def _build_cmd(self, runner_path: str, extra_args: List[str]) -> Union[List[str], str]:
        """Build the Blender subprocess command.

        On Windows, returns a shell-quoted string (for ``shell=True``).
        On Linux/Mac, returns a list (for ``shell=False``).
        """
        parts = [
            self._blender,
            "--background",
            str(self._blend_file),
            "--python",
            runner_path,
            "--",
        ] + extra_args

        if sys.platform == "win32":
            # Quote each part to handle spaces in paths.
            quoted = " ".join(f'"{p}"' if " " in p else p for p in parts)
            return quoted

        return parts

    def _build_env(self) -> Dict[str, str]:
        """Build the subprocess environment dict."""
        env = os.environ.copy()
        env["AL_LIB_LOGLEVEL"] = "0"
        if self._gpu_devices is not None:
            env["CUDA_VISIBLE_DEVICES"] = self._gpu_devices
        return env
