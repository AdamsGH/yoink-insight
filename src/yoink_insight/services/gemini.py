"""GeminiSummarizer - summarize YouTube videos via transcript + Gemini API."""
from __future__ import annotations

import asyncio
import logging
import re
from urllib.parse import parse_qs, urlparse

from google import genai
from youtube_transcript_api import (
    NoTranscriptFound,
    TranscriptsDisabled,
    YouTubeTranscriptApi,
)

from yoink_insight.config import InsightConfig

logger = logging.getLogger(__name__)

# Default built-in instruction blocks. The full prompt sent to Gemini is
# assembled in _make_prompt by joining: <instruction> + <transcript block>.
# Users can override the instruction body via insight_user_prompts; the
# transcript block is appended automatically and is not user-controlled.
SUMMARY_INSTRUCTION = """\
You are summarising a YouTube video from its transcript. Produce a tight,
specific bullet list (10 bullets max) covering the key claims, conclusions
and examples actually present in the video.

Rules:
- Each bullet must carry a concrete claim, fact, or step. Skip filler like
  "the speaker introduces the topic".
- Preserve numbers, model names, version tags, and code/path tokens verbatim.
- Do NOT describe the structure of the video ("the author explains..."); name
  the actual point being made.
- Use Markdown: '- ' for bullets, **bold** for inline emphasis, `code` for
  identifiers. No HTML tags.
- No preamble, no closing remarks. Output only the bullets.
- Reply in {lang}.
"""

ABOUT_INSTRUCTION = """\
You are describing a YouTube video to someone deciding whether to watch it,
based on its transcript. Produce 2-3 sentences (max ~60 words).

Rules:
- First sentence: what the video is about (subject + angle).
- Optional second sentence: most distinctive thing it offers (a specific
  argument, demo, dataset, conclusion).
- Optional third sentence: who would find it useful, in concrete terms ("if
  you maintain Postgres clusters"), not vague ("developers").
- Preserve names, versions, and tokens verbatim.
- Be factual; do not editorialise or speculate beyond the transcript.
- No preamble, no "this video". Just the description text.
- Reply in {lang}.
"""

_TRANSCRIPT_BLOCK = """\

Transcript:
{transcript}
"""


class InsightError(Exception):
    """Raised when summarization fails."""


def _extract_video_id(url: str) -> str | None:
    """Parse a YouTube URL and return the video ID, or None if not recognized."""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if "youtu.be" in host:
        vid = parsed.path.lstrip("/").split("/")[0]
        return vid or None
    if "youtube.com" in host:
        qs = parse_qs(parsed.query)
        if "v" in qs:
            return qs["v"][0]
        # Handles /shorts/<id> and /embed/<id>
        m = re.match(r"/(?:shorts|embed|v)/([A-Za-z0-9_-]+)", parsed.path)
        if m:
            return m.group(1)
    return None


def _fetch_transcript(video_id: str, lang_csv: str) -> str:
    """Fetch transcript text for a video, trying languages in order.

    Raises InsightError if no transcript is available.
    """
    langs = [code.strip() for code in lang_csv.split(",") if code.strip()]
    api = YouTubeTranscriptApi()
    try:
        # Try preferred languages first, then fall back to any available
        transcript_list = api.list(video_id)
        try:
            transcript = transcript_list.find_transcript(langs)
        except NoTranscriptFound:
            # Accept any language - Gemini will translate via prompt
            transcript = transcript_list.find_transcript(
                [t.language_code for t in transcript_list]
            )
        fetched = transcript.fetch()
        return " ".join(snip.text for snip in fetched)
    except TranscriptsDisabled:
        raise InsightError("transcripts_disabled")
    except NoTranscriptFound:
        raise InsightError("no_transcript")
    except Exception as exc:
        logger.warning("Transcript fetch failed for %s: %s", video_id, exc)
        raise InsightError("transcript_error") from exc


class GeminiSummarizer:
    """Fetches a YouTube transcript and summarizes it with the Gemini API."""

    def __init__(self, config: InsightConfig) -> None:
        if not config.gemini_api_key:
            raise InsightError("gemini_not_configured")
        self._client = genai.Client(api_key=config.gemini_api_key)
        self._model = config.gemini_model
        self._lang_csv = config.insight_transcript_langs

    async def _run(self, prompt: str) -> str:
        """Send prompt to Gemini and return complete text response."""
        try:
            response = await asyncio.wait_for(
                self._client.aio.models.generate_content(
                    model=self._model,
                    contents=prompt,
                ),
                timeout=30.0,
            )
        except asyncio.TimeoutError as exc:
            logger.error("Gemini API timeout")
            raise InsightError("api_error") from exc
        except Exception as exc:
            logger.error("Gemini API error: %s", exc)
            raise InsightError("api_error") from exc

        if response.prompt_feedback and response.prompt_feedback.block_reason:
            reason = str(response.prompt_feedback.block_reason.value).lower()
            logger.warning("Gemini blocked prompt: %s", reason)
            if "prohibited" in reason:
                raise InsightError("prohibited_content")
            raise InsightError("content_blocked")

        text = response.text
        if not text or not text.strip():
            raise InsightError("empty_response")

        return text.strip()

    async def stream(self, prompt: str):
        """Yield text chunks from Gemini as they arrive.

        Each yielded value is a str chunk (may be empty string for keep-alive).
        Raises InsightError on API-level failure.
        """
        try:
            async for chunk in await self._client.aio.models.generate_content_stream(
                model=self._model,
                contents=prompt,
            ):
                if chunk.text:
                    yield chunk.text
        except Exception as exc:
            logger.error("Gemini stream error: %s", exc)
            raise InsightError("api_error") from exc

    def _make_prompt(
        self,
        command: str,
        transcript: str,
        lang: str,
        instruction_override: str | None = None,
    ) -> str:
        if instruction_override and instruction_override.strip():
            instruction = instruction_override.strip()
        elif command == "summary":
            instruction = SUMMARY_INSTRUCTION
        else:
            instruction = ABOUT_INSTRUCTION
        if "{lang}" in instruction:
            instruction = instruction.format(lang=lang)
        return instruction + _TRANSCRIPT_BLOCK.format(transcript=transcript)

    async def summarize(self, url: str, lang: str, prompt_override: str | None = None) -> str:
        """Return a bullet-list summary. Raises InsightError on failure."""
        video_id = _extract_video_id(url)
        if not video_id:
            raise InsightError("not_youtube")
        transcript = await asyncio.to_thread(_fetch_transcript, video_id, self._lang_csv)
        return await self._run(self._make_prompt("summary", transcript, lang, prompt_override))

    async def describe(self, url: str, lang: str, prompt_override: str | None = None) -> str:
        """Return a 2-3 sentence description. Raises InsightError on failure."""
        video_id = _extract_video_id(url)
        if not video_id:
            raise InsightError("not_youtube")
        transcript = await asyncio.to_thread(_fetch_transcript, video_id, self._lang_csv)
        return await self._run(self._make_prompt("about", transcript, lang, prompt_override))

    async def stream_command(
        self, url: str, lang: str, command: str,
        prompt_override: str | None = None,
    ):
        """Yield text chunks for summary or describe command.

        Fetches transcript once, then streams from Gemini.
        Raises InsightError if video_id or transcript cannot be resolved.
        """
        video_id = _extract_video_id(url)
        if not video_id:
            raise InsightError("not_youtube")
        transcript = await asyncio.to_thread(_fetch_transcript, video_id, self._lang_csv)
        prompt = self._make_prompt(command, transcript, lang, prompt_override)
        async for chunk in self.stream(prompt):
            yield chunk
