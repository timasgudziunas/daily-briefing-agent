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
import logging.handlers
import sys
import webbrowser
from pathlib import Path

from src import calendar as trading_calendar
from src import curate as curation
from src import dedup
from src import email as mailer
from src import fetch
from src import ledger
from src import predict

log = logging.getLogger("am_briefing")

ROOT = Path(__file__).resolve().parent
ARCHIVE_DIR = ROOT / "data" / "archive"
PREVIEW_PATH = ROOT / "data" / "archive" / "_preview-am.html"  # gitignored, for --no-send
LOG_DIR = ROOT / "data" / "logs"


def _setup_logging() -> None:
    """Console + rotating file logging so every scheduled run is auditable."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")

    console = logging.StreamHandler()
    console.setFormatter(fmt)

    file_h = logging.handlers.RotatingFileHandler(
        LOG_DIR / "am.log", maxBytes=500_000, backupCount=5, encoding="utf-8"
    )
    file_h.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(console)
    root.addHandler(file_h)


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

    # Phase 2: read the curated active lessons view, then predict + append to ledger.
    # Prediction step is best-effort — a failure here still sends the briefing.
    log.info("Predicting…")
    lessons = ledger.read_active_lessons()
    predict.make_predictions(briefing, lessons_text=lessons, today=today, run="am")

    subject, html = mailer.build_html(briefing)

    if no_send:
        PREVIEW_PATH.parent.mkdir(parents=True, exist_ok=True)
        PREVIEW_PATH.write_text(html, encoding="utf-8")
        log.info("--no-send: wrote preview to %s", PREVIEW_PATH)
        try:
            _archive(briefing, subject)
        except Exception:
            log.warning("Archive write failed; preview was written but no archive record.")
        try:
            webbrowser.open(PREVIEW_PATH.as_uri())
        except Exception:
            pass
        print(f"\nSubject: {subject}\nPreview: {PREVIEW_PATH}")
        return 0

    log.info("Sending…")
    mailer.send_email(subject, html, text=mailer.render_digest_text(briefing), to=to)
    print(f"Sent: {subject}")

    # Mark sent stories as seen so future curation passes skip them.
    dedup.mark_seen(
        [item.link for item in briefing.items],
        [item.headline for item in briefing.items],
    )

    try:
        _archive(briefing, subject)
    except Exception:
        log.warning("Archive write failed — email was sent but no archive record created.")

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Send the AM Briefing.")
    parser.add_argument("--no-send", action="store_true",
                        help="Build + archive + write a local HTML preview; do not send.")
    parser.add_argument("--force", action="store_true",
                        help="Run even on a non-trading day (hand-testing).")
    parser.add_argument("--to", default=None, help="Override recipient email.")
    args = parser.parse_args()

    _setup_logging()
    log.info("=== AM Briefing starting ===")
    try:
        code = run(no_send=args.no_send, force=args.force, to=args.to)
        if code == 0:
            log.info("=== AM Briefing completed successfully ===")
        else:
            log.warning("=== AM Briefing completed with exit code %d ===", code)
        sys.exit(code)
    except Exception:
        log.exception("=== AM Briefing run FAILED ===")
        sys.exit(1)


if __name__ == "__main__":
    main()
