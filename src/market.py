"""Price / market-data lookups for grading (Phase 2).

Outcome data the PM run grades against: `yfinance` for prices (primary) with
`finnhub-python` as a fallback for the current quote, plus FRED for economic
series outcomes. These are pure data accessors — every function degrades
gracefully (returns None) on failure so a flaky data source never crashes the
PM run; the grader simply marks what it cannot verify as ungradable.

yfinance covers historical closes (needed for multi-day horizons); Finnhub's
free quote endpoint only knows the *current* price, so it backs up same-day /
latest-close lookups, not arbitrary historical dates.
"""

from __future__ import annotations

import datetime as _dt
import logging
from dataclasses import dataclass

from . import config

log = logging.getLogger(__name__)


@dataclass
class Quote:
    """A resolved price point."""

    ticker: str
    close: float
    date: _dt.date
    source: str  # "yfinance" | "finnhub"


@dataclass
class Move:
    """Price movement of a ticker between two closes."""

    ticker: str
    start_close: float
    end_close: float
    start_date: _dt.date
    end_date: _dt.date
    source: str

    @property
    def pct(self) -> float:
        if not self.start_close:
            return 0.0
        return (self.end_close - self.start_close) / self.start_close * 100.0

    def describe(self) -> str:
        arrow = "up" if self.pct >= 0 else "down"
        return (
            f"{self.ticker}: {self.start_close:.2f} ({self.start_date}) -> "
            f"{self.end_close:.2f} ({self.end_date}), {arrow} {abs(self.pct):.2f}% "
            f"[{self.source}]"
        )


# ── yfinance (primary) ────────────────────────────────────────────────────────

def _yf_history(ticker: str, start: _dt.date, end: _dt.date):
    """Return a yfinance history DataFrame, or None on any failure."""
    try:
        import yfinance as yf
    except ImportError:
        log.warning("yfinance not installed; cannot fetch prices.")
        return None
    try:
        # end is exclusive in yfinance; pad it by a day to include `end`.
        df = yf.Ticker(ticker).history(
            start=start.isoformat(),
            end=(end + _dt.timedelta(days=1)).isoformat(),
            auto_adjust=True,
        )
        if df is None or df.empty:
            return None
        return df
    except Exception as exc:
        log.warning("yfinance history failed for %s: %s", ticker, exc)
        return None


def close_on(ticker: str, date: _dt.date) -> Quote | None:
    """The last close on or before `date` (handles weekends/holidays)."""
    df = _yf_history(ticker, date - _dt.timedelta(days=7), date)
    if df is None:
        return None
    try:
        row = df.iloc[-1]
        idx = df.index[-1]
        return Quote(ticker, float(row["Close"]), idx.date(), "yfinance")
    except Exception:
        return None


def latest_close(ticker: str) -> Quote | None:
    """The most recent available close, yfinance first, Finnhub as fallback."""
    df = _yf_history(ticker, _dt.date.today() - _dt.timedelta(days=10), _dt.date.today())
    if df is not None:
        try:
            row = df.iloc[-1]
            idx = df.index[-1]
            return Quote(ticker, float(row["Close"]), idx.date(), "yfinance")
        except Exception:
            pass
    return _finnhub_quote(ticker)


def move_since(ticker: str, since: _dt.date) -> Move | None:
    """Price movement from the close on/before `since` to the latest close."""
    start = close_on(ticker, since)
    end = latest_close(ticker)
    if not start or not end:
        return None
    return Move(ticker, start.close, end.close, start.date, end.date, end.source)


def daily_move(ticker: str) -> Move | None:
    """Latest session's move (prior close -> latest close) for same-day calls."""
    df = _yf_history(ticker, _dt.date.today() - _dt.timedelta(days=10), _dt.date.today())
    if df is not None and len(df) >= 2:
        try:
            prev, last = df.iloc[-2], df.iloc[-1]
            return Move(
                ticker, float(prev["Close"]), float(last["Close"]),
                df.index[-2].date(), df.index[-1].date(), "yfinance",
            )
        except Exception:
            pass
    # Finnhub fallback: its quote carries current price + previous close.
    q = _finnhub_raw(ticker)
    if q and q.get("pc") and q.get("c"):
        today = _dt.date.today()
        return Move(
            ticker, float(q["pc"]), float(q["c"]),
            today - _dt.timedelta(days=1), today, "finnhub",
        )
    return None


# ── Finnhub (fallback, current quote only) ────────────────────────────────────

def _finnhub_raw(ticker: str) -> dict | None:
    api_key = config.get_secret("FINNHUB_API_KEY")
    if not api_key:
        return None
    try:
        import finnhub
    except ImportError:
        log.warning("finnhub-python not installed; no price fallback.")
        return None
    try:
        q = finnhub.Client(api_key=api_key).quote(ticker)
        return q if q and q.get("c") else None
    except Exception as exc:
        log.warning("Finnhub quote failed for %s: %s", ticker, exc)
        return None


def _finnhub_quote(ticker: str) -> Quote | None:
    q = _finnhub_raw(ticker)
    if not q:
        return None
    return Quote(ticker, float(q["c"]), _dt.date.today(), "finnhub")


# ── PM Market Summary ─────────────────────────────────────────────────────────

@dataclass
class SummaryRow:
    """One labeled line in the PM Market Summary grid (display data only)."""

    label: str
    group: str           # "Indices" | "Watchlist" | "Commodities" | "Crypto" | "Rates"
    level: str           # preformatted, e.g. "7,500.58" or "4.49%"
    change: str          # preformatted, e.g. "+1.08%" or "+6 bp" or "—"
    direction: str       # "up" | "down" | "flat" (drives the color)


# Render groups in this order regardless of config/fetch order.
_GROUP_ORDER = ["Indices", "Watchlist", "Commodities", "Crypto", "Rates"]


def _fmt_level(value: float) -> str:
    return f"{value:,.2f}"


def _price_row(symbol: str, label: str, group: str) -> SummaryRow | None:
    """A SummaryRow from the latest session's % move, or None if no data."""
    m = daily_move(symbol)
    if not m:
        return None
    pct = m.pct
    direction = "up" if pct > 0.005 else "down" if pct < -0.005 else "flat"
    sign = "+" if pct >= 0 else "-"
    return SummaryRow(label, group, _fmt_level(m.end_close), f"{sign}{abs(pct):.2f}%", direction)


def _yield_row(series_id: str, label: str = "10Y Treasury") -> SummaryRow | None:
    """A SummaryRow for a FRED rate series: level (%) + daily change in bp."""
    vals = fred_values(series_id)
    if not vals:
        return None
    latest, prev, _ = vals
    if prev is None:
        return SummaryRow(label, "Rates", f"{latest:.2f}%", "—", "flat")
    bp = (latest - prev) * 100
    direction = "up" if bp > 0.5 else "down" if bp < -0.5 else "flat"
    sign = "+" if bp >= 0 else "-"
    return SummaryRow(label, "Rates", f"{latest:.2f}%", f"{sign}{abs(bp):.0f} bp", direction)


def summary_rows() -> list[SummaryRow]:
    """Build the full Market Summary grid: configured instruments + watchlist + yield.

    Each row degrades independently — a single ticker with no data is dropped, not
    fatal — so a flaky source never sinks the whole summary.
    """
    rows: list[SummaryRow] = []
    for inst in config.market_summary():
        symbol = inst.get("symbol")
        if not symbol:
            continue
        row = _price_row(symbol, inst.get("label", symbol), inst.get("group", "Markets"))
        if row:
            rows.append(row)
    for ticker in config.watchlist():
        row = _price_row(ticker, ticker, "Watchlist")
        if row:
            rows.append(row)
    yield_series = config.market_yield_series()
    if yield_series:
        row = _yield_row(yield_series)
        if row:
            rows.append(row)
    # Stable sort by group order (preserves within-group ordering from config).
    rows.sort(key=lambda r: _GROUP_ORDER.index(r.group) if r.group in _GROUP_ORDER else 99)
    return rows


def summary_context(rows: list[SummaryRow]) -> str:
    """Compact text of the moves, fed to the LLM to explain the day's direction."""
    if not rows:
        return "(price data unavailable)"
    return "\n".join(f"{r.label} ({r.group}): {r.level}, {r.change}" for r in rows)


# ── FRED (economic outcomes) ──────────────────────────────────────────────────

def fred_values(series_id: str) -> tuple[float, float | None, _dt.date] | None:
    """Numeric latest reading of a FRED series: (latest, prev_or_None, date).

    Shares the same graceful-degradation rules as `fred_latest` (no key -> None,
    never raises); used where callers need the raw numbers, not a description.
    """
    try:
        api_key = config.get_secret("FRED_API_KEY")
        if not api_key:
            return None
        from fredapi import Fred

        data = Fred(api_key=api_key).get_series(series_id).dropna()
        if data.empty:
            return None
        latest = float(data.iloc[-1])
        prev = float(data.iloc[-2]) if len(data) > 1 else None
        return latest, prev, data.index[-1].date()
    except Exception as exc:
        log.warning("FRED values lookup failed for %s: %s", series_id, exc)
        return None


def fred_latest(series_id: str) -> str | None:
    """A short human description of a FRED series' latest reading, or None.

    Reuses fetch.py's FRED logic so the same degradation rules apply (no key ->
    None, never raises).
    """
    from . import fetch

    try:
        api_key = config.get_secret("FRED_API_KEY")
        if not api_key:
            return None
        from fredapi import Fred

        data = Fred(api_key=api_key).get_series(series_id).dropna()
        if data.empty:
            return None
        latest, latest_date = float(data.iloc[-1]), data.index[-1].date()
        if len(data) > 1:
            prev = float(data.iloc[-2])
            return (
                f"FRED {series_id}: {latest} on {latest_date} "
                f"(prev {prev}, change {latest - prev:+.2f})"
            )
        return f"FRED {series_id}: {latest} on {latest_date}"
    except Exception as exc:
        log.warning("FRED lookup failed for %s: %s", series_id, exc)
        return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for t in config.watchlist() + ["SPY"]:
        m = daily_move(t)
        print(m.describe() if m else f"{t}: no data")
    print(fred_latest("DGS10"))
