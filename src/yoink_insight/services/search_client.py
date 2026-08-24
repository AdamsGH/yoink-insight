"""Native OpenAI Responses web search for TLDR evidence enrichment."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from json import JSONDecodeError
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from yoink_insight.config import InsightConfig

logger = logging.getLogger(__name__)


@dataclass
class SearchSource:
    url: str
    title: str
    snippet: str


@dataclass
class SearchFetchResult:
    sources: list[SearchSource]
    via: str
    answer: str = ""


class SearchFetchError(Exception):
    """Raised when native web search fails or returns no usable evidence."""


def _responses_endpoint(base_url: str) -> str:
    return base_url.rstrip("/") + "/responses"


def _parse_response_payload(text: str) -> dict[str, Any]:
    try:
        payload = json.loads(text)
    except JSONDecodeError:
        payload = None
    if isinstance(payload, dict):
        return payload

    output_items: list[dict[str, Any]] = []
    completed: dict[str, Any] | None = None
    for line in text.splitlines():
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data or data == "[DONE]":
            continue
        try:
            event = json.loads(data)
        except JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") == "response.output_item.done" and isinstance(event.get("item"), dict):
            output_items.append(event["item"])
        if event.get("type") in {"response.done", "response.completed"} and isinstance(
            event.get("response"), dict
        ):
            completed = event["response"]
    if completed is not None:
        completed_output = completed.get("output")
        if not isinstance(completed_output, list) or not completed_output:
            completed["output"] = output_items
        return completed
    if output_items:
        return {"output": output_items}
    raise SearchFetchError("invalid_response")


def _snippet(text: str, start: Any, end: Any) -> str:
    if not isinstance(start, int) or not isinstance(end, int):
        return ""
    return text[max(0, start - 120):min(len(text), end + 120)].strip()


def _extract_search_result(payload: dict[str, Any]) -> tuple[str, list[SearchSource]]:
    output = payload.get("output")
    if not isinstance(output, list):
        output = []
    answer_parts: list[str] = []
    sources: list[SearchSource] = []
    seen: set[str] = set()

    def add_source(url: Any, title: Any, snippet: str = "") -> None:
        if not isinstance(url, str) or not url.strip() or url in seen:
            return
        seen.add(url)
        sources.append(
            SearchSource(
                url=url,
                title=title if isinstance(title, str) and title.strip() else url,
                snippet=snippet,
            )
        )

    for item in output:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "message" and isinstance(item.get("content"), list):
            for part in item["content"]:
                if not isinstance(part, dict):
                    continue
                text = part.get("text")
                if isinstance(text, str) and text.strip():
                    answer_parts.append(text.strip())
                annotations = part.get("annotations")
                if not isinstance(annotations, list):
                    continue
                for annotation in annotations:
                    if not isinstance(annotation, dict) or annotation.get("type") != "url_citation":
                        continue
                    add_source(
                        annotation.get("url"),
                        annotation.get("title"),
                        _snippet(text if isinstance(text, str) else "", annotation.get("start_index"), annotation.get("end_index")),
                    )
        if item.get("type") == "web_search_call":
            action = item.get("action") if isinstance(item.get("action"), dict) else {}
            for group in (action.get("sources"), item.get("sources"), item.get("results")):
                if not isinstance(group, list):
                    continue
                for source in group:
                    if isinstance(source, dict):
                        add_source(
                            source.get("url") or source.get("source_website_url"),
                            source.get("title") or source.get("caption"),
                        )
    return "\n".join(answer_parts), sources


async def search_fetch(
    query: str,
    config: InsightConfig,
    *,
    model: str | None = None,
    top_k: int = 5,
) -> SearchFetchResult:
    """Run server-side native web search through the configured Responses endpoint."""
    selected_model = model or config.tldr_search_model or config.tldr_llm_model
    if not selected_model:
        raise SearchFetchError("search_model_required")
    endpoint = _responses_endpoint(config.gateway_base_url)
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if config.gateway_api_key:
        headers["Authorization"] = f"Bearer {config.gateway_api_key}"
    body = {
        "model": selected_model,
        "instructions": (
            "Search the web for independent evidence relevant to the request. Prefer primary "
            "sources, reproducible measurements, upstream documentation, and contrary evidence. "
            "Return a concise factual synthesis with clickable citations."
        ),
        "input": [{"role": "user", "content": [{"type": "input_text", "text": query}]}],
        "tools": [{"type": "web_search"}],
        "include": ["web_search_call.action.sources"],
        "store": False,
        "stream": False,
        "tool_choice": "required",
        "parallel_tool_calls": True,
    }

    try:
        async with httpx.AsyncClient(timeout=config.tldr_search_timeout_seconds) as client:
            response = await client.post(endpoint, json=body, headers=headers)
    except httpx.RequestError as exc:
        logger.warning("native web search request failed: %s", exc)
        raise SearchFetchError("gateway_unavailable") from exc
    if response.status_code != 200:
        logger.warning("native web search returned %d: %s", response.status_code, response.text[:200])
        raise SearchFetchError("search_error")

    payload = _parse_response_payload(response.text)
    answer, sources = _extract_search_result(payload)
    sources = sources[:top_k]
    if not answer and not sources:
        raise SearchFetchError("no_content")
    return SearchFetchResult(sources=sources, via="openai-responses:web_search", answer=answer)


def join_sources_for_llm(result: SearchFetchResult) -> str:
    answer = result.answer.strip()
    sources = result.sources
    blocks: list[str] = []
    if answer:
        blocks.append("Grounded web-search synthesis:\n" + answer)
    for index, source in enumerate(sources, 1):
        lines = [f"Source {index}: {source.title or source.url}", f"URL: {source.url}"]
        if source.snippet.strip():
            lines.append("Relevant passage: " + source.snippet.strip())
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)
