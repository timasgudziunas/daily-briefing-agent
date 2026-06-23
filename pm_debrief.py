"""PM Debrief entry point (run in the evening, trading days only).

Daily loop (see CLAUDE.md "Architecture"):
    load this morning's predictions (+ long-horizon ones now due)
    -> fetch market/data outcomes -> grade strictly -> write verdicts + lessons
    -> build market wrap + ~2 items + learning piece -> send email -> archive.

The PM run is the half of the loop that makes the system improve: it grades the
AM's calls against real data and distills misses into lessons the next AM run
reads before predicting.

Usage:
    python pm_debrief.py                 # gate, grade, learn, build, send, archive
    python pm_debrief.py --no-send       # build + archive + local HTML preview, no send
    python pm_debrief.py --force         # run even on a non-trading day (hand-testing)
    python pm_debrief.py --to a@b.com    # override recipient (default: send to self)
"""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import sys
import webbrowser
from pathlib import Path

from src import calendar as trading_calendar
from src import debrief as debriefing
from src import email as mailer
from src import fetch
from src import grade
from src import ledger

log = logging.getLogger("pm_debrief")

ROOT = Path(__file__).resolve().parent
ARCHIVE_DIR = ROOT / "data" / "archive"
PREVIEW_PATH = ARCHIVE_DIR / "_preview-pm.html"  # gitignored, for --no-send
LOG_DIR = ROOT / "data" / "logs"


def _setup_logging() -> None:
    """Console + rotating file logging so every scheduled run is auditable."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")

    console = logging.StreamHandler()
    console.setFormatter(fmt)

    file_h = logging.handlers.RotatingFileHandler(
        LOG_DIR / "pm.log", maxBytes=500_000, backupCount=5, encoding="utf-8"
    )
    file_h.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(console)
    root.addHandler(file_h)


def _archive(deb: debriefing.Debrief, subject: str) -> Path:
    """Write the sent debrief to data/archive/YYYY-MM-DD-pm.md (gitignored)."""
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    path = ARCHIVE_DIR / f"{deb.date.isoformat()}-pm.md"
    body = f"# {subject}\n\n{mailer.render_debrief_text(deb)}\n"
    path.write_text(body, encoding="utf-8")
    log.info("Archived to %s", path)
    return path


def run(no_send: bool = False, force: bool = False, to: str | None = None) -> int:
    today = trading_calendar.today_eastern()

    # Trading-day gate — only run on days the US market is open.
    if not force and not trading_calendar.is_trading_day(today):
        log.info("%s is not an NYSE trading day — nothing to send. Exiting.", today)
        return 0

    # 1. Grade every prediction that has come due, against real data.
    due = ledger.due_predictions(today)
    log.info("Grading %d due predictions…", len(due))
    graded = grade.grade_due(due, today=today)
    if graded:
        ledger.update_predictions(graded)

    # 2. Distill any misses into the (small, curated) lessons file.
    new_lessons = grade.distill_lessons(graded, ledger.read_lessons())
    if new_lessons:
        ledger.write_lessons(new_lessons)
        log.info("Lessons file updated from today's misses.")

    # 3. Market/econ data for the summary, plus the general-interest feeds that
    #    feed the "Something New" nightly learning piece (fetched separately so the
    #    AM run, which never uses them, stays fast).
    log.info("Fetching sources…")
    sources = fetch.fetch_all()
    learning_candidates = fetch.fetch_learning()

    log.info("Composing debrief…")
    deb = debriefing.compose_debrief(
        sources, graded, learning_candidates=learning_candidates, today=today
    )

    # Guard against a gutted debrief: if both LLM-composed sections (market wrap
    # + "Something New") failed AND nothing came due to grade, the email would be
    # nothing but a bare price table. That's a broken run, not a quiet one — fail
    # loudly rather than ship it. (A scorecard OR a market wrap OR a learning
    # piece is enough real content to be worth sending; the moves grid alone is
    # not.) Mirrors the AM run's "don't send an empty briefing" guard.
    if not (deb.grades or deb.market_wrap or deb.learning):
        log.error(
            "PM Debrief has no scorecard, market wrap, or learning piece — the "
            "LLM steps likely failed and nothing came due. Not sending a gutted "
            "debrief (only the price table would remain)."
        )
        return 1

    subject, html = mailer.build_pm_html(deb)

    if no_send:
        PREVIEW_PATH.parent.mkdir(parents=True, exist_ok=True)
        PREVIEW_PATH.write_text(html, encoding="utf-8")
        log.info("--no-send: wrote preview to %s", PREVIEW_PATH)
        try:
            _archive(deb, subject)
        except Exception:
            log.warning("Archive write failed; preview was written but no archive record.")
        try:
            webbrowser.open(PREVIEW_PATH.as_uri())
        except Exception:
            pass
        print(f"\nSubject: {subject}\nPreview: {PREVIEW_PATH}")
        return 0

    log.info("Sending…")
    mailer.send_email(subject, html, text=mailer.render_debrief_text(deb), to=to)
    print(f"Sent: {subject}")

    try:
        _archive(deb, subject)
    except Exception:
        log.warning("Archive write failed — email was sent but no archive record created.")

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Send the PM Debrief.")
    parser.add_argument("--no-send", action="store_true",
                        help="Build + archive + write a local HTML preview; do not send.")
    parser.add_argument("--force", action="store_true",
                        help="Run even on a non-trading day (hand-testing).")
    parser.add_argument("--to", default=None, help="Override recipient email.")
    args = parser.parse_args()

    _setup_logging()
    log.info("=== PM Debrief starting ===")
    try:
        code = run(no_send=args.no_send, force=args.force, to=args.to)
        if code == 0:
            log.info("=== PM Debrief completed successfully ===")
        else:
            log.warning("=== PM Debrief completed with exit code %d ===", code)
        sys.exit(code)
    except Exception:
        log.exception("=== PM Debrief run FAILED ===")
        sys.exit(1)


if __name__ == "__main__":
    main()
