"""PM Debrief content build (Phase 2).

The PM email's shape (see CLAUDE.md "Architecture"): open with the prediction
grades, then a Market Summary (overall direction + the day's notable moves —
indices, watchlist, gold, oil, yields, crypto), then a single "Something New"
nightly learning piece. Predictions are made in the AM run only — the PM run
grades, recaps, and teaches.

Unlike the AM Briefing, the PM run deliberately drops the Politics/Technology/
Economy article sections. The evening read is one genuinely fascinating story
from OUTSIDE markets and investing (science, history, engineering, psychology,
geography…), so the reader finishes every debrief having learned something they
almost certainly didn't know before — framed with a little context first, then
linked to the real article.

This module composes the *content*; grading lives in grade.py, persistence in
ledger.py, market data in market.py, and rendering/sending in email.py. The
market wrap is grounded in real same-session moves (market.py) plus the latest
econ readings; the learning piece is picked + distilled from the general-interest
feeds (config `[sources.learning]`, fetched via fetch.fetch_learning()).
"""

from __future__ import annotations

import datetime as _dt
import logging
from dataclasses import dataclass, field

from . import config, dedup, extract, llm, market
from .fetch import Article, Sources
from .ledger import Prediction

log = logging.getLogger(__name__)

# Cap the learning candidate pool handed to the selector (token budget).
_MAX_LEARNING_CANDIDATES = 25


@dataclass
class LearningPiece:
    """The PM "Something New" nightly teaching slot: context first, then the article."""

    title: str
    topic: str           # short tag, e.g. "History", "Astronomy", "Psychology"
    context: str         # 2-3 sentences of framing to read BEFORE the article
    key_points: list[str]
    link: str
    source: str


@dataclass
class Debrief:
    """A composed PM Debrief, ready to render."""

    date: _dt.date
    tldr: list[str] = field(default_factory=list)
    grades: list[Prediction] = field(default_factory=list)
    market_wrap: list[str] = field(default_factory=list)        # narrative bullets
    market_moves: list[market.SummaryRow] = field(default_factory=list)  # the grid
    learning: LearningPiece | None = None


# ── Grades + market context ──────────────────────────────────────────────────

def _grade_summary(grades: list[Prediction]) -> str:
    if not grades:
        return "(no predictions came due today)"
    counts: dict[str, int] = {}
    for g in grades:
        counts[g.status] = counts.get(g.status, 0) + 1
    tally = ", ".join(f"{n} {s}" for s, n in counts.items())
    lines = [f"Record today: {tally}."]
    for g in grades:
        lines.append(f"- [{g.status}] ({g.horizon}) {g.call} -> {g.outcome}")
    return "\n".join(lines)


def _wrap_tldr_prompt(moves_ctx: str, econ_ctx: str, grade_ctx: str) -> str:
    """Compact JSON call: market wrap + TL;DR only (kept small to avoid truncation)."""
    return "\n".join([
        "You are writing the top of a lean PM market debrief for a personal "
        "investor (watchlist: " + ", ".join(config.watchlist()) + "). Be tight, "
        "factual, non-repetitive. No filler, no hype.",
        "",
        "Produce:",
        "1. market_wrap: 2-3 bullets giving the day's OVERALL read — broad market "
        "direction and WHY, the notable watchlist/asset moves, and anything worth "
        "flagging (gold, oil, yields, crypto). Connect moves to causes; don't just "
        "restate every number — the reader sees the full table below. <= 28 words each.",
        "2. tldr: 2-3 ultra-short skim-back lines (scorecard + biggest move). <= 18 words each.",
        "",
        f"TODAY'S MARKET MOVES:\n{moves_ctx}",
        "",
        f"LATEST ECONOMIC READINGS:\n{econ_ctx or '(none)'}",
        "",
        f"PREDICTION GRADES TODAY:\n{grade_ctx}",
        "",
        'Return JSON only: {"market_wrap": ["...", "..."], "tldr": ["...", "..."]}',
    ])


# ── "Something New" learning piece ───────────────────────────────────────────

def _learning_select_prompt(candidates: list[Article]) -> str:
    """Pass 1 — pick the single most fascinating, genuinely-novel non-markets story."""
    lines = [
        "You are picking ONE story for the 'Something New' nightly learning slot in "
        "a personal investor's PM debrief. The entire point: the reader should finish "
        "having learned something they almost certainly did NOT know before.",
        "",
        "HARD RULES:",
        "- Topic MUST be OUTSIDE markets, investing, finance, business, and partisan "
        "politics. Think science, history, engineering, psychology, geography, nature, "
        "archaeology, space, mathematics.",
        "- Pick the single most surprising, genuinely-interesting item — not the most "
        "'important'. Avoid anything most educated people already know.",
        "- Prefer a self-contained marvel over breaking news; freshness does not matter "
        "here, fascination does.",
        "",
        "CANDIDATES:",
    ]
    for i, a in enumerate(candidates):
        summary = " ".join(a.summary.split())[:240]
        lines.append(f"[L{i}] ({a.source}) {a.title}\n    {summary}")
    seen = dedup.seen_context()
    if seen:
        lines.append(f"\n{seen}")

    lines.append(
        '\nReturn JSON: {"ref": "L3", "topic": "<one or two word tag, e.g. History, '
        'Astronomy, Psychology>", "reason": "<short>"}. Use the [L#] refs exactly.'
    )
    return "\n".join(lines)


def _learning_compose_prompt(headline: str, source: str, topic: str, context: str) -> str:
    """Pass 2 — write the framing 'what to know first' + the fascinating key points."""
    return "\n".join([
        f"Write the 'Something New' nightly learning piece about this {topic} story "
        "for a sharp, curious reader. Goal: they finish having learned something "
        "genuinely new and fascinating.",
        "",
        "Produce, grounded ONLY in the provided content:",
        "1. context: 2-3 sentences of essential background / what to know BEFORE "
        "reading the article, so the story lands. Plain prose, no fluff.",
        "2. key_points: 2-3 tight bullets carrying the genuinely surprising substance.",
        "",
        "Do NOT reproduce article text — distill. No markets/investing spin; just the "
        "wonder of the thing.",
        "",
        f"HEADLINE: {headline} ({source})",
        f"CONTENT:\n{context}",
        "",
        'Return JSON: {"context": "...", "key_points": ["...", "..."]}',
    ])


def compose_learning(candidates: list[Article]) -> LearningPiece | None:
    """Select one general-interest article and distill it into a LearningPiece.

    Returns None when there are no candidates. Raises llm.LLMError on model
    failure, which the caller isolates so the debrief still ships without it.
    """
    if not candidates:
        log.warning("No learning candidates fetched; PM ships without 'Something New'.")
        return None

    pool = candidates[:_MAX_LEARNING_CANDIDATES]
    selection = llm.complete_json(_learning_select_prompt(pool))
    ref = selection.get("ref") if isinstance(selection, dict) else None
    topic = (selection.get("topic") or "").strip() if isinstance(selection, dict) else ""

    idx = 0  # fall back to the freshest candidate if the ref is unusable
    if isinstance(ref, str) and ref.startswith("L") and ref[1:].isdigit():
        n = int(ref[1:])
        if 0 <= n < len(pool):
            idx = n
        else:
            log.warning("Learning selector returned out-of-range ref %r; using freshest.", ref)
    article = pool[idx]

    # Resolve + extract the real piece so the key points are grounded (not a guess).
    link = extract.resolve_link(article.link)
    content = extract.best_context(link, article.summary)

    composed = llm.complete_json(
        _learning_compose_prompt(article.title, article.source, topic or "fascinating", content)
    )
    context = (composed.get("context") or "").strip() if isinstance(composed, dict) else ""
    key_points = (
        [p.strip() for p in composed.get("key_points", []) if p.strip()]
        if isinstance(composed, dict) else []
    )
    return LearningPiece(
        title=article.title,
        topic=topic or "Something New",
        context=context,
        key_points=key_points or ["(details unavailable — open the full story)"],
        link=link,
        source=article.source,
    )


# ── Orchestration ────────────────────────────────────────────────────────────

def compose_debrief(
    sources: Sources,
    grades: list[Prediction],
    learning_candidates: list[Article] | None = None,
    today: _dt.date | None = None,
) -> Debrief:
    """Build the full PM Debrief: grades + market summary + a learning piece.

    Each content block is failure-isolated: a flaky LLM/market/feed call degrades
    that one section rather than sinking the whole debrief (which always ships at
    least the scorecard).
    """
    today = today or _dt.date.today()

    rows = market.summary_rows()
    moves_ctx = market.summary_context(rows)
    econ_ctx = "\n".join(
        f"{e.title}: {e.latest_value} on {e.latest_date}" for e in sources.econ
    )
    grade_ctx = _grade_summary(grades)

    tldr: list[str] = []
    market_wrap: list[str] = []
    try:
        extras = llm.complete_json(_wrap_tldr_prompt(moves_ctx, econ_ctx, grade_ctx))
        if isinstance(extras, dict):
            tldr = [t.strip() for t in extras.get("tldr", []) if t.strip()]
            market_wrap = [w.strip() for w in extras.get("market_wrap", []) if w.strip()]
    except llm.LLMError as exc:
        log.warning("PM wrap/TL;DR generation failed (%s); shipping moves table only.", exc)

    learning: LearningPiece | None = None
    try:
        learning = compose_learning(learning_candidates or [])
    except llm.LLMError as exc:
        log.warning("PM learning piece generation failed (%s); skipping it.", exc)

    return Debrief(
        date=today,
        tldr=tldr,
        grades=grades,
        market_wrap=market_wrap,
        market_moves=rows,
        learning=learning,
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    from .fetch import fetch_all, fetch_learning

    d = compose_debrief(fetch_all(), [], learning_candidates=fetch_learning())
    print("TL;DR:", d.tldr)
    print("WRAP:", d.market_wrap)
    print("MOVES:", [(r.label, r.change) for r in d.market_moves])
    if d.learning:
        print("LEARN:", d.learning.topic, "—", d.learning.title)
        print("  context:", d.learning.context[:120])
