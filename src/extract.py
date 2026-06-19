"""Article content extraction (Phase 1).

For a curated finalist, fetch the *real* article body via `trafilatura` and
return a clean excerpt. That excerpt is raw material handed transiently to the
LLM, which distills the 2-3 key points that actually land in the email.

Copyright + the "preserve real articles, not lossy summaries" rule (CLAUDE.md):
the full article text is NEVER persisted or emitted — only the short excerpt
flows to the model in-memory, and only the model's key points + the source link
are kept. We also extract on the *finalists* only (not all candidates), so the
run stays fast and we don't hammer publishers.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.parse
import urllib.request

import trafilatura

log = logging.getLogger(__name__)

# Enough context for the model to pull accurate key points, short enough to stay
# well clear of reproducing the article.
EXCERPT_CHARS = 2000

# Google News (used for the AP/Reuters wires) hands out encoded redirect links
# like https://news.google.com/rss/articles/CBMi... instead of the real article
# URL. trafilatura can't extract from those, and we want the *real* source link
# in the email anyway — so resolve them. Resolution runs on finalists only, so
# it's a handful of calls per run.
_GNEWS_HOST = "news.google.com"
_UA = {"User-Agent": "Mozilla/5.0"}
_BATCHEXECUTE = "https://news.google.com/_/DotsSplashUi/data/batchexecute"


def resolve_link(url: str, timeout: int = 20) -> str:
    """Resolve a Google News redirect link to the real article URL.

    Returns the original `url` unchanged when it isn't a Google News link or when
    resolution fails — callers always get a usable URL and the run degrades
    gracefully (extraction then falls back to the feed summary).
    """
    if _GNEWS_HOST not in url:
        return url
    try:
        # Step 1: the article page carries the id/signature/timestamp needed to
        # ask Google for the underlying URL.
        req = urllib.request.Request(url, headers=_UA)
        html = urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "ignore")
        aid = re.search(r'data-n-a-id="([^"]+)"', html)
        sig = re.search(r'data-n-a-sg="([^"]+)"', html)
        ts = re.search(r'data-n-a-ts="([^"]+)"', html)
        if not (aid and sig and ts):
            log.warning("resolve_link: no signature in %s", url)
            return url

        # Step 2: Google's batchexecute endpoint returns the real URL.
        inner = json.dumps(
            ["garturlreq", [["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1,
                             None, None, None, None, None, 0, 1],
                            "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0],
             aid.group(1), ts.group(1), sig.group(1)]
        )
        payload = [[["Fbv4je", inner]]]
        body = "f.req=" + urllib.parse.quote(json.dumps(payload))
        breq = urllib.request.Request(
            _BATCHEXECUTE,
            data=body.encode(),
            headers={**_UA, "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
        )
        raw = urllib.request.urlopen(breq, timeout=timeout).read().decode("utf-8", "ignore")
        m = re.search(r'garturlres.*?(https?://[^\\"]+)', raw)
        if m:
            return m.group(1)
        log.warning("resolve_link: no URL in batchexecute response for %s", url)
    except Exception as exc:
        log.warning("resolve_link: failed on %s: %s", url, exc)
    return url


def extract_excerpt(url: str, max_chars: int = EXCERPT_CHARS) -> str | None:
    """Return a clean text excerpt of the article at `url`, or None on failure.

    Never raises — a fetch/parse failure logs and returns None so the caller can
    fall back to the feed summary.
    """
    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            log.warning("extract: could not fetch %s", url)
            return None
        text = trafilatura.extract(
            downloaded,
            include_comments=False,
            include_tables=False,
            favor_precision=True,
        )
    except Exception as exc:
        log.warning("extract: failed on %s: %s", url, exc)
        return None

    if not text:
        return None
    text = " ".join(text.split())  # collapse whitespace
    if len(text) > max_chars:
        text = text[:max_chars].rsplit(" ", 1)[0] + "…"
    return text


def _strip_html(text: str) -> str:
    """Crude tag strip for feed summaries (e.g. Google News' `<a href=…>` blurbs)
    so the model never sees raw markup. Good enough for short summary strings."""
    return " ".join(re.sub(r"<[^>]+>", " ", text).split())


def best_context(url: str, feed_summary: str = "") -> str:
    """Excerpt for the model, falling back to the feed summary if extraction fails.

    Guarantees a non-empty string when any context exists, so curation always has
    something to work from even for paywalled/blocked pages.
    """
    excerpt = extract_excerpt(url)
    if excerpt:
        return excerpt
    if feed_summary:
        return _strip_html(feed_summary)[:EXCERPT_CHARS]
    return ""
