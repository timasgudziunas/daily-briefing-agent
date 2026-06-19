"""AM Briefing entry point (run before market open, trading days only).

Daily loop (see CLAUDE.md "Architecture"):
    [Phase 2: read lessons] -> fetch news -> curate items
    -> [Phase 2: make predictions + append to ledger] -> send email -> archive.

Phase 1 scope: a real, well-formatted AM Briefing in the inbox. No predictions or
scheduling yet — those arrive in Phase 2/3.

Usage:
    python am_briefing.py                 # gate, curate, send, archive
    python am_briefing.py --no-send       # build + archive + write a local preview, no send
    python am_briefing.py --force         # run even on a non-trading day (hand-testing)
    python am_briefing.py --to a@b.com    # override recipient (default: send to self)
"""

from __future__ import annotations

import argparse
import datetime as _dt
import logging
import sys
import webbrowser
from pathlib import Path

from src import calendar as trading_calendar
from src import curate as curation
from src import email as mailer
from src import fetch

log = logging.getLogger("am_briefing")

ROOT = Path(__file__).resolve().parent
ARCHIVE_DIR = ROOT / "data" / "archive"
PREVIEW_PATH = ROOT / "data" / "archive" / "_preview-am.html"  # gitignored, for --no-send


def _archive(briefing: curation.Briefing, subject: str) -> Path:
    """Write the sent digest to data/archive/YYYY-MM-DD-am.md (gitignored, private).

    The archive is plain text/markdown — the durable record of what went out.
    """
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    path = ARCHIVE_DIR / f"{briefing.date.isoformat()}-am.md"
    body = f"# {subject}\n\n{mailer.render_digest_text(briefing)}\n"
    path.write_text(body, encoding="utf-8")
    log.info("Archived to %s", path)
    return path


def run(no_send: bool = False, force: bool = False, to: str | None = None) -> int:
    today = trading_calendar.today_eastern()

    # Trading-day gate — the agent only emails on days the US market is open.
    if not force and not trading_calendar.is_trading_day(today):
        log.info("%s is not an NYSE trading day — nothing to send. Exiting.", today)
        return 0

    log.info("Fetching sources…")
    sources = fetch.fetch_all()

    log.info("Curating…")
    briefing = curation.curate(sources, today=today)
    if not briefing.items:
        log.error("Curation produced no items; not sending an empty briefing.")
        return 1

    subject, html = mailer.build_html(briefing)
    _archive(briefing, subject)

    if no_send:
        PREVIEW_PATH.parent.mkdir(parents=True, exist_ok=True)
        PREVIEW_PATH.write_text(html, encoding="utf-8")
        log.info("--no-send: wrote preview to %s", PREVIEW_PATH)
        try:
            webbrowser.open(PREVIEW_PATH.as_uri())
        except Exception:
            pass
        print(f"\nSubject: {subject}\nPreview: {PREVIEW_PATH}")
        return 0

    log.info("Sending…")
    mailer.send_email(subject, html, text=mailer.render_digest_text(briefing), to=to)
    print(f"Sent: {subject}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Send the AM Briefing.")
    parser.add_argument("--no-send", action="store_true",
                        help="Build + archive + write a local HTML preview; do not send.")
    parser.add_argument("--force", action="store_true",
                        help="Run even on a non-trading day (hand-testing).")
    parser.add_argument("--to", default=None, help="Override recipient email.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        sys.exit(run(no_send=args.no_send, force=args.force, to=args.to))
    except Exception:
        log.exception("AM Briefing run failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
