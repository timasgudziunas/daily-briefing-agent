"""Curation: turn raw sources into a lean, well-formed AM Briefing (Phase 1).

Two LLM passes through the swappable `llm` interface:

  1. SELECT — from the candidate pool (wire + tech articles, FRED series), pick
     ~3 finalists across the three pillars (Politics / Technology / Economy),
     enforcing the leanness, no-filler, no-AI-slop and recency-first rules.
  2. COMPOSE — extract the real article body for each finalist (extract.py) and
     write its 2-3 key points + one-line "why it matters", plus a TL;DR for the
     whole email.

Phase 1 stops at "why it matters" — predictions are added in Phase 2. Only key
points + the source link are kept; full article text is never persisted.

Note: `curate.py` is a small structural addition beyond CLAUDE.md's listed
module set — it holds the "Curation prompt" Phase 1 step and keeps the
`am_briefing.py` orchestrator thin. The LLM transport still lives only in
`llm.py`.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
from dataclasses import dataclass, field

from . import config, extract, llm
from .fetch import Article, EconSeries, Sources

log = logging.getLogger(__name__)

PILLARS = ["Politics", "Technology", "Economy"]
TARGET_ITEMS = 3  # ~3 in the AM (CLAUDE.md leanness rule)


@dataclass
class Call:
    """A prediction as shown in the email: a short, plain, falsifiable claim with
    its horizon and a calibrated confidence. The full gradable record (rationale,
    ticker/metric, etc.) lives in the ledger; this is just the display view."""

    horizon: str
    call: str
    confidence: int | None = None


@dataclass
class Item:
    """One finished briefing item, ready to render."""

    pillar: str
    headline: str
    link: str
    source: str
    key_points: list[str]
    why_it_matters: str
    # Phase 2: one or two Calls (predictions) attached by the AM predict step;
    # the gradable records themselves live in the ledger.
    predictions: list[Call] = field(default_factory=list)


@dataclass
class Briefing:
    """A composed AM Briefing: TL;DR + the finalists."""

    date: _dt.date
    tldr: list[str] = field(default_factory=list)
    items: list[Item] = field(default_factory=list)


# ── Prompt building ──────────────────────────────────────────────────────────

_RULES = """\
You are the editor of a lean, twice-daily personal investing briefing. Hard rules:
- LEAN IS A FEATURE. Pick only the highest-signal stories. When unsure, cut it.
- Three pillars: Politics (worldwide, mostly US), Technology (REAL breakthroughs
  — research, hardware, science — NOT AI hype or product-launch churn), Economy
  (serious US metrics: inflation, rates, jobs, GDP).
- No filler, no fluff, no low-signal churn.
- RECENCY FIRST: prefer the freshest stories; when two compete, newer wins.
- The reader invests in ETFs + individual stocks (watchlist: {watchlist}); favor
  items that sharpen real investing decisions or teach something genuinely new."""


def _select_prompt(articles: list[Article], econ: list[EconSeries]) -> str:
    today = _dt.date.today().isoformat()
    lines = [
        _RULES.format(watchlist=", ".join(config.watchlist())),
        "",
        f"Today is {today}. Below are candidate items. Select about {TARGET_ITEMS} "
        "finalists total — aim for one per pillar, but only include an item if it "
        "genuinely earns its place. It is fine to return fewer than "
        f"{TARGET_ITEMS} if the pool is thin; never pad with filler.",
        "When two candidates cover essentially the same story, prefer the AP News "
        "one over Reuters (AP's full text is reliably available for key points; "
        "Reuters' is not). This is a tie-breaker only — a clearly stronger or "
        "fresher Reuters story still wins.",
        "",
        "ARTICLES:",
    ]
    for i, a in enumerate(articles):
        when = a.published.date().isoformat() if a.published else "undated"
        summary = " ".join(a.summary.split())[:240]
        lines.append(f"[A{i}] ({a.source}, {when}) {a.title}\n    {summary}")

    if econ:
        lines.append("\nECONOMIC SERIES (FRED, latest readings):")
        for i, e in enumerate(econ):
            chg = "" if e.change is None else f", prev {e.prev_value} (Δ {e.change:+.2f})"
            lines.append(f"[E{i}] {e.title}: {e.latest_value} on {e.latest_date}{chg}")

    lines.append(
        "\nReturn JSON: "
        '{"selected": [{"ref": "A3", "pillar": "Technology", "reason": "<short>"}]}. '
        'Use the [A#]/[E#] refs exactly. "pillar" must be one of '
        "Politics/Technology/Economy."
    )
    return "\n".join(lines)


def _compose_prompt(selected: list[dict]) -> str:
    """`selected` items each carry: ref, pillar, headline, source, link, context."""
    blocks = [
        _RULES.format(watchlist=", ".join(config.watchlist())),
        "",
        "Write the final briefing for these chosen items. For EACH item produce:",
        "- 2-3 key points pulled from the provided content (factual, specific, no fluff).",
        "- a single one-line 'why it matters' / application for an investor.",
        "Do NOT reproduce full article text — distill. Keep every line tight.",
        "Also write a TL;DR: one ultra-short line per item for skim-back.",
        "",
        "ITEMS:",
    ]
    for s in selected:
        blocks.append(
            f"### {s['ref']} | {s['pillar']} | {s['headline']} ({s['source']})\n"
            f"{s['context']}"
        )
    blocks.append(
        "\nReturn JSON: "
        '{"tldr": ["<line per item>"], '
        '"items": [{"ref": "A3", "key_points": ["...", "..."], '
        '"why_it_matters": "..."}]}'
    )
    return "\n".join(blocks)


# ── Orchestration ────────────────────────────────────────────────────────────

def _index_candidates(articles: list[Article], econ: list[EconSeries]) -> dict:
    refs: dict[str, dict] = {}
    for i, a in enumerate(articles):
        refs[f"A{i}"] = {"kind": "article", "obj": a}
    for i, e in enumerate(econ):
        refs[f"E{i}"] = {"kind": "econ", "obj": e}
    return refs


def curate(sources: Sources, today: _dt.date | None = None) -> Briefing:
    """Run the two-pass curation and return a composed Briefing.

    Raises if nothing usable can be selected (an empty briefing is never sent).
    """
    today = today or _dt.date.today()
    if not sources.articles and not sources.econ:
        raise RuntimeError("No candidate sources fetched; cannot curate a briefing.")

    refs = _index_candidates(sources.articles, sources.econ)

    # Pass 1 — selection.
    selection = llm.complete_json(_select_prompt(sources.articles, sources.econ))
    chosen = selection.get("selected", []) if isinstance(selection, dict) else []
    if not chosen:
        raise RuntimeError("Curator selected no items.")

    # Build the compose payload: attach real content/context to each finalist.
    selected: list[dict] = []
    for pick in chosen[: TARGET_ITEMS + 1]:  # small safety margin over target
        ref = pick.get("ref")
        entry = refs.get(ref)
        if not entry:
            log.warning("Curator returned unknown ref %r; skipping.", ref)
            continue
        pillar = pick.get("pillar", "")
        if entry["kind"] == "article":
            a: Article = entry["obj"]
            # Wire links come via Google News as encoded redirects — resolve to
            # the real article URL so both extraction and the email link are real.
            link = extract.resolve_link(a.link)
            context = extract.best_context(link, a.summary)
            selected.append(
                {
                    "ref": ref, "pillar": pillar, "headline": a.title,
                    "source": a.source, "link": link, "context": context,
                    "kind": "article",
                }
            )
        else:
            e: EconSeries = entry["obj"]
            chg = "" if e.change is None else f" Previous reading {e.prev_value} (change {e.change:+.2f})."
            context = (
                f"{e.title}. Latest value {e.latest_value} as of {e.latest_date}.{chg} "
                f"FRED series {e.series_id}."
            )
            selected.append(
                {
                    "ref": ref, "pillar": pillar or "Economy", "headline": e.title,
                    "source": f"FRED ({e.series_id})",
                    "link": f"https://fred.stlouisfed.org/series/{e.series_id}",
                    "context": context, "kind": "econ",
                }
            )

    if not selected:
        raise RuntimeError("No valid finalists after resolving curator refs.")

    # Pass 2 — composition.
    composed = llm.complete_json(_compose_prompt(selected))
    by_ref = {c.get("ref"): c for c in composed.get("items", [])}

    items: list[Item] = []
    for s in selected:
        c = by_ref.get(s["ref"], {})
        key_points = [p.strip() for p in c.get("key_points", []) if p.strip()]
        items.append(
            Item(
                pillar=s["pillar"] or "—",
                headline=s["headline"],
                link=s["link"],
                source=s["source"],
                key_points=key_points or ["(key points unavailable)"],
                why_it_matters=c.get("why_it_matters", "").strip(),
            )
        )

    tldr = [t.strip() for t in composed.get("tldr", []) if t.strip()]
    # Order items by pillar for a consistent read.
    items.sort(key=lambda it: PILLARS.index(it.pillar) if it.pillar in PILLARS else 99)
    return Briefing(date=today, tldr=tldr, items=items)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    from .fetch import fetch_all

    b = curate(fetch_all())
    print(json.dumps(
        {"date": b.date.isoformat(), "tldr": b.tldr,
         "items": [vars(i) for i in b.items]},
        indent=2,
    ))
