"""Strict, data-grounded grading + lessons distillation (Phase 2).

The PM run loads this morning's predictions plus any longer-horizon ones now due
(ledger.due_predictions), gathers the real outcome data for each (market.py for
prices, FRED for economic series), and grades every call right / wrong / partial
with a one-line *why* anchored to that data — never the model's own vibes. A
model grading its own homework must not be lenient: when the data doesn't clearly
confirm the call, it is not "right".

When grading surfaces misses, `distill_lessons` proposes concise, generalizable
rules and merges them into the (small, curated) lessons file the AM run reads.
"""

from __future__ import annotations

import datetime as _dt
import logging

from . import llm, market
from .ledger import Prediction

log = logging.getLogger(__name__)

VALID_STATUS = {"right", "wrong", "partial"}


# ── Outcome gathering ─────────────────────────────────────────────────────────

def _gather_outcome(pred: Prediction) -> str:
    """Collect the real data a prediction should be graded against."""
    parts: list[str] = []
    if pred.ticker:
        move = (
            market.daily_move(pred.ticker)
            if pred.horizon == "same-day"
            else market.move_since(pred.ticker, pred.created_date)
        )
        parts.append(move.describe() if move else f"{pred.ticker}: price data unavailable")
    if pred.metric:
        parts.append(market.fred_latest(pred.metric) or f"FRED {pred.metric}: data unavailable")
    return " | ".join(parts) if parts else "(no anchorable market/FRED data — qualitative call)"


# ── Grading ───────────────────────────────────────────────────────────────────

def _grade_prompt(rows: list[dict]) -> str:
    lines = [
        "You are grading your own past predictions for a personal investing "
        "briefing. Be STRICT and DATA-GROUNDED. Anchor every verdict to the "
        "observed data provided — never to a hunch. If the data does not clearly "
        "confirm the call, it is NOT 'right'. Reward precision, punish vagueness.",
        "",
        "For each prediction return: status (right | wrong | partial), a one-line "
        "'outcome' stating the real numbers/facts observed, and a one-line 'why' "
        "justifying the verdict against those numbers.",
        "- 'right': the data confirms the call (correct direction AND any stated "
        "magnitude/threshold).",
        "- 'partial': direction right but magnitude/timing off, or only partly "
        "borne out.",
        "- 'wrong': the data contradicts the call, OR the call was too vague to "
        "verify (vagueness is a miss, not a pass).",
        "",
        "PREDICTIONS TO GRADE:",
    ]
    for r in rows:
        lines.append(
            f"### id={r['id']}\n"
            f"made: {r['created']} | horizon: {r['horizon']} | due: {r['due']}\n"
            f"item: {r['item']}\n"
            f"call: {r['call']}\n"
            f"observed data: {r['outcome_data']}"
        )
    lines.append(
        "\nReturn JSON only: "
        '{"grades": [{"id": "<id>", "status": "right|wrong|partial", '
        '"outcome": "<real data observed>", "why": "<one line>"}]}'
    )
    return "\n".join(lines)


def grade_due(
    due: list[Prediction],
    today: _dt.date | None = None,
) -> list[Prediction]:
    """Grade each due prediction in place against real data; return the graded list.

    Mutates and returns the Prediction objects (status/outcome/why/graded set).
    Degrades gracefully: an LLM failure leaves predictions open (ungraded) rather
    than fabricating verdicts.
    """
    today = today or _dt.date.today()
    if not due:
        return []

    rows = []
    for p in due:
        rows.append(
            {
                "id": p.id, "created": p.created, "horizon": p.horizon, "due": p.due,
                "item": p.item, "call": p.call, "outcome_data": _gather_outcome(p),
            }
        )

    try:
        raw = llm.complete_json(_grade_prompt(rows))
    except llm.LLMError as exc:
        log.warning("Grading failed (%s); predictions left open.", exc)
        return []

    grades = {g.get("id"): g for g in raw.get("grades", [])} if isinstance(raw, dict) else {}
    graded: list[Prediction] = []
    for p in due:
        g = grades.get(p.id)
        if not g:
            log.warning("No grade returned for %s; left open.", p.id)
            continue
        status = (g.get("status") or "").strip().lower()
        if status not in VALID_STATUS:
            log.warning("Invalid status %r for %s; left open.", status, p.id)
            continue
        p.status = status
        p.outcome = (g.get("outcome") or "").strip()
        p.why = (g.get("why") or "").strip()
        p.graded = today.isoformat()
        graded.append(p)

    log.info("Graded %d of %d due predictions.", len(graded), len(due))
    return graded


# ── Lessons distillation ──────────────────────────────────────────────────────

def distill_lessons(graded: list[Prediction], current_lessons: str) -> str | None:
    """Propose + merge concise rules from graded misses. Returns new text or None.

    Only misses/partials can teach a lesson, and the file must stay SMALL — so
    the model is told to merge, dedupe, and cut, not just append. Returns None
    when there is nothing worth changing (caller then leaves the file untouched).
    """
    misses = [p for p in graded if p.status in ("wrong", "partial")]
    if not misses:
        log.info("No misses this round; lessons file unchanged.")
        return None

    miss_lines = "\n".join(
        f"- [{p.status}] call: {p.call}\n  outcome: {p.outcome}\n  why: {p.why}"
        for p in misses
    )
    prompt = (
        "You curate a SMALL, high-signal lessons file for a personal investing "
        "briefing. It is read into every morning's prediction step, so every line "
        "must earn its place. Below are predictions that just missed, with why.\n\n"
        "Update the lessons file: distill any genuinely generalizable rule from "
        "these misses, MERGE with existing lessons (dedupe, sharpen, and DELETE "
        "anything stale or redundant). Keep it tight — aim for at most ~8 bullet "
        "rules total. If the misses teach nothing new and generalizable, return "
        "the existing file unchanged.\n\n"
        "Return the COMPLETE updated markdown file content (it will overwrite the "
        "file verbatim), starting with a '# Lessons' heading.\n\n"
        f"=== CURRENT LESSONS FILE ===\n{current_lessons}\n\n"
        f"=== RECENT MISSES ===\n{miss_lines}"
    )
    try:
        new_text = llm.complete(prompt)
    except llm.LLMError as exc:
        log.warning("Lessons distillation failed (%s); file unchanged.", exc)
        return None

    new_text = new_text.strip()
    # Tolerate a stray ```markdown fence or a short preamble before the heading:
    # slice from the first "# Lessons" we find so the file stays clean.
    if new_text.startswith("```"):
        new_text = new_text.strip("`")
        if new_text.lower().startswith("markdown"):
            new_text = new_text[len("markdown"):]
        new_text = new_text.strip()
    idx = new_text.lower().find("# lessons")
    if idx == -1:
        log.warning("Distilled lessons missing heading; file unchanged.")
        return None
    return new_text[idx:].strip()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    from .ledger import due_predictions

    due = due_predictions(_dt.date.today())
    print(f"{len(due)} predictions due today.")
    for p in grade_due(due):
        print(f"  [{p.status}] {p.call[:60]} — {p.outcome[:60]}")
