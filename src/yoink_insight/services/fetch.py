"""Web and GitHub content fetching for /tldr.

Fetch strategy (tried in order):
  1. GitHub URLs  -> GitHub API (repos, files, issues, PRs, commits, releases)
  2. llms.txt     -> follow matched path if found
  3. readability  -> extract main article text (like defuddle/Readability.js)
  4. trafilatura  -> fallback extractor
  5. jina.ai      -> markdown provider
  6. curl.md      -> markdown provider
  7. raw HTML     -> regex strip as last resort
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

_USER_AGENT = "Mozilla/5.0 (compatible; yoink-insight/1.0)"
_TIMEOUT = 30.0

_GITHUB_HOSTS = {"github.com", "api.github.com", "raw.githubusercontent.com"}

# Shared GitHub client. Reusing one client lets httpx keep the TCP/TLS pool
# warm across calls and apply transport-level retries; a fresh AsyncClient
# per call surfaces every transient pool reset as ConnectError(''). The
# transport retries 2 transient connection failures before bubbling up.
_github_client: httpx.AsyncClient | None = None
_github_client_lock = asyncio.Lock()

# Proxy for plain-HTML / markdown-provider fetches when the host can't reach
# raw.githubusercontent.com or r.jina.ai directly. yt-dlp downloader already
# uses this socks5 env on yoink hosts; reuse it here so /tldr fallback paths
# don't dead-end with ConnectError on github.com / 451 on Jina.
_FALLBACK_PROXY = os.environ.get("proxy_url") or os.environ.get("PROXY_URL")


async def _get_github_client() -> httpx.AsyncClient:
    global _github_client
    if _github_client is not None:
        return _github_client
    async with _github_client_lock:
        if _github_client is None:
            transport = httpx.AsyncHTTPTransport(retries=2)
            _github_client = httpx.AsyncClient(
                timeout=20.0,
                transport=transport,
                follow_redirects=True,
                headers={
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                    "User-Agent": _USER_AGENT,
                },
            )
    return _github_client
_MARKDOWN_PROVIDERS = [
    ("jina",    "https://r.jina.ai/{url}",   {"Accept": "text/markdown", "X-No-Cache": "true", "X-Return-Format": "markdown"}),
    ("curl.md", "https://curl.md/{url}",      {"Accept": "text/markdown"}),
]


@dataclass
class FetchResult:
    content: str
    title: str | None
    via: str


# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------

def _parse_github_url(url: str) -> dict | None:
    """Return a dict describing the GitHub API call implied by the URL, or None."""
    try:
        p = urlparse(url)
    except Exception:
        return None
    host = (p.hostname or "").lower()
    parts = [x for x in p.path.split("/") if x]

    if host == "raw.githubusercontent.com":
        # raw.githubusercontent.com/owner/repo/ref/path...
        if len(parts) < 4:
            return None
        owner, repo, ref, *rest = parts
        return {"op": "raw_file", "owner": owner, "repo": repo,
                "ref": ref, "path": "/".join(rest)}

    if host == "api.github.com":
        return {"op": "api_passthrough", "path": p.path.lstrip("/") + (("?" + p.query) if p.query else "")}

    if host != "github.com":
        return None

    if len(parts) < 2:
        return None
    owner, repo, *rest = parts
    section = rest[0] if rest else None

    if not section:
        return {"op": "repo_info", "owner": owner, "repo": repo}
    if section == "blob" and len(rest) >= 3:
        ref, *fp = rest[1:]
        return {"op": "file", "owner": owner, "repo": repo, "ref": ref, "path": "/".join(fp)}
    if section == "tree":
        ref = rest[1] if len(rest) > 1 else "HEAD"
        dir_path = "/".join(rest[2:]) if len(rest) > 2 else ""
        return {"op": "tree", "owner": owner, "repo": repo, "ref": ref, "path": dir_path}
    if section == "issues":
        if len(rest) > 1 and rest[1].isdigit():
            return {"op": "issue", "owner": owner, "repo": repo, "number": int(rest[1])}
        return {"op": "issues", "owner": owner, "repo": repo, "state": "open"}
    if section in ("pull", "pulls"):
        if len(rest) > 1 and rest[1].isdigit():
            return {"op": "pr", "owner": owner, "repo": repo, "number": int(rest[1])}
        return {"op": "prs", "owner": owner, "repo": repo, "state": "open"}
    if section == "commits":
        branch = rest[1] if len(rest) > 1 else None
        return {"op": "commits", "owner": owner, "repo": repo, "branch": branch}
    if section == "releases":
        return {"op": "releases", "owner": owner, "repo": repo}

    return {"op": "repo_info", "owner": owner, "repo": repo}


def _to_toon(data: object) -> str:
    """Encode a JSON-serializable object as TOON for token-efficient LLM input."""
    try:
        from toon_format import encode  # noqa: PLC0415
        return encode(data)
    except Exception:
        import json  # noqa: PLC0415
        return json.dumps(data, ensure_ascii=False, indent=2)


async def _github_fetch(route: dict, token: str | None) -> str:
    # Auth header is per-call (the shared client has only the static headers).
    auth_headers: dict[str, str] = {}
    if token:
        auth_headers["Authorization"] = f"Bearer {token}"

    base = "https://api.github.com"
    op = route["op"]
    client = await _get_github_client()

    if op == "raw_file":
        raw_url = f"https://raw.githubusercontent.com/{route['owner']}/{route['repo']}/{route['ref']}/{route['path']}"
        r = await client.get(raw_url, headers=auth_headers)
        r.raise_for_status()
        return r.text

    if op == "api_passthrough":
        r = await client.get(f"{base}/{route['path']}", headers=auth_headers)
        r.raise_for_status()
        return _to_toon(r.json())

    if op == "file":
        # Try raw first (no API rate limit hit)
        raw_url = f"https://raw.githubusercontent.com/{route['owner']}/{route['repo']}/{route['ref']}/{route['path']}"
        r = await client.get(raw_url, headers=auth_headers)
        if r.status_code == 200:
            return r.text
        # Fall back to contents API (returns base64)
        import base64
        api_url = f"{base}/repos/{route['owner']}/{route['repo']}/contents/{route['path']}?ref={route['ref']}"
        r = await client.get(api_url, headers=auth_headers)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict) and data.get("encoding") == "base64":
            return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        return _to_toon(data)

    if op == "tree":
        api_url = f"{base}/repos/{route['owner']}/{route['repo']}/git/trees/{route['ref']}?recursive=1"
        r = await client.get(api_url, headers=auth_headers)
        r.raise_for_status()
        tree = r.json().get("tree", [])
        path_prefix = route.get("path", "")
        lines = []
        for item in tree:
            p = item.get("path", "")
            if path_prefix and not p.startswith(path_prefix):
                continue
            lines.append(f"{item.get('type','?'):4}  {p}")
        return "\n".join(lines)

    if op == "repo_info":
        r = await client.get(f"{base}/repos/{route['owner']}/{route['repo']}", headers=auth_headers)
        r.raise_for_status()
        d = r.json()
        lines = [
            f"# {d.get('full_name','')}",
            d.get("description") or "",
            "",
            f"Stars: {d.get('stargazers_count',0)}  Forks: {d.get('forks_count',0)}  Open issues: {d.get('open_issues_count',0)}",
            f"Language: {d.get('language','?')}  License: {(d.get('license') or {}).get('spdx_id','?')}",
            f"Default branch: {d.get('default_branch','main')}",
            f"URL: {d.get('html_url','')}",
        ]
        # Fetch README
        try:
            rr = await client.get(f"{base}/repos/{route['owner']}/{route['repo']}/readme", headers=auth_headers)
            if rr.status_code == 200:
                import base64 as _b64
                rd = rr.json()
                readme = _b64.b64decode(rd["content"]).decode("utf-8", errors="replace")
                lines += ["", "## README", readme[:4000]]
        except Exception:
            pass
        return "\n".join(lines)

    if op == "issue":
        r = await client.get(f"{base}/repos/{route['owner']}/{route['repo']}/issues/{route['number']}", headers=auth_headers)
        r.raise_for_status()
        d = r.json()
        lines = [
            f"# Issue #{d['number']}: {d['title']}",
            f"State: {d['state']}  Author: {d['user']['login']}",
            "",
            d.get("body") or "(no body)",
        ]
        cr = await client.get(f"{base}/repos/{route['owner']}/{route['repo']}/issues/{route['number']}/comments?per_page=20", headers=auth_headers)
        if cr.status_code == 200:
            for c in cr.json():
                lines += ["", f"--- @{c['user']['login']} ---", c.get("body") or ""]
        return "\n".join(lines)

    if op == "issues":
        r = await client.get(
            f"{base}/repos/{route['owner']}/{route['repo']}/issues",
            params={"state": route.get("state", "open"), "per_page": 30},
            headers=auth_headers,
        )
        r.raise_for_status()
        items = [
            {"number": i["number"], "state": i["state"], "title": i["title"], "author": i["user"]["login"]}
            for i in r.json() if "pull_request" not in i
        ]
        return f"## Issues ({route.get('state', 'open')})\n" + _to_toon(items)

    if op == "pr":
        r = await client.get(f"{base}/repos/{route['owner']}/{route['repo']}/pulls/{route['number']}", headers=auth_headers)
        r.raise_for_status()
        d = r.json()
        lines = [
            f"# PR #{d['number']}: {d['title']}",
            f"State: {d['state']}  Author: {d['user']['login']}",
            f"Base: {d['base']['ref']} <- Head: {d['head']['ref']}",
            "",
            d.get("body") or "(no body)",
        ]
        cr = await client.get(f"{base}/repos/{route['owner']}/{route['repo']}/pulls/{route['number']}/comments?per_page=20", headers=auth_headers)
        if cr.status_code == 200:
            for c in cr.json():
                lines += ["", f"--- @{c['user']['login']} on `{c.get('path','')}` ---", c.get("body") or ""]
        return "\n".join(lines)

    if op == "prs":
        r = await client.get(
            f"{base}/repos/{route['owner']}/{route['repo']}/pulls",
            params={"state": route.get("state", "open"), "per_page": 30},
            headers=auth_headers,
        )
        r.raise_for_status()
        items = [
            {"number": pr["number"], "state": pr["state"], "title": pr["title"], "author": pr["user"]["login"]}
            for pr in r.json()
        ]
        return f"## Pull requests ({route.get('state', 'open')})\n" + _to_toon(items)

    if op == "commits":
        params: dict = {"per_page": 30}
        if route.get("branch"):
            params["sha"] = route["branch"]
        r = await client.get(f"{base}/repos/{route['owner']}/{route['repo']}/commits", params=params, headers=auth_headers)
        r.raise_for_status()
        items = [
            {"sha": c["sha"][:8], "message": c["commit"]["message"].splitlines()[0][:80], "author": c["commit"]["author"]["name"]}
            for c in r.json()
        ]
        return "## Commits\n" + _to_toon(items)

    if op == "releases":
        r = await client.get(f"{base}/repos/{route['owner']}/{route['repo']}/releases?per_page=10", headers=auth_headers)
        r.raise_for_status()
        items = [
            {"tag": rel["tag_name"], "name": rel["name"], "published": rel.get("published_at", "")[:10], "body": (rel.get("body") or "")[:300]}
            for rel in r.json()
        ]
        return "## Releases\n" + _to_toon(items)

    return ""



# ---------------------------------------------------------------------------
# HTML extraction
# ---------------------------------------------------------------------------

def _readability_extract(html: str, url: str) -> tuple[str, str | None]:
    """Extract main article text using readability-lxml. Returns (text, title)."""
    try:
        from readability import Document
        doc = Document(html, url=url)
        title = doc.title()
        summary_html = doc.summary()
        text = _html_to_text(summary_html)
        return text, title or None
    except Exception as exc:
        logger.debug("readability failed: %s", exc)
        return "", None


def _trafilatura_extract(html: str) -> str:
    try:
        import trafilatura
        result = trafilatura.extract(html, include_comments=False, include_tables=True, no_fallback=False)
        return result or ""
    except Exception as exc:
        logger.debug("trafilatura failed: %s", exc)
        return ""


def _html_to_text(html: str) -> str:
    """Best-effort HTML -> plain text via BeautifulSoup."""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form", "iframe"]):
            tag.decompose()
        return soup.get_text(separator="\n", strip=True)
    except Exception:
        # Regex strip as last resort
        text = re.sub(r"<[^>]+>", " ", html)
        return re.sub(r"\s{3,}", "\n\n", text).strip()


# ---------------------------------------------------------------------------
# llms.txt
# ---------------------------------------------------------------------------

async def _check_llms_txt(url: str, client: httpx.AsyncClient) -> str | None:
    """If origin has llms.txt and it matches the requested path, return the matched URL."""
    try:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        r = await client.get(f"{origin}/llms.txt", timeout=8.0)
        if r.status_code != 200 or len(r.text) < 50:
            return None
        requested_path = parsed.path.rstrip("/")
        link_re = re.compile(r'\[([^\]]+)\]\((https?://[^)]+)\)')
        for m in link_re.finditer(r.text):
            link_url = m.group(2)
            try:
                link_path = urlparse(link_url).path.rstrip("/").rstrip("/index.md").rstrip(".md")
                if link_path == requested_path:
                    return link_url
            except Exception:
                continue
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Markdown providers
# ---------------------------------------------------------------------------

async def _fetch_via_provider(url: str, name: str, provider_url: str, extra_headers: dict, client: httpx.AsyncClient) -> str | None:
    try:
        target = provider_url.format(url=url)
        r = await client.get(target, headers={**extra_headers, "User-Agent": _USER_AGENT}, timeout=20.0)
        if r.status_code == 200 and len(r.text) > 100:
            stripped = _strip_provider_chrome(r.text)
            # After chrome removal a 404 / empty-article page from the
            # provider often collapses to a few '---' separators and
            # whitespace. Anything below this threshold has no useful
            # body, so we treat it as a miss and let the caller try the
            # next strategy instead of feeding the LLM dashes.
            if len(re.sub(r"[\s\-]+", "", stripped)) >= 100:
                return stripped
            logger.debug("%s returned only chrome/separators (len=%d after strip), skipping", name, len(stripped))
    except Exception as exc:
        logger.debug("%s failed: %s", name, exc)
    return None


# Patterns the curl.md / jina markdown providers emit around the actual
# article body. We strip them so the LLM sees only the content the user
# cares about, not the source URL, domain, author avatar, or 'Powered by'
# footer. We intentionally do NOT touch inline images further down the
# body: those carry alt text the model can use; only the hero image
# directly after the H1 and the author avatar link are decoration.
_FRONT_MATTER_RE = re.compile(r"\A---\n.*?\n---\n+", re.DOTALL)
_PROVIDER_FOOTER_RE = re.compile(
    r"(?:\A|\n+)---\n+Powered by \[(?:curl\.md|Jina[^\]]*)\]\([^)]+\)\s*\Z",
    re.IGNORECASE,
)
# Author avatar link: [![Name](image-url)](/author/slug/) or similar.
_AUTHOR_AVATAR_RE = re.compile(r"\[!\[[^\]]*\]\([^)]+\)\]\(/[^)]*author[^)]*\)\s*")
# Plain 'By [Name](/author/...)' byline emitted by curl.md when the source
# page links the author. Matches at start of line; one byline per article.
_BYLINE_RE = re.compile(r"^By\s+\[[^\]]+\]\([^)]*author[^)]*\)\s*\n+", re.MULTILINE)
# 'Published ...' timestamp line that follows the byline on most CMS
# templates. Tolerant about formatting (date/time/timezone shapes vary).
_PUBLISHED_RE = re.compile(r"^Published[^\n]{0,80}\n+", re.MULTILINE)
# Author bio paragraph that XDA-style sites embed between the byline
# block and the article body. Heuristic: a paragraph that opens with one
# of the known bio starters and ends at the next blank line. Tightened
# enough to never bite into article prose.
_AUTHOR_BIO_RE = re.compile(
    r"^(?:Beginning|Born|Currently|Originally|Based|Working|Writing|Having|With over)\b[^\n]*(?:\n[^\n]+)*\n\n",
    re.MULTILINE,
)
# Hero image: an ![alt](url) that appears immediately after the first H1
# heading. Anchored to '# heading\n...![...](...)' to avoid stripping
# inline images in the body.
_HERO_IMAGE_RE = re.compile(
    r"(\A|\n)(#\s+[^\n]+\n+)!\[[^\]]*\]\([^)]+\)\s*\n+",
)


def _strip_provider_chrome(text: str) -> str:
    """Remove curl.md / jina decoration that leaks the source URL and
    surrounding chrome but does not contribute to the article content.

    Strips, in order: YAML front-matter at the top (url/site/publish_date),
    the hero image right under the H1, the author avatar link, the
    'By [Name](/author/...)' byline, the 'Published ...' timestamp, the
    author bio paragraph, and the 'Powered by ...' footer. Each substitution
    is bounded (count=1 where the pattern is one-shot) so a future change in
    provider output degrades to a no-op rather than a corrupted body.
    """
    out = _FRONT_MATTER_RE.sub("", text, count=1)
    out = _HERO_IMAGE_RE.sub(r"\1\2", out, count=1)
    out = _AUTHOR_AVATAR_RE.sub("", out, count=1)
    # Byline / publish-date / bio may appear more than once: many CMSs
    # (XDA in particular) embed 'related article' cards inside the body,
    # each with its own 'By [Name](/author/...)' line. Strip every
    # occurrence so the model sees only the article prose.
    out = _BYLINE_RE.sub("", out)
    out = _PUBLISHED_RE.sub("", out)
    out = _AUTHOR_BIO_RE.sub("", out, count=1)
    out = _PROVIDER_FOOTER_RE.sub("", out)
    return out.strip() + "\n"


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def fetch_web_content(url: str, max_chars: int, github_token: str | None = None) -> FetchResult:
    """Fetch URL and return extracted text content.

    Strategy:
      GitHub URLs -> GitHub API
      Others:
        1. llms.txt match
        2. readability-lxml (defuddle equivalent)
        3. trafilatura
        4. jina.ai
        5. curl.md
        6. raw HTML strip
    """
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()

    # GitHub
    is_github = host in _GITHUB_HOSTS
    if is_github:
        route = _parse_github_url(url)
        if route:
            logger.debug("GitHub fetch op=%s auth=%s url=%s", route.get("op"), bool(github_token), url)
            try:
                text = await _github_fetch(route, github_token)
                if text.strip():
                    if len(text) > max_chars:
                        text = text[:max_chars] + "\n\n[Content truncated]"
                    return FetchResult(content=text, title=None, via=f"github-api:{route['op']}")
                logger.warning("GitHub API returned empty content for %s op=%s, falling back", url, route.get("op"))
            except Exception as exc:
                # repr() exposes ConnectError(''), TimeoutException(''), etc.
                # The bare str(exc) is empty for many httpx network errors.
                logger.warning(
                    "GitHub API fetch failed for %s op=%s: %r",
                    url, route.get("op"), exc,
                )

    client_kwargs: dict = {
        "timeout": _TIMEOUT,
        "follow_redirects": True,
        "headers": {"User-Agent": _USER_AGENT},
    }
    if _FALLBACK_PROXY:
        client_kwargs["proxy"] = _FALLBACK_PROXY
    async with httpx.AsyncClient(**client_kwargs) as client:
        # llms.txt (skip for GitHub - they don't have /llms.txt)
        if not is_github:
            matched_url = await _check_llms_txt(url, client)
        else:
            matched_url = None
        fetch_url = matched_url or url
        via_prefix = "llms.txt+" if matched_url else ""

        # Fetch raw HTML once, reuse for multiple extractors
        html: str | None = None
        try:
            r = await client.get(fetch_url, timeout=_TIMEOUT)
            if r.status_code < 400:
                html = r.text
        except httpx.RequestError as exc:
            logger.warning("HTTP fetch failed for %s: %r", fetch_url, exc)

        if html and not is_github:
            # readability
            text, title = await asyncio.to_thread(_readability_extract, html, fetch_url)
            if text and len(text) > 200:
                if len(text) > max_chars:
                    text = text[:max_chars] + "\n\n[Content truncated]"
                return FetchResult(content=text, title=title, via=f"{via_prefix}readability")

            # trafilatura
            text = await asyncio.to_thread(_trafilatura_extract, html)
            if text and len(text) > 200:
                if len(text) > max_chars:
                    text = text[:max_chars] + "\n\n[Content truncated]"
                return FetchResult(content=text, title=None, via=f"{via_prefix}trafilatura")

        # Markdown providers
        for name, provider_url, extra_headers in _MARKDOWN_PROVIDERS:
            text = await _fetch_via_provider(url, name, provider_url, extra_headers, client)
            if text:
                if len(text) > max_chars:
                    text = text[:max_chars] + "\n\n[Content truncated]"
                return FetchResult(content=text, title=None, via=name)

        # Raw HTML strip as last resort (skip for GitHub - HTML is useless there)
        if html and not is_github and len(html) > 200:
            text = await asyncio.to_thread(_html_to_text, html)
            if text and len(text) > 100:
                title_m = re.search(r"<title[^>]*>([^<]+)</title>", html, re.I)
                title = title_m.group(1).strip() if title_m else None
                if len(text) > max_chars:
                    text = text[:max_chars] + "\n\n[Content truncated]"
                return FetchResult(content=text, title=title, via="raw-html")

    raise _FetchError("no_content")


class _FetchError(Exception):
    pass
