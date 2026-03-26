"""GeminiRunner - async subprocess wrapper for the Gemini CLI."""
from __future__ import annotations

import asyncio
import logging
import os

from yoink_insight.config import InsightConfig

logger = logging.getLogger(__name__)


class GeminiError(Exception):
    """Raised when the Gemini CLI exits non-zero or times out."""


class GeminiRunner:
    """Runs the Gemini CLI as an async subprocess and returns its stdout."""

    def __init__(self, config: InsightConfig) -> None:
        self._config = config

    async def run(self, prompt: str) -> str:
        """Execute the gemini CLI with the given prompt and return the text output.

        Raises:
            GeminiError: if the process exits with a non-zero code or times out.
        """
        env = os.environ.copy()
        if self._config.gemini_home:
            env["HOME"] = self._config.gemini_home

        cmd = [
            self._config.gemini_cli_path,
            "--output-format",
            "text",
            "-p",
            prompt,
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
        except FileNotFoundError as exc:
            raise GeminiError(
                f"Gemini CLI not found at '{self._config.gemini_cli_path}'"
            ) from exc

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=self._config.insight_timeout,
            )
        except asyncio.TimeoutError as exc:
            proc.kill()
            await proc.wait()
            raise GeminiError(
                f"Gemini CLI timed out after {self._config.insight_timeout}s"
            ) from exc

        if proc.returncode != 0:
            err_text = stderr.decode(errors="replace").strip()
            logger.warning("Gemini CLI exited %d: %s", proc.returncode, err_text)
            raise GeminiError(err_text or f"exit code {proc.returncode}")

        return stdout.decode(errors="replace").strip()
