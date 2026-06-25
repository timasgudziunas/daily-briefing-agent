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

from . import config, llm, market
from .ledger import LessonEntry, Prediction

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


# ── Lessons update (two-file architecture) ────────────────────────────────────
#
# Single LLM call when there are new misses: distill new lessons + confirm existing
# ones + select the ~8 for the active view — all in one pass.
#
# The master log (lessons_log.json) is append-only: entries are added or updated
# (outcome_count / last_confirmed) but NEVER deleted. Evicting a lesson from the
# active view (lessons_active.md) does NOT remove it from the log.

def _update_lessons_prompt(
    misses: list[Prediction],
    log_entries: list[LessonEntry],
    today: _dt.date,
) -> str:
    sectors = ", ".join(config.sectors() or [])
    watchlist = ", ".join(config.watchlist() or [])
    lines = [
        "You are maintaining the lessons for a personal investing briefing. "
        "There are TWO files: a master log (append-only source of truth containing "
        "every lesson ever learned) and an active view (~8 lessons the AM Briefing "
        "reads before predicting). Your job: update the log and refresh the view.",
        "",
        "MASTER LOG (current entries, id | outcome_count | last_confirmed | text):",
    ]
    if log_entries:
        for e in log_entries:
            lines.append(f"  {e.id} | x{e.outcome_count} | {e.last_confirmed} | {e.text}")
    else:
        lines.append("  (empty — no lessons yet)")
    lines += [
        "",
        "RECENT MISSES (predictions that just resolved wrong or partial):",
    ]
    for p in misses:
        lines.append(
            f"  [{p.status}] horizon={p.horizon} | call: {p.call}\n"
            f"    outcome: {p.outcome} | why: {p.why}"
        )
    lines += [
        "",
        f"CONTEXT: sectors = {sectors} | watchlist = {watchlist} | today = {today}",
        "",
        "YOUR THREE TASKS:",
        "1. NEW lessons — for each miss, decide if it teaches a genuinely new, "
        "generalizable rule NOT already covered by the master log. If a very "
        "similar rule exists, choose CONFIRM instead — never append near-duplicates.",
        "2. CONFIRM — list IDs of existing log entries that are reinforced by "
        "today's misses (same failure mode, same theme). This raises their weight.",
        "3. ACTIVE VIEW — select up to 8 lessons for the active view from the "
        "UPDATED log (log + any new entries). Weight by: outcome_count (higher = "
        "battle-tested), recency of last_confirmed, relevance to current sectors/"
        "watchlist. Reference new lessons as NEW-0, NEW-1, … (their index in 'new').",
        "",
        "Return JSON only:",
        '{"new": [{"text": "one tight generalizable rule"}], '
        '"confirm": ["L0001"], '
        '"active_ids": ["L0003", "L0001", "NEW-0"]}',
        "Rules: 'new' may be empty. IDs in 'confirm' must exist in the log. "
        "'active_ids' may reference log IDs or NEW-N. Keep 'text' tight — one "
        "plain bullet the AM run can directly apply to the next prediction.",
    ]
    return "\n".join(lines)


def update_lessons(
    misses: list[Prediction],
    log_entries: list[LessonEntry],
    today: _dt.date | None = None,
) -> tuple[list[LessonEntry], str] | None:
    """Single LLM call: update the master log + render the fresh active view.

    Returns (updated_log_entries, active_markdown) ready to save, or None on
    any LLM/parse failure (caller leaves both files untouched in that case).
    Only call this when there are actual misses — the caller gates on that.
    """
    today = today or _dt.date.today()
    from .ledger import next_lesson_id

    prompt = _update_lessons_prompt(misses, log_entries, today)
    try:
        raw = llm.complete_json(prompt)
    except llm.LLMError as exc:
        log.warning("Lessons update LLM call failed (%s); files unchanged.", exc)
        return None

    if not isinstance(raw, dict):
        log.warning("Lessons update returned non-dict; files unchanged.")
        return None

    new_texts = [
        n.get("text", "").strip()
        for n in raw.get("new", [])
        if isinstance(n, dict) and n.get("text", "").strip()
    ]
    confirm_ids = set(str(c) for c in raw.get("confirm", []) if c)
    active_refs = [str(r) for r in raw.get("active_ids", []) if r]

    # Work on an in-memory copy — the caller saves if we succeed.
    updated = list(log_entries)
    existing_id_map = {e.id: e for e in updated}
    miss_source_ids = [p.id for p in misses]

    # 1. Confirm existing entries (increment count + update date + add sources).
    confirmed_count = 0
    for cid in confirm_ids:
        entry = existing_id_map.get(cid)
        if entry is None:
            log.warning("Lessons confirm references unknown ID %r; skipping.", cid)
            continue
        entry.outcome_count += 1
        entry.last_confirmed = today.isoformat()
        entry.sources = list(set(entry.sources + miss_source_ids))
        confirmed_count += 1

    # 2. Append genuinely new entries.
    new_entries: list[LessonEntry] = []
    for text in new_texts:
        e = LessonEntry(
            id=next_lesson_id(updated + new_entries),
            text=text,
            created=today.isoformat(),
            last_confirmed=today.isoformat(),
            sources=list(miss_source_ids),
            outcome_count=1,
        )
        new_entries.append(e)
    updated.extend(new_entries)

    # Map NEW-N references to real IDs now that we've assigned them.
    new_id_map = {f"NEW-{i}": e.id for i, e in enumerate(new_entries)}
    all_id_map = {e.id: e for e in updated}

    # 3. Resolve active_refs → entries → render active markdown.
    active_lines: list[str] = []
    seen_active: set[str] = set()
    for ref in active_refs:
        real_id = new_id_map.get(ref, ref)
        if real_id in seen_active:
            continue
        entry = all_id_map.get(real_id)
        if entry is None:
            log.warning("active_ids ref %r (%r) not found; skipping.", ref, real_id)
            continue
        active_lines.append(f"- {entry.text}")
        seen_active.add(real_id)

    if not active_lines:
        # Fallback: use top entries by outcome_count then recency.
        fallback = sorted(updated, key=lambda e: (e.outcome_count, e.last_confirmed), reverse=True)[:8]
        active_lines = [f"- {e.text}" for e in fallback]
        log.warning("active_ids empty or all invalid; using fallback selection (%d).", len(fallback))

    active_md = "# Active Lessons\n\n" + "\n".join(active_lines) + "\n"

    log.info(
        "Lessons update: %d new, %d confirmed, %d selected for active view.",
        len(new_entries), confirmed_count, len(active_lines),
    )
    return updated, active_md


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    from .ledger import due_predictions

    due = due_predictions(_dt.date.today())
    print(f"{len(due)} predictions due today.")
    for p in grade_due(due):
        print(f"  [{p.status}] {p.call[:60]} — {p.outcome[:60]}")
