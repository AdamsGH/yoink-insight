"""Convert markdown to (plain_text, [MessageEntity dicts]) for Telegram Bot API.

Pass the result as text= and entities= to sendMessage instead of parse_mode.
No escaping required - plain text is transmitted as-is.

Telegram entity offsets/lengths are in UTF-16 code units (surrogate pairs for
characters outside BMP count as 2). All arithmetic here uses utf16_len().

Supported:
  **bold** / __bold__
  *italic* / _italic_
  `inline code`
  ```code block```
  [text](url)
  # headings -> bold line
  - / * bullet lists -> bullet char prefix
"""
from __future__ import annotations

import logging
import re

from markdown_it import MarkdownIt
from markdown_it.token import Token

logging.getLogger("markdown_it").setLevel(logging.WARNING)


def _utf16_len(s: str) -> int:
    """Number of UTF-16 code units used by string s."""
    return sum(2 if ord(c) > 0xFFFF else 1 for c in s)


def md_to_entities(text: str) -> tuple[str, list[dict]]:
    """Parse markdown, return (plain_text, entities).

    entities items are dicts: {type, offset, length} or {type, offset, length, url}.
    Offsets and lengths are in UTF-16 code units as required by Telegram Bot API.
    """
    md = MarkdownIt("commonmark")
    tokens = md.parse(text)

    chars: list[str] = []
    entities: list[dict] = []

    # Running UTF-16 offset counter
    _utf16_pos = 0

    def pos() -> int:
        return _utf16_pos

    # Stack of open spans: (entity_type, utf16_start, url)
    stack: list[tuple[str, int, str]] = []

    def append_text(s: str) -> None:
        nonlocal _utf16_pos
        chars.append(s)
        _utf16_pos += _utf16_len(s)

    def open_span(etype: str, url: str = "") -> None:
        stack.append((etype, pos(), url))

    def close_span(etype: str) -> None:
        for i in range(len(stack) - 1, -1, -1):
            if stack[i][0] == etype:
                _, start, url = stack.pop(i)
                length = pos() - start
                if length > 0:
                    ent: dict = {"type": etype, "offset": start, "length": length}
                    if url:
                        ent["url"] = url
                    entities.append(ent)
                return

    _in_link = False

    def walk_inline(children: list[Token]) -> None:
        nonlocal _in_link
        for tok in children:
            t = tok.type
            if t == "text":
                append_text(tok.content)
            elif t in ("softbreak", "hardbreak"):
                append_text("\n")
            elif t == "strong_open":
                if not _in_link:
                    open_span("bold")
            elif t == "strong_close":
                if not _in_link:
                    close_span("bold")
            elif t == "em_open":
                if not _in_link:
                    open_span("italic")
            elif t == "em_close":
                if not _in_link:
                    close_span("italic")
            elif t == "code_inline":
                start = pos()
                append_text(tok.content)
                if not _in_link:
                    entities.append({"type": "code", "offset": start, "length": pos() - start})
            elif t == "link_open":
                href = dict(tok.attrs or {}).get("href", "")
                open_span("text_link", href)
                _in_link = True
            elif t == "link_close":
                close_span("text_link")
                _in_link = False
            elif t == "html_inline":
                append_text(re.sub(r"<[^>]+>", "", tok.content))
            elif tok.children:
                walk_inline(tok.children)

    def newline_if_needed() -> None:
        if chars and chars[-1][-1:] != "\n":
            append_text("\n")

    _in_list_item = False

    for tok in tokens:
        t = tok.type

        if t == "inline":
            walk_inline(tok.children or [])

        elif t == "paragraph_open":
            if not _in_list_item:
                newline_if_needed()
        elif t == "paragraph_close":
            if not _in_list_item:
                append_text("\n")

        elif t == "heading_open":
            newline_if_needed()
            open_span("bold")
        elif t == "heading_close":
            close_span("bold")
            append_text("\n")

        elif t == "list_item_open":
            newline_if_needed()
            append_text("\u2022 ")
            _in_list_item = True
        elif t == "list_item_close":
            _in_list_item = False
            append_text("\n\n")

        elif t in ("bullet_list_open", "ordered_list_open"):
            newline_if_needed()
        elif t in ("bullet_list_close", "ordered_list_close"):
            pass

        elif t in ("fence", "code_block"):
            newline_if_needed()
            start = pos()
            content = tok.content.rstrip("\n")
            append_text(content)
            entities.append({"type": "pre", "offset": start, "length": pos() - start})

        elif t == "hr":
            newline_if_needed()

        elif t == "html_block":
            append_text(re.sub(r"<[^>]+>", "", tok.content))

    raw = "".join(chars)

    # Collapse 3+ newlines to 2
    # Need to recompute offsets after stripping leading newlines
    stripped = raw.lstrip("\n")
    leading = _utf16_len(raw) - _utf16_len(stripped)
    # Also collapse triple+ newlines
    result = re.sub(r"\n{3,}", "\n\n", stripped).rstrip()

    if leading > 0:
        entities = [
            {**e, "offset": e["offset"] - leading}
            for e in entities
            if e["offset"] >= leading
        ]

    return result, entities
