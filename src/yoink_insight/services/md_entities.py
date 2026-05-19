"""Convert markdown to (plain_text, [MessageEntity dicts]) for Telegram Bot API.

Pass the result as text= and entities= to sendMessage instead of parse_mode.
No escaping required - plain text is transmitted as-is.

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

import re

from markdown_it import MarkdownIt
from markdown_it.token import Token


def md_to_entities(text: str) -> tuple[str, list[dict]]:
    """Parse markdown, return (plain_text, entities).

    entities items are dicts: {type, offset, length} or {type, offset, length, url}.
    Pass as telegram.MessageEntity(**item) or directly via Bot API json.
    """
    md = MarkdownIt("commonmark")
    tokens = md.parse(text)

    chars: list[str] = []
    entities: list[dict] = []

    # Stack of open spans: (entity_type, start_offset, url)
    stack: list[tuple[str, int, str]] = []

    def pos() -> int:
        return sum(len(c) for c in chars)

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

    def walk_inline(children: list[Token]) -> None:
        for tok in children:
            t = tok.type
            if t == "text":
                chars.append(tok.content)
            elif t in ("softbreak", "hardbreak"):
                chars.append("\n")
            elif t == "strong_open":
                open_span("bold")
            elif t == "strong_close":
                close_span("bold")
            elif t == "em_open":
                open_span("italic")
            elif t == "em_close":
                close_span("italic")
            elif t == "code_inline":
                start = pos()
                chars.append(tok.content)
                entities.append({"type": "code", "offset": start, "length": len(tok.content)})
            elif t == "link_open":
                href = dict(tok.attrs or {}).get("href", "")
                open_span("text_link", href)
            elif t == "link_close":
                close_span("text_link")
            elif t == "html_inline":
                chars.append(re.sub(r"<[^>]+>", "", tok.content))
            elif tok.children:
                walk_inline(tok.children)

    def newline_if_needed() -> None:
        if chars and chars[-1] != "\n":
            chars.append("\n")

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
                chars.append("\n")

        elif t == "heading_open":
            newline_if_needed()
            open_span("bold")
        elif t == "heading_close":
            close_span("bold")
            chars.append("\n")

        elif t == "list_item_open":
            newline_if_needed()
            chars.append("\u2022 ")
            _in_list_item = True
        elif t == "list_item_close":
            _in_list_item = False
            chars.append("\n")

        elif t in ("bullet_list_open", "ordered_list_open"):
            newline_if_needed()
        elif t in ("bullet_list_close", "ordered_list_close"):
            pass

        elif t in ("fence", "code_block"):
            newline_if_needed()
            start = pos()
            content = tok.content.rstrip("\n")
            chars.append(content)
            entities.append({"type": "pre", "offset": start, "length": len(content)})

        elif t == "hr":
            newline_if_needed()

        elif t == "html_block":
            chars.append(re.sub(r"<[^>]+>", "", tok.content))

    result = re.sub(r"\n{3,}", "\n\n", "".join(chars)).strip()

    # If leading whitespace was stripped, shift entity offsets
    stripped_start = len("".join(chars)) - len("".join(chars).lstrip("\n"))
    if stripped_start > 0:
        entities = [
            {**e, "offset": e["offset"] - stripped_start}
            for e in entities
            if e["offset"] - stripped_start >= 0
        ]

    return result, entities
