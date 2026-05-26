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
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

_USER_AGENT = "Mozilla/5.0 (compatible; yoink-insight/1.0)"
_TIMEOUT = 30.0

_GITHUB_HOSTS = {"github.com", "api.github.com", "raw.githubusercontent.com"}
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
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    base = "https://api.github.com"
    op = route["op"]

    async with httpx.AsyncClient(timeout=20.0, headers=headers) as client:
        if op == "raw_file":
            raw_url = f"https://raw.githubusercontent.com/{route['owner']}/{route['repo']}/{route['ref']}/{route['path']}"
            r = await client.get(raw_url)
            r.raise_for_status()
            return r.text

        if op == "api_passthrough":
            r = await client.get(f"{base}/{route['path']}")
            r.raise_for_status()
            return _to_toon(r.json())

        if op == "file":
            # Try raw first (no API rate limit hit)
            raw_url = f"https://raw.githubusercontent.com/{route['owner']}/{route['repo']}/{route['ref']}/{route['path']}"
            r = await client.get(raw_url)
            if r.status_code == 200:
                return r.text
            # Fall back to contents API (returns base64)
            import base64
            api_url = f"{base}/repos/{route['owner']}/{route['repo']}/contents/{route['path']}?ref={route['ref']}"
            r = await client.get(api_url)
            r.raise_for_status()
            data = r.json()
            if isinstance(data, dict) and data.get("encoding") == "base64":
                return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
            return _to_toon(data)

        if op == "tree":
            api_url = f"{base}/repos/{route['owner']}/{route['repo']}/git/trees/{route['ref']}?recursive=1"
            r = await client.get(api_url)
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
            r = await client.get(f"{base}/repos/{route['owner']}/{route['repo']}")
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
                rr = await client.get(f"{base}/repos/{route['owner']}/{route['repo']}/readme")
                if rr.status_code == 200:
                    import base64 as _b64
                    rd = rr.json()
                    readme = _b64.b64decode(rd["content"]).decode("utf-8", errors="replace")
                    lines += ["", "## README", readme[:4000]]
            except Exception:
                pass
            return "\n".join(lines)

        if op == "issue":
            r = await client.get(f"{base}/repos/{route['owner']}/{route['repo']}/issues/{route['number']}")
            r.raise_for_status()
            d = r.json()
            lines = [
                f"# Issue #{d['number']}: {d['title']}",
                f"State: {d['state']}  Author: {d['user']['login']}",
                "",
                d.get("body") or "(no body)",
            ]
            # Comments
            cr = await client.get(f"{base}/repos/{route['owner']}/{route['repo']}/issues/{route['number']}/comments?per_page=20")
            if cr.status_code == 200:
                for c in cr.json():
                    lines += ["", f"--- @{c['user']['login']} ---", c.get("body") or ""]
            return "\n".join(lines)

        if op == "issues":
            r = await client.get(
                f"{base}/repos/{route['owner']}/{route['repo']}/issues",
                params={"state": route.get("state", "open"), "per_page": 30},
            )
            r.raise_for_status()
            items = [
                {"number": i["number"], "state": i["state"], "title": i["title"], "author": i["user"]["login"]}
                for i in r.json() if "pull_request" not in i
            ]
            return f"## Issues ({route.get('state', 'open')})\n" + _to_toon(items)

        if op == "pr":
            r = await client.get(f"{base}/repos/{route['owner']}/{route['repo']}/pulls/{route['number']}")
            r.raise_for_status()
            d = r.json()
            lines = [
                f"# PR #{d['number']}: {d['title']}",
                f"State: {d['state']}  Author: {d['user']['login']}",
                f"Base: {d['base']['ref']} <- Head: {d['head']['ref']}",
                "",
                d.get("body") or "(no body)",
            ]
            # Review comments
            cr = await client.get(f"{base}/repos/{route['owner']}/{route['repo']}/pulls/{route['number']}/comments?per_page=20")
            if cr.status_code == 200:
                for c in cr.json():
                    lines += ["", f"--- @{c['user']['login']} on `{c.get('path','')}` ---", c.get("body") or ""]
            return "\n".join(lines)

        if op == "prs":
            r = await client.get(
                f"{base}/repos/{route['owner']}/{route['repo']}/pulls",
                params={"state": route.get("state", "open"), "per_page": 30},
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
            r = await client.get(f"{base}/repos/{route['owner']}/{route['repo']}/commits", params=params)
            r.raise_for_status()
            items = [
                {"sha": c["sha"][:8], "message": c["commit"]["message"].splitlines()[0][:80], "author": c["commit"]["author"]["name"]}
                for c in r.json()
            ]
            return "## Commits\n" + _to_toon(items)

        if op == "releases":
            r = await client.get(f"{base}/repos/{route['owner']}/{route['repo']}/releases?per_page=10")
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
            return r.text
    except Exception as exc:
        logger.debug("%s failed: %s", name, exc)
    return None


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
                logger.warning("GitHub API fetch failed for %s: %s: %s", url, type(exc).__name__, exc)

    async with httpx.AsyncClient(
        timeout=_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": _USER_AGENT},
    ) as client:
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
            logger.warning("HTTP fetch failed for %s: %s", fetch_url, exc)

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
