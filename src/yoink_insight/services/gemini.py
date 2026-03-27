"""GeminiSummarizer - summarize YouTube videos via transcript + Gemini API."""
from __future__ import annotations

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

SUMMARY_PROMPT = """\
Below is the transcript of a YouTube video. Summarize its key points as a \
concise bullet list (10 bullets max). Reply in {lang}. Do not include any \
preamble - output the bullet list directly.

Transcript:
{transcript}
"""

ABOUT_PROMPT = """\
Below is the transcript of a YouTube video. Describe what the video is about \
in 2-3 sentences. Be concise and factual. Reply in {lang}. Output only the \
description, no preamble.

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
    langs = [l.strip() for l in lang_csv.split(",") if l.strip()]
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
        """Send prompt to Gemini API and return the text response."""
        try:
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=prompt,
            )
            text = response.text
        except Exception as exc:
            logger.error("Gemini API error: %s", exc)
            raise InsightError("api_error") from exc

        if not text or not text.strip():
            raise InsightError("empty_response")

        return text.strip()

    async def summarize(self, url: str, lang: str) -> str:
        """Return a bullet-list summary of the YouTube video at url.

        Raises InsightError on any failure.
        """
        video_id = _extract_video_id(url)
        if not video_id:
            raise InsightError("not_youtube")

        transcript = _fetch_transcript(video_id, self._lang_csv)

        prompt = SUMMARY_PROMPT.format(transcript=transcript, lang=lang)
        return await self._run(prompt)

    async def describe(self, url: str, lang: str) -> str:
        """Return a 2-3 sentence description of the YouTube video at url."""
        video_id = _extract_video_id(url)
        if not video_id:
            raise InsightError("not_youtube")

        transcript = _fetch_transcript(video_id, self._lang_csv)
        prompt = ABOUT_PROMPT.format(transcript=transcript, lang=lang)
        return await self._run(prompt)
