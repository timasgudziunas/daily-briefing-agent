"""Throwaway preview: render a PM Debrief with placeholder data in every section.

Purpose — let the owner eyeball ALL parts of the redesigned PM email (scorecard
with each verdict type, the new Market Summary grid, and the "Something New"
nightly learning piece) without waiting for real predictions/feeds. Uses the
real email.py renderer so the output is pixel-identical to a live send. No email
is sent; nothing is written to the ledger/archive.

Run:  PYTHONPATH=. python scripts/preview_pm_placeholder.py
"""

from __future__ import annotations

import datetime as _dt
import webbrowser
from pathlib import Path

from src import email as mailer
from src.debrief import Debrief, LearningPiece
from src.ledger import Prediction
from src.market import SummaryRow

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "archive" / "_preview-pm-placeholder.html"

TODAY = _dt.date(2026, 6, 19)


def _grade(status, horizon, created, call, outcome, why) -> Prediction:
    return Prediction(
        id=f"{created}-{status}", created=created, run="am", item=call,
        pillar="Market", call=call, horizon=horizon, due=TODAY.isoformat(),
        status=status, outcome=outcome, why=why, graded=TODAY.isoformat(),
    )


grades = [
    _grade(
        "right", "same-day", "2026-06-19",
        "Meta closes higher than its open as the antitrust headline fades.",
        "META opened $702.10, closed $711.84 (+1.4%).",
        "Sellers faded the open; the regulatory news was already priced in. "
        "Call resolves clean-right against the close.",
    ),
    _grade(
        "wrong", "1-week", "2026-06-12",
        "10-year Treasury yield falls below 4.20% within a week on soft data.",
        "10Y closed the week at 4.31%, up 6bp from the call.",
        "A hotter-than-expected retail-sales print reversed the bond rally. "
        "The directional read was wrong; data, not vibes.",
    ),
    _grade(
        "partial", "1-month", "2026-05-19",
        "Alphabet outperforms the S&P 500 by 3+ points over the month.",
        "GOOGL +4.9% vs SPY +2.6% — outperformed by 2.3 pts, short of the 3-pt bar.",
        "Right on direction and leadership, but the magnitude target wasn't met. "
        "Partial credit: the thesis held, the threshold didn't.",
    ),
]

market_wrap = [
    "Broad tape firm: stocks rose on cooling-inflation hopes, but breadth stayed narrow — megacaps did the lifting.",
    "Gold slipped as real yields firmed; crude was flat on an offsetting inventory build.",
    "Bitcoin fell ~4% in a risk-appetite wobble, diverging from equities.",
]

market_moves = [
    SummaryRow("S&P 500", "Indices", "7,500.58", "+1.08%", "up"),
    SummaryRow("Nasdaq", "Indices", "26,517.93", "+1.91%", "up"),
    SummaryRow("Dow", "Indices", "51,564.70", "+0.14%", "up"),
    SummaryRow("META", "Watchlist", "577.22", "+1.70%", "up"),
    SummaryRow("GOOGL", "Watchlist", "368.03", "+1.17%", "up"),
    SummaryRow("Gold", "Commodities", "4,172.90", "-1.21%", "down"),
    SummaryRow("Crude oil", "Commodities", "76.54", "-0.08%", "flat"),
    SummaryRow("Bitcoin", "Crypto", "62,896.47", "-4.12%", "down"),
    SummaryRow("10Y Treasury", "Rates", "4.49%", "+6 bp", "up"),
]

learning = LearningPiece(
    title="The Roman concrete that gets stronger the longer it sits in the sea",
    topic="Engineering",
    context=(
        "Modern concrete slowly crumbles in seawater, yet Roman harbor structures "
        "poured 2,000 years ago are still standing. For decades nobody knew why "
        "their recipe outlasted ours — until researchers looked at it crystal by "
        "crystal."
    ),
    key_points=[
        "Roman builders mixed volcanic ash with lime and seawater; the reaction grew "
        "a rare mineral, aluminous tobermorite, that ordinary concrete never forms.",
        "Seawater percolating through the material kept dissolving and re-precipitating "
        "crystals — so the concrete actively self-reinforced instead of decaying.",
        "Labs are now trying to reverse-engineer the recipe for greener, longer-lived "
        "marine concrete, since modern Portland cement is a major CO2 source.",
    ],
    link="https://www.smithsonianmag.com/example-roman-concrete",
    source="Smithsonian",
)

deb = Debrief(
    date=TODAY,
    tldr=[
        "Scorecard 1-1-1: same-day Meta call hit, 1-week rates call missed.",
        "Tech led a narrow tape; gold and bitcoin slipped, 10Y up 6bp.",
        "Something New: why Roman sea-concrete outlasts ours by two millennia.",
    ],
    grades=grades,
    market_wrap=market_wrap,
    market_moves=market_moves,
    learning=learning,
)

subject, html = mailer.build_pm_html(deb)
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(html, encoding="utf-8")
print(f"Subject: {subject}")
print(f"Preview: {OUT}")
try:
    webbrowser.open(OUT.as_uri())
except Exception:
    pass
