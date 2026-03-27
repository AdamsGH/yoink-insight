"""GeminiRunner - async subprocess wrapper for the Gemini CLI.

gemini CLI requires a pseudo-TTY to run in non-interactive mode.
We use `script -q -e -c "..."` which allocates a PTY internally,
allowing the CLI to detect a terminal and produce output.
The raw output is then stripped of ANSI escape sequences.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import shlex

from yoink_insight.config import InsightConfig

logger = logging.getLogger(__name__)

# Matches ANSI escape sequences and common terminal control codes
_ANSI_RE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
# Matches carriage returns and other control chars except newline/tab
_CTRL_RE = re.compile(r"[\r\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _strip_terminal(text: str) -> str:
    """Remove ANSI escape sequences and stray control characters."""
    text = _ANSI_RE.sub("", text)
    text = _CTRL_RE.sub("", text)
    # Remove gemini's "Loaded cached credentials." banner lines
    lines = [l for l in text.splitlines() if not l.startswith("Loaded cached")]
    return "\n".join(lines).strip()


class GeminiError(Exception):
    """Raised when the Gemini CLI exits non-zero or times out."""


class GeminiRunner:
    """Runs the Gemini CLI via script(1) to provide a pseudo-TTY."""

    def __init__(self, config: InsightConfig) -> None:
        self._config = config

    async def run(self, prompt: str) -> str:
        """Execute gemini CLI with the given prompt and return clean text output.

        Uses `script -q -e -c <cmd> /dev/null` to allocate a PTY so the CLI
        detects a terminal and produces output in non-interactive mode.

        Raises:
            GeminiError: if the process exits non-zero or times out.
        """
        env = os.environ.copy()
        if self._config.gemini_home:
            env["HOME"] = self._config.gemini_home

        # Build the inner gemini command, safely quoted
        inner = (
            f"{shlex.quote(self._config.gemini_cli_path)}"
            f" --output-format text"
            f" -p {shlex.quote(prompt)}"
        )
        # script -q  : quiet (no start/done headers)
        # script -e  : exit with child exit code
        # script -c  : run command string via shell
        # /dev/null  : discard typescript file
        cmd = ["script", "-q", "-e", "-c", inner, "/dev/null"]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
            )
        except FileNotFoundError as exc:
            raise GeminiError("'script' utility not found in PATH") from exc

        try:
            stdout, _ = await asyncio.wait_for(
                proc.communicate(),
                timeout=self._config.insight_timeout,
            )
        except asyncio.TimeoutError as exc:
            proc.kill()
            await proc.wait()
            raise GeminiError(
                f"Gemini CLI timed out after {self._config.insight_timeout}s"
            ) from exc

        raw = stdout.decode(errors="replace")
        text = _strip_terminal(raw)

        if proc.returncode != 0:
            logger.warning("Gemini CLI exited %d: %s", proc.returncode, text[:200])
            raise GeminiError(text or f"exit code {proc.returncode}")

        if not text:
            raise GeminiError("Gemini CLI returned empty output")

        return text
