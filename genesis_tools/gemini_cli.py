"""GeminiCLI — subprocess wrapper for the local `gemini` CLI binary.

Provides text and JSON calls with image attachment, retry logic,
and agent-mode guards. No API key required — auth is handled
by the gemini CLI itself (gemini auth login).

Usage:
    from genesis_tools import GeminiCLI

    cli = GeminiCLI(model="gemini-2.0-flash")
    name = cli.call("What is this?", images=["mask.png", "orig.png"])
    data = cli.call_json("Return scene params", system_prompt=system)
"""

import json
import os
import shutil
import subprocess
import tempfile
import time
from typing import Optional


class GeminiCLI:
    """Wrapper around the local `gemini` CLI binary.

    Args:
        model: Model name passed via -m flag (e.g. 'gemini-2.0-flash').
               If None, the CLI uses its configured default.
        timeout: Seconds to wait per CLI call. Default 180.
        max_retries: Retry attempts on error or agent-mode response. Default 3.
        inter_call_delay: Seconds to sleep after each successful call. Default 0.
    """

    _RETRY_BASE_WAIT_SECONDS: int = 10  # base wait for linear-backoff retry: wait = base * (attempt+1)

    def __init__(
        self,
        model: Optional[str] = None,
        timeout: int = 180,
        max_retries: int = 3,
        inter_call_delay: float = 0.0,
    ) -> None:
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self.inter_call_delay = inter_call_delay

    def call(
        self,
        prompt: str,
        images: Optional[list] = None,
        system_prompt: Optional[str] = None,
        max_response_chars: int = 2000,
    ) -> str:
        """Call the gemini CLI and return stripped text output.

        Args:
            prompt: User prompt text.
            images: Optional list of file paths to attach via @filepath stdin syntax.
            system_prompt: If given, prepended to prompt with a '---' separator.
            max_response_chars: Responses longer than this are treated as
                agent-mode responses and trigger a retry.

        Returns:
            Stripped text response from the CLI.

        Raises:
            RuntimeError: If all retries are exhausted.
        """
        combined_prompt = prompt
        if system_prompt:
            combined_prompt = f"{system_prompt}\n\n---\nUser: {prompt}"

        if self.model:
            model_flags = ["-m", self.model]
        else:
            model_flags = []

        tmpdir = None
        if images:
            # gemini-cli applies .gitignore rules and blocks git-ignored files.
            # Copy images to a fresh temp dir outside any repo, then add it
            # via --include-directories so gemini-cli can read them.
            tmpdir = tempfile.mkdtemp(prefix="gemini_vlm_")
            tmp_images = []
            for img in images:
                dst = os.path.join(tmpdir, os.path.basename(img))
                shutil.copy2(img, dst)
                tmp_images.append(dst)
            image_refs = " ".join(f"@{p}" for p in tmp_images)
            stdin_content = f"{image_refs}\n\n{combined_prompt}"
            cmd = ["gemini", "-o", "text", "--include-directories", tmpdir] + model_flags
        else:
            stdin_content = ""
            cmd = ["gemini", "-p", combined_prompt, "-o", "text"] + model_flags

        last_error: Optional[Exception] = None
        try:
            for attempt in range(self.max_retries + 1):
                try:
                    result = subprocess.run(
                        cmd,
                        input=stdin_content,
                        capture_output=True,
                        text=True,
                        timeout=self.timeout,
                    )
                    if result.returncode != 0:
                        raise RuntimeError(result.stderr.strip() or f"exit code {result.returncode}")

                    output = result.stdout.strip()

                    if len(output) > max_response_chars:
                        raise RuntimeError(
                            f"Response too long ({len(output)} chars); "
                            "likely entered agent mode"
                        )

                    if self.inter_call_delay > 0:
                        time.sleep(self.inter_call_delay)

                    return output

                except Exception as e:
                    last_error = e
                    if attempt < self.max_retries:
                        wait = self._RETRY_BASE_WAIT_SECONDS * (attempt + 1)
                        print(
                            f"[GeminiCLI] Error, retrying in {wait}s "
                            f"(attempt {attempt + 1}/{self.max_retries}): {e}"
                        )
                        time.sleep(wait)

            raise RuntimeError(
                f"GeminiCLI failed after {self.max_retries + 1} attempts: {last_error}"
            )
        finally:
            if tmpdir:
                shutil.rmtree(tmpdir, ignore_errors=True)

    def call_json(
        self,
        prompt: str,
        images: Optional[list] = None,
        system_prompt: Optional[str] = None,
    ) -> dict:
        """Call the CLI and parse the response as JSON.

        Appends a JSON instruction to the prompt, strips markdown fences
        from the response, and retries if the response cannot be parsed.

        Args:
            prompt: User prompt text.
            images: Optional list of file paths to attach.
            system_prompt: If given, prepended to prompt.

        Returns:
            Parsed JSON as a dict.

        Raises:
            RuntimeError: If all retries (on JSONDecodeError) are exhausted.
                Note: RuntimeError raised by self.call() (transport/timeout/
                agent-mode) propagates immediately — only JSONDecodeError
                triggers this method's retry loop.
        """
        json_prompt = prompt + "\n\nReturn ONLY valid JSON. No markdown, no explanation."

        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                raw = self.call(
                    json_prompt,
                    images=images,
                    system_prompt=system_prompt,
                    max_response_chars=10000,
                )
                # Strip markdown fences if present (e.g. ```json ... ```)
                clean = raw.strip()
                if clean.startswith("```"):
                    lines = clean.split("\n")
                    lines = lines[1:]  # remove opening fence line
                    if lines and lines[-1].startswith("```"):
                        lines = lines[:-1]
                    clean = "\n".join(lines).strip()

                return json.loads(clean)

            except json.JSONDecodeError as e:
                last_error = e
                if attempt < self.max_retries:
                    wait = self._RETRY_BASE_WAIT_SECONDS * (attempt + 1)
                    print(
                        f"[GeminiCLI] JSON parse failed, retrying in {wait}s "
                        f"(attempt {attempt + 1}/{self.max_retries}): {e}"
                    )
                    time.sleep(wait)

        raise RuntimeError(
            f"GeminiCLI.call_json failed after {self.max_retries + 1} attempts: {last_error}"
        )
