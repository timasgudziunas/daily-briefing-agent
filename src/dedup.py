"""Story de-duplication: rolling log of recently-sent story URLs and titles.

Keeps a 7-day rolling window in data/seen.json (gitignored — local only) so the
curation SELECT prompt can skip stories already sent in recent days. Updated after
each real send (not --no-send preview runs).

All I/O is best-effort: a corrupt or missing seen.json just means no dedup
context is injected — the run continues cleanly.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
SEEN_PATH = ROOT / "data" / "seen.json"
MAX_AGE_DAYS = 7  # rolling window; older entries are expired on each load


def load_seen() -> list[dict]:
    """Load the rolling seen list, expiring entries older than MAX_AGE_DAYS."""
    if not SEEN_PATH.exists():
        return []
    try:
        data = json.loads(SEEN_PATH.read_text(encoding="utf-8"))
        cutoff = _dt.date.today() - _dt.timedelta(days=MAX_AGE_DAYS)
        return [
            e for e in data.get("seen", [])
            if _dt.date.fromisoformat(e.get("date", "1970-01-01")) >= cutoff
        ]
    except Exception as exc:
        log.warning("Could not load %s (%s); deduplication state cleared.", SEEN_PATH.name, exc)
        return []


def save_seen(entries: list[dict]) -> None:
    """Persist the seen list (atomic-ish replace)."""
    try:
        SEEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = SEEN_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"seen": entries}, indent=2) + "\n", encoding="utf-8")
        tmp.replace(SEEN_PATH)
    except Exception as exc:
        log.warning(
            "Could not save %s (%s); dedup state will not persist.", SEEN_PATH.name, exc
        )


def mark_seen(urls: list[str], titles: list[str]) -> None:
    """Append newly-sent items to the rolling log; expire stale entries.

    Only appends URLs not already in the window (idempotent on duplicates).
    """
    if not urls:
        return
    entries = load_seen()
    today = _dt.date.today().isoformat()
    existing_urls = {e.get("url", "") for e in entries}
    added = 0
    for url, title in zip(urls, titles):
        if url and url not in existing_urls:
            entries.append({"url": url, "title": title, "date": today})
            existing_urls.add(url)
            added += 1
    save_seen(entries)
    log.info(
        "Dedup: marked %d new item(s) seen (rolling window: %d total).", added, len(entries)
    )


def seen_context() -> str:
    """Text block of recently-sent headlines for injection into a SELECT prompt.

    Returns an empty string if nothing has been seen yet (first run or empty window).
    """
    entries = load_seen()
    if not entries:
        return ""
    lines = [
        "RECENTLY-SENT STORIES — skip any candidate that is the same story or "
        "essentially the same angle as one of these:"
    ]
    for e in entries:
        lines.append(f"  - [{e.get('date', '?')}] {e.get('title', '(untitled)')}")
    return "\n".join(lines)
