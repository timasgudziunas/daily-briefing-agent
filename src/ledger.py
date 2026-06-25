"""Persistent state: ledger (JSON) + lessons (Markdown) — the system's memory.

The ledger is the source of truth: every prediction the AM run makes is appended
here, and the PM run grades them in place. The lessons file holds distilled,
generalizable rules — kept SMALL and high-signal, and read by the AM run before
it predicts.

PRIVACY: the real `data/ledger.json` and `data/lessons.md` are gitignored
(personal track record stays local). Only blank `*.example.*` templates are
committed. On first use, if a real file is missing it is created from its
template here, so a fresh checkout runs without manual setup.

Prediction schema (one entry in `ledger["predictions"]`):
    id       unique, e.g. "2026-06-19-am-0"
    created  ISO date the prediction was made
    run      "am" | "pm" (which run created it)
    item     short description of what the prediction is about (the headline)
    pillar   Politics | Technology | Economy | Market (for econ/price calls)
    call     the concrete, falsifiable claim being made
    horizon  one of the locked ladder values (see config: predictions.horizons)
    due      ISO date the call becomes gradable (created + horizon)
    ticker   optional — a stock/ETF symbol to anchor grading to a real price
    metric   optional — a FRED series id to anchor grading to real data
    rationale  the research-backed reasoning behind the call (kept for grading
               context and so future calls can learn from past reasoning)
    confidence integer 0-100: calibrated probability the call resolves correct
    confidence_rationale  one line on why that confidence level
    status   "open" | "right" | "wrong" | "partial"
    outcome  filled at grading: the real data observed
    why      filled at grading: the rationale for the verdict
    graded   ISO date graded, or null while open
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
LEDGER_PATH = DATA_DIR / "ledger.json"
LEDGER_TEMPLATE = DATA_DIR / "ledger.example.json"

# Two-file lessons architecture (Phase 4):
#   lessons_log.json    — append-only master log; every lesson ever learned; NEVER trimmed.
#   lessons_active.md   — curated active view (~8 lessons) that the AM Briefing ingests.
# The old lessons.md is kept for migration only (bootstrapped into lessons_active.md on first use).
LESSONS_LOG_PATH = DATA_DIR / "lessons_log.json"
LESSONS_LOG_TEMPLATE = DATA_DIR / "lessons_log.example.json"
ACTIVE_LESSONS_PATH = DATA_DIR / "lessons_active.md"
ACTIVE_LESSONS_TEMPLATE = DATA_DIR / "lessons_active.example.md"
_LEGACY_LESSONS_PATH = DATA_DIR / "lessons.md"  # migration source only

# The locked horizon ladder lives in config.toml; these are the deltas used to
# turn a horizon into a concrete "due" date. Kept here (not config) because they
# are the *meaning* of each label, not a tunable knob.
_MONTHS = {"1-month": 1, "1-quarter": 3, "6-months": 6, "1-year": 12}


@dataclass
class Prediction:
    """One prediction — see the module docstring for the field meanings."""

    id: str
    created: str
    run: str
    item: str
    pillar: str
    call: str
    horizon: str
    due: str
    ticker: str | None = None
    metric: str | None = None
    rationale: str = ""
    confidence: int | None = None
    confidence_rationale: str = ""
    status: str = "open"
    outcome: str = ""
    why: str = ""
    graded: str | None = None

    @property
    def created_date(self) -> _dt.date:
        return _dt.date.fromisoformat(self.created)

    @property
    def due_date(self) -> _dt.date:
        return _dt.date.fromisoformat(self.due)

    def is_due(self, on: _dt.date) -> bool:
        """True if this open prediction can be graded on/after `on`."""
        return self.status == "open" and self.due_date <= on


@dataclass
class LessonEntry:
    """One entry in the append-only lessons master log.

    The master log (lessons_log.json) is the source of truth — entries are only
    ADDED or UPDATED (outcome_count / last_confirmed), never deleted. The active
    view (lessons_active.md) is a curated ~8-lesson subset that the AM run reads.

    Fields:
        id              unique sequential key, e.g. "L0000"
        text            the lesson bullet (one tight, generalizable rule)
        created         ISO date first distilled
        last_confirmed  ISO date most recently reinforced by an outcome
        sources         ledger prediction IDs that support this lesson
        outcome_count   number of distinct graded outcomes supporting it
    """

    id: str
    text: str
    created: str
    last_confirmed: str
    sources: list  # list[str] — ledger prediction IDs
    outcome_count: int


# ── Horizon math ──────────────────────────────────────────────────────────────

def _add_months(date: _dt.date, months: int) -> _dt.date:
    """Add `months` to `date`, clamping the day to the target month's length."""
    month_index = date.month - 1 + months
    year = date.year + month_index // 12
    month = month_index % 12 + 1
    # Clamp day (e.g. Jan 31 + 1 month -> Feb 28/29).
    last_day = (_dt.date(year + (month == 12), (month % 12) + 1, 1) - _dt.timedelta(days=1)).day
    return _dt.date(year, month, min(date.day, last_day))


def due_date(created: _dt.date, horizon: str) -> _dt.date:
    """The date a prediction made on `created` at `horizon` becomes gradable."""
    if horizon == "same-day":
        return created
    if horizon == "1-week":
        return created + _dt.timedelta(days=7)
    if horizon in _MONTHS:
        return _add_months(created, _MONTHS[horizon])
    log.warning("Unknown horizon %r; treating as same-day.", horizon)
    return created


# ── Bootstrap ─────────────────────────────────────────────────────────────────

def _ensure_file(path: Path, template: Path) -> None:
    """Create `path` from `template` on first use (privacy bootstrap)."""
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if template.exists():
        shutil.copyfile(template, path)
        log.info("Bootstrapped %s from %s", path.name, template.name)
    else:  # template missing too — fall back to a sane empty default
        if path.suffix == ".json":
            path.write_text('{\n  "predictions": []\n}\n', encoding="utf-8")
        else:
            path.write_text("# Lessons\n", encoding="utf-8")
        log.info("Created empty %s (no template found).", path.name)


# ── Ledger I/O ────────────────────────────────────────────────────────────────

def load_ledger() -> list[Prediction]:
    """Load all predictions from the ledger (bootstrapping the file if missing)."""
    _ensure_file(LEDGER_PATH, LEDGER_TEMPLATE)
    raw = json.loads(LEDGER_PATH.read_text(encoding="utf-8") or "{}")
    out: list[Prediction] = []
    for d in raw.get("predictions", []):
        # Tolerate extra/missing keys so the schema can evolve without breaking.
        known = {k: d.get(k) for k in Prediction.__dataclass_fields__}
        out.append(Prediction(**known))
    return out


def save_ledger(predictions: list[Prediction]) -> None:
    """Write the full prediction list back to the ledger (atomic-ish replace)."""
    _ensure_file(LEDGER_PATH, LEDGER_TEMPLATE)
    payload = {"predictions": [asdict(p) for p in predictions]}
    tmp = LEDGER_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(LEDGER_PATH)
    log.info("Ledger saved: %d predictions.", len(predictions))


def next_id(existing: list[Prediction], created: _dt.date, run: str) -> str:
    """A unique, readable id for a new prediction: `<date>-<run>-<n>`."""
    prefix = f"{created.isoformat()}-{run}-"
    n = sum(1 for p in existing if p.id.startswith(prefix))
    return f"{prefix}{n}"


def append_predictions(new: list[Prediction]) -> list[Prediction]:
    """Append predictions to the ledger and return the full updated list."""
    if not new:
        return load_ledger()
    all_preds = load_ledger()
    all_preds.extend(new)
    save_ledger(all_preds)
    return all_preds


def due_predictions(on: _dt.date, predictions: list[Prediction] | None = None) -> list[Prediction]:
    """Open predictions whose horizon has come due on/before `on`."""
    preds = load_ledger() if predictions is None else predictions
    return [p for p in preds if p.is_due(on)]


def track_record(limit: int = 25, predictions: list[Prediction] | None = None) -> list[Prediction]:
    """The most recent *graded* predictions (right/wrong/partial), newest first.

    Fed into the AM prediction step so the agent can learn from how its past
    calls actually resolved — and calibrate confidence against its real hit rate.
    """
    preds = load_ledger() if predictions is None else predictions
    graded = [p for p in preds if p.status in ("right", "wrong", "partial")]
    graded.sort(key=lambda p: p.graded or "", reverse=True)
    return graded[:limit]


def update_predictions(graded: list[Prediction]) -> list[Prediction]:
    """Persist graded predictions back into the ledger, matched by id."""
    by_id = {p.id: p for p in graded}
    all_preds = load_ledger()
    for i, p in enumerate(all_preds):
        if p.id in by_id:
            all_preds[i] = by_id[p.id]
    save_ledger(all_preds)
    return all_preds


# ── Lessons I/O (two-file architecture) ──────────────────────────────────────
#
# Master log  (lessons_log.json)   — append-only; every lesson ever learned.
# Active view (lessons_active.md)  — curated ~8-lesson subset; what AM ingests.
#
# Bootstrap order for lessons_active.md:
#   1. Use existing lessons_active.md (normal case).
#   2. Migrate from legacy lessons.md if present (first run after the upgrade).
#   3. Copy from the blank template.
#   4. Write an empty placeholder.

def _ensure_active_lessons() -> None:
    if ACTIVE_LESSONS_PATH.exists():
        return
    ACTIVE_LESSONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    if _LEGACY_LESSONS_PATH.exists():
        content = _LEGACY_LESSONS_PATH.read_text(encoding="utf-8")
        ACTIVE_LESSONS_PATH.write_text(content, encoding="utf-8")
        log.info("Migrated lessons.md -> lessons_active.md")
    elif ACTIVE_LESSONS_TEMPLATE.exists():
        shutil.copyfile(ACTIVE_LESSONS_TEMPLATE, ACTIVE_LESSONS_PATH)
        log.info("Bootstrapped %s from template.", ACTIVE_LESSONS_PATH.name)
    else:
        ACTIVE_LESSONS_PATH.write_text("# Active Lessons\n", encoding="utf-8")
        log.info("Created empty %s.", ACTIVE_LESSONS_PATH.name)


def read_active_lessons() -> str:
    """Return the active lessons text (the ~8-lesson curated view).

    This is the only thing the AM run reads before predicting — keep it tight.
    """
    _ensure_active_lessons()
    return ACTIVE_LESSONS_PATH.read_text(encoding="utf-8")


def write_active_lessons(text: str) -> None:
    """Overwrite the active lessons view with freshly curated `text`."""
    _ensure_active_lessons()
    ACTIVE_LESSONS_PATH.write_text(text.rstrip() + "\n", encoding="utf-8")
    log.info("Active lessons view updated (%d chars).", len(text))


def load_lessons_log() -> list[LessonEntry]:
    """Load all entries from the append-only lessons master log."""
    _ensure_file(LESSONS_LOG_PATH, LESSONS_LOG_TEMPLATE)
    raw = json.loads(LESSONS_LOG_PATH.read_text(encoding="utf-8") or "{}")
    out: list[LessonEntry] = []
    for d in raw.get("lessons", []):
        out.append(LessonEntry(
            id=d.get("id", ""),
            text=d.get("text", ""),
            created=d.get("created", ""),
            last_confirmed=d.get("last_confirmed", ""),
            sources=d.get("sources") or [],
            outcome_count=int(d.get("outcome_count") or 0),
        ))
    return out


def save_lessons_log(entries: list[LessonEntry]) -> None:
    """Write the full lessons log back (atomic-ish replace).

    This is the ONLY write path for the master log — always pass the complete list.
    """
    _ensure_file(LESSONS_LOG_PATH, LESSONS_LOG_TEMPLATE)
    payload = {"lessons": [asdict(e) for e in entries]}
    tmp = LESSONS_LOG_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(LESSONS_LOG_PATH)
    log.info("Lessons log saved: %d entries.", len(entries))


def next_lesson_id(existing: list[LessonEntry]) -> str:
    """A sequential, zero-padded lesson ID: L0000, L0001, …"""
    return f"L{len(existing):04d}"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    preds = load_ledger()
    print(f"{len(preds)} predictions in ledger.")
    for p in preds[-5:]:
        print(f"  [{p.status}] {p.horizon:9} due {p.due}  {p.call[:70]}")
    log_entries = load_lessons_log()
    print(f"\nLessons log: {len(log_entries)} entries.")
    for e in log_entries[-5:]:
        print(f"  [{e.id}] x{e.outcome_count}  {e.text[:70]}")
    print(f"\nActive lessons: {len(read_active_lessons())} chars.")
