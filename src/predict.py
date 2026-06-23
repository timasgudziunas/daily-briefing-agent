"""Prediction + horizon logic (Phase 2).

For each AM item the agent makes one or two concrete, *gradable* calls. Before
committing, it (1) does live web research to verify facts and gather the most
current context, and (2) reads its own track record — how past calls actually
resolved — plus the distilled lessons. Each call is therefore research-backed and
track-record-aware, not a one-shot guess.

Every call carries:
  - a SHORT, plain, falsifiable claim (the `call` itself — no embedded reasoning),
  - the best-fit horizon from the locked ladder,
  - a `ticker`/`metric` anchor where possible (so the PM run grades against real
    data), the research `rationale`,
  - and a calibrated numeric `confidence` (0-100) with a one-line justification —
    meaningful, tied to evidence strength + base rates + the agent's real hit rate.

Calls become ledger.Prediction records (appended to the ledger) and a short
curate.Call display view is attached to each item for the email.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging

from . import config, ledger, llm
from .curate import Briefing, Call, Item

log = logging.getLogger(__name__)

# Allow at most this many predictions per item (decision: "one or two").
MAX_PER_ITEM = 2
# The prediction step is a small research agent — give it web tools and room.
RESEARCH_TOOLS = ["WebSearch", "WebFetch"]
RESEARCH_TIMEOUT = 600  # seconds; web research over several items is slow


def _track_record_block(record: list[ledger.Prediction]) -> str:
    if not record:
        return (
            "TRACK RECORD: none yet — you have no graded calls to learn from. Until "
            "a record exists, be CONSERVATIVE with confidence (don't exceed ~70 "
            "without strong, verified evidence)."
        )
    rights = sum(1 for p in record if p.status == "right")
    partials = sum(1 for p in record if p.status == "partial")
    total = len(record)
    hit = (rights + 0.5 * partials) / total * 100 if total else 0
    lines = [
        f"TRACK RECORD (your last {total} graded calls — {rights} right, "
        f"{partials} partial; ~{hit:.0f}% credit). LEARN from the misses and "
        "calibrate confidence to this real hit rate, not optimism:",
    ]
    for p in record:
        said = f", you said {p.confidence}%" if p.confidence is not None else ""
        lines.append(f"- [{p.status}] ({p.horizon}) {p.call}{said} -> {p.outcome or 'n/a'}")
    return "\n".join(lines)


def _predict_prompt(
    briefing: Briefing,
    lessons_text: str,
    record: list[ledger.Prediction],
    today: _dt.date,
) -> str:
    horizons = config.horizons()
    watchlist = ", ".join(config.watchlist())
    lines = [
        "You are the forecasting brain of a lean personal investing briefing. Make "
        "one or two concrete, falsifiable calls per item. Treat this as real "
        "research, not a guess.",
        "",
    ]
    lines += [
        "BEFORE you commit each call, DO THE WORK:",
        "1. RESEARCH with web search — verify the facts, pull the most current "
        "context (latest prices/levels, fresh developments, relevant base rates). "
        "Do NOT rely only on the snippet provided; confirm and update it.",
        "2. REVIEW your track record and lessons below — learn from past misses and "
        "do not repeat them; notice where you were over- or under-confident.",
        "",
        "CALL FORMAT — keep it STRAIGHTFORWARD:",
        "- 'call': ONE short, plain sentence. A single clear, falsifiable claim "
        "with an explicit direction and (where sensible) a threshold. NO embedded "
        "reasoning, NO hedging clauses, NO 'because...'. Plain English a busy "
        "reader gets in one glance.",
        "- Put the reasoning in 'rationale' (1-2 sentences), separate from the call.",
        f"- 'horizon': the single best fit from: {', '.join(horizons)}. Match it to "
        "the item (intraday/reaction news -> same-day/1-week; structural shifts -> "
        "1-month+).",
        "- Prefer ONE sharp call per item; add a second only if a different horizon "
        "genuinely adds signal. Never pad.",
        "- ANCHOR TO DATA: set 'ticker' to a symbol when the call is about a "
        f"stock/ETF/index (watchlist: {watchlist}; broad calls may use SPY, QQQ, "
        "USO, etc.). Set 'metric' to a FRED id for economic calls (e.g. CPIAUCSL, "
        "UNRATE, DGS10). Leave both null only when genuinely qualitative.",
        "",
        "CONFIDENCE — make it MEANINGFUL, not a label:",
        "- 'confidence': an integer 0-100 = your honest, calibrated probability the "
        "call resolves correct. ~50 = coin-flip. Reserve >75 for calls backed by "
        "strong, verified evidence. Reflect evidence strength, base rates, the "
        "horizon's uncertainty, AND your real track-record hit rate. Do NOT inflate.",
        "- 'confidence_rationale': one line on what drives that number.",
        "",
        _track_record_block(record),
        "",
    ]
    if lessons_text.strip():
        lines += ["LESSONS LEARNED SO FAR (apply these):", lessons_text.strip(), ""]
    lines.append("ITEMS:")
    for i, it in enumerate(briefing.items):
        kp = "; ".join(it.key_points)
        lines.append(
            f"[{i}] ({it.pillar}) {it.headline}\n"
            f"    key points: {kp}\n"
            f"    why it matters: {it.why_it_matters}"
        )
    lines.append(
        "\nWhen done researching, return JSON only (no prose): "
        '{"predictions": [{"item": 0, "horizon": "1-week", '
        '"call": "<short plain claim>", "rationale": "<1-2 sentences>", '
        '"ticker": "META" | null, "metric": "CPIAUCSL" | null, '
        '"confidence": 65, "confidence_rationale": "<one line>", '
        '"pillar": "Technology"}]}. '
        f"Use the [#] item index exactly. At most {MAX_PER_ITEM} predictions per item."
    )
    return "\n".join(lines)


def _clean_symbol(value) -> str | None:
    if not value or not isinstance(value, str):
        return None
    v = value.strip().upper()
    return v or None


def _clean_confidence(value) -> int | None:
    try:
        return max(0, min(100, int(round(float(value)))))
    except (TypeError, ValueError):
        return None


def _run_llm(prompt: str):
    """Research-backed call, with a tool-free fallback if web research fails."""
    try:
        return llm.complete_json(prompt, allowed_tools=RESEARCH_TOOLS, timeout=RESEARCH_TIMEOUT)
    except llm.LLMError as exc:
        log.warning("Research-backed prediction failed (%s); retrying without web tools.", exc)
        return llm.complete_json(prompt)


def make_predictions(
    briefing: Briefing,
    lessons_text: str = "",
    today: _dt.date | None = None,
    run: str = "am",
) -> list[ledger.Prediction]:
    """Research, then generate predictions for a briefing's items; append to ledger.

    Side effect: populates `item.predictions` (curate.Call views) for the email.
    Returns the new Prediction records (also persisted). Degrades gracefully — on
    any LLM/parse failure the briefing still sends, just without predictions.
    """
    today = today or _dt.date.today()
    if not briefing.items:
        return []

    existing = ledger.load_ledger()
    record = ledger.track_record(predictions=existing)
    try:
        raw = _run_llm(_predict_prompt(briefing, lessons_text, record, today))
    except llm.LLMError as exc:
        log.warning("Prediction step failed (%s); sending briefing without predictions.", exc)
        return []

    rows = raw.get("predictions", []) if isinstance(raw, dict) else []
    new: list[ledger.Prediction] = []
    per_item: dict[int, int] = {}

    for row in rows:
        try:
            idx = int(row.get("item"))
        except (TypeError, ValueError):
            continue
        if not (0 <= idx < len(briefing.items)):
            log.warning("Prediction references unknown item %r; skipping.", row.get("item"))
            continue
        if per_item.get(idx, 0) >= MAX_PER_ITEM:
            continue

        item: Item = briefing.items[idx]
        call = (row.get("call") or "").strip()
        horizon = (row.get("horizon") or "").strip()
        if not call or horizon not in config.horizons():
            log.warning("Dropping malformed prediction for item %d: %r", idx, row)
            continue

        confidence = _clean_confidence(row.get("confidence"))
        pred = ledger.Prediction(
            id=ledger.next_id(existing + new, today, run),
            created=today.isoformat(),
            run=run,
            item=item.headline,
            pillar=row.get("pillar") or item.pillar,
            call=call,
            horizon=horizon,
            due=ledger.due_date(today, horizon).isoformat(),
            ticker=_clean_symbol(row.get("ticker")),
            metric=_clean_symbol(row.get("metric")),
            rationale=(row.get("rationale") or "").strip(),
            confidence=confidence,
            confidence_rationale=(row.get("confidence_rationale") or "").strip(),
        )
        new.append(pred)
        per_item[idx] = per_item.get(idx, 0) + 1
        item.predictions.append(Call(horizon=horizon, call=call, confidence=confidence))

    if new:
        ledger.append_predictions(new)
        log.info("Appended %d research-backed predictions to the ledger.", len(new))
    return new


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    from .curate import curate
    from .fetch import fetch_all

    b = curate(fetch_all())
    preds = make_predictions(b, ledger.read_lessons())
    print(json.dumps([vars(p) for p in preds], indent=2))
