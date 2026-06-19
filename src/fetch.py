"""Source fetching: RSS feeds + FRED economic data (Phase 1).

Pulls from the sources in `config.toml`: AP News + Reuters (wires), Ars Technica
+ IEEE Spectrum (tech), and FRED series (economic data). Recency-first: every
list of items is sorted newest-first and capped, so the freshest stories survive
into curation.

Resilience: a dead feed, a placeholder URL, or a missing FRED key degrades
gracefully — that source is skipped and the run continues with whatever else is
available, rather than the whole briefing failing.
"""

from __future__ import annotations

import datetime as _dt
import logging
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

import feedparser

from . import config

log = logging.getLogger(__name__)
UTC = _dt.timezone.utc

# Recency-first knobs. Keep the candidate pool small but fresh — curation only
# needs ~3 finalists, so feeding it a tight, recent set is both cheaper and more
# aligned with the "recency first" principle.
MAX_PER_FEED = 12
MAX_AGE_DAYS = 4  # wire/tech stories older than this are dropped before curation


@dataclass
class Article:
    """A single candidate news item pulled from a feed.

    `summary` is the feed-provided blurb only — the full article text is fetched
    transiently in extract.py and never stored here.
    """

    title: str
    link: str
    source: str  # human label, e.g. "AP News", "Ars Technica"
    category: str  # "wire" | "tech"  (curation maps these onto the 3 pillars)
    published: _dt.datetime | None = None
    summary: str = ""

    @property
    def age_days(self) -> float | None:
        if self.published is None:
            return None
        return (_dt.datetime.now(tz=UTC) - self.published).total_seconds() / 86400


@dataclass
class EconSeries:
    """The latest reading of a FRED economic series, with its prior value."""

    series_id: str
    title: str
    latest_value: float
    latest_date: _dt.date
    prev_value: float | None = None

    @property
    def change(self) -> float | None:
        if self.prev_value is None:
            return None
        return self.latest_value - self.prev_value


@dataclass
class Sources:
    """Everything fetched for one run, grouped for the curator."""

    articles: list[Article] = field(default_factory=list)
    econ: list[EconSeries] = field(default_factory=list)


# ── RSS ─────────────────────────────────────────────────────────────────────

def _parse_published(entry) -> _dt.datetime | None:
    """Best-effort published datetime (UTC) from a feedparser entry."""
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            return _dt.datetime(*t[:6], tzinfo=UTC)
    return None


def _is_placeholder(url: str) -> bool:
    return not url or url.strip().upper().startswith("PLACEHOLDER")


def fetch_feed(url: str, source_label: str, category: str) -> list[Article]:
    """Fetch + normalize one RSS feed. Never raises — returns [] on any failure."""
    if _is_placeholder(url):
        log.info("Skipping %s: feed URL is still a placeholder.", source_label)
        return []
    try:
        parsed = feedparser.parse(url)
    except Exception as exc:  # feedparser rarely raises, but be safe
        log.warning("Failed to fetch %s (%s): %s", source_label, url, exc)
        return []

    if parsed.bozo and not parsed.entries:
        log.warning("Feed %s returned no usable entries (%s).", source_label, url)
        return []

    articles: list[Article] = []
    for entry in parsed.entries:
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or "").strip()
        if not title or not link:
            continue
        # Google News appends " - <Publisher>" to every title; for our site-scoped
        # wire feeds that just duplicates source_label. Strip it so headlines read clean.
        suffix = f" - {source_label}"
        if title.endswith(suffix):
            title = title[: -len(suffix)].strip()
        articles.append(
            Article(
                title=title,
                link=link,
                source=source_label,
                category=category,
                published=_parse_published(entry),
                summary=(entry.get("summary") or "").strip(),
            )
        )
    # Feeds publish newest-first; keep only the freshest slice per source so the
    # candidate pool stays tight (recency-first, and cheaper to curate over).
    articles = articles[:MAX_PER_FEED]
    log.info("%s: %d entries (capped at %d)", source_label, len(articles), MAX_PER_FEED)
    return articles


# Human labels for the feed keys in config.toml.
_WIRE_LABELS = {"ap_news": "AP News", "reuters": "Reuters"}
_TECH_LABELS = {"ars_technica": "Ars Technica", "ieee_spectrum": "IEEE Spectrum"}


def _iter_feed_urls(section: dict) -> list[tuple[str, str]]:
    """Flatten a config sources section into (url, key) pairs.

    Each value may be a single URL string or a list of URLs (the wires allow
    multiple generated feeds per service).
    """
    pairs: list[tuple[str, str]] = []
    for key, value in section.items():
        urls = value if isinstance(value, list) else [value]
        for url in urls:
            pairs.append((url, key))
    return pairs


def fetch_articles() -> list[Article]:
    """Fetch every configured wire + tech feed, newest-first, recency-filtered."""
    srcs = config.sources()
    articles: list[Article] = []

    for url, key in _iter_feed_urls(srcs.get("wires", {})):
        articles += fetch_feed(url, _WIRE_LABELS.get(key, key), "wire")
    for url, key in _iter_feed_urls(srcs.get("tech", {})):
        articles += fetch_feed(url, _TECH_LABELS.get(key, key), "tech")

    # Recency-first: drop stale items, then sort newest-first. Items with no
    # date sort last but are kept (a missing date shouldn't silently delete news).
    def sort_key(a: Article):
        return a.published or _dt.datetime.min.replace(tzinfo=UTC)

    fresh = [a for a in articles if (a.age_days is None or a.age_days <= MAX_AGE_DAYS)]
    fresh.sort(key=sort_key, reverse=True)
    log.info("Total candidate articles after recency filter: %d", len(fresh))
    return fresh


# ── FRED ────────────────────────────────────────────────────────────────────

def fetch_econ() -> list[EconSeries]:
    """Pull the latest reading of each configured FRED series.

    Skips entirely (returns []) if no FRED key is set, so the run still works
    without economic data configured.
    """
    api_key = config.get_secret("FRED_API_KEY")
    if not api_key:
        log.info("Skipping FRED: no FRED_API_KEY set.")
        return []

    series_ids = config.sources().get("economic", {}).get("fred_series", [])
    if not series_ids:
        return []

    try:
        from fredapi import Fred
    except ImportError:
        log.warning("fredapi not installed; skipping economic data.")
        return []

    fred = Fred(api_key=api_key)
    out: list[EconSeries] = []
    for sid in series_ids:
        try:
            data = fred.get_series(sid).dropna()
            if data.empty:
                continue
            info = fred.get_series_info(sid)
            latest_idx = data.index[-1]
            out.append(
                EconSeries(
                    series_id=sid,
                    title=str(info.get("title", sid)),
                    latest_value=float(data.iloc[-1]),
                    latest_date=latest_idx.date(),
                    prev_value=float(data.iloc[-2]) if len(data) > 1 else None,
                )
            )
        except Exception as exc:
            log.warning("FRED series %s failed: %s", sid, exc)
    log.info("FRED series fetched: %d", len(out))
    return out


def fetch_all() -> Sources:
    """Top-level fetch: all articles + all econ series for one run."""
    return Sources(articles=fetch_articles(), econ=fetch_econ())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    s = fetch_all()
    print(f"\n{len(s.articles)} articles, {len(s.econ)} econ series")
    for a in s.articles[:10]:
        when = a.published.date().isoformat() if a.published else "—"
        print(f"  [{a.source:13}] {when}  {a.title[:70]}")
    for e in s.econ:
        print(f"  [FRED {e.series_id}] {e.latest_value} on {e.latest_date}  ({e.title[:40]})")
