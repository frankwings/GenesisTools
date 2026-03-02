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
import subprocess
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

        cmd = ["gemini", "-p", combined_prompt, "-o", "text"]
        if self.model:
            cmd += ["-m", self.model]

        stdin_content = ""
        if images:
            stdin_content = " ".join(f"@{p}" for p in images)

        last_error: Optional[Exception] = None
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
                    wait = 10 * (attempt + 1)
                    print(
                        f"[GeminiCLI] Error, retrying in {wait}s "
                        f"(attempt {attempt + 1}/{self.max_retries}): {e}"
                    )
                    time.sleep(wait)

        raise RuntimeError(
            f"GeminiCLI failed after {self.max_retries + 1} attempts: {last_error}"
        )

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
            RuntimeError: If all retries are exhausted without valid JSON.
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
                # Strip markdown fences if present
                clean = raw.strip()
                if clean.startswith("```"):
                    lines = clean.split("\n")
                    if lines[0].startswith("```"):
                        lines = lines[1:]
                    if lines and lines[-1].startswith("```"):
                        lines = lines[:-1]
                    clean = "\n".join(lines).strip()

                return json.loads(clean)

            except json.JSONDecodeError as e:
                last_error = e
                if attempt < self.max_retries:
                    wait = 10 * (attempt + 1)
                    print(
                        f"[GeminiCLI] JSON parse failed, retrying in {wait}s "
                        f"(attempt {attempt + 1}/{self.max_retries}): {e}"
                    )
                    time.sleep(wait)

        raise RuntimeError(
            f"GeminiCLI.call_json failed after {self.max_retries + 1} attempts: {last_error}"
        )
