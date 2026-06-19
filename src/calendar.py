"""Trading-day / holiday gate (Phase 1).

Uses `pandas-market-calendars` (NYSE) to decide whether a given day is a trading
day. Both entry points call this first and exit early on weekends/market
holidays, so the digest is only ever sent on days the US market is open.

Note: this module shadows the stdlib `calendar`, but only for imports that
explicitly reference the `src` package (`from src import calendar`). Plain
`import calendar` elsewhere still resolves to the stdlib module.
"""

from __future__ import annotations

import datetime as _dt
from functools import lru_cache
from zoneinfo import ZoneInfo

import pandas_market_calendars as mcal

MARKET = "NYSE"
EASTERN = ZoneInfo("America/New_York")


@lru_cache(maxsize=1)
def _nyse():
    return mcal.get_calendar(MARKET)


def today_eastern() -> _dt.date:
    """The current calendar date in US/Eastern (the schedule's reference zone)."""
    return _dt.datetime.now(tz=EASTERN).date()


def is_trading_day(date: _dt.date | None = None) -> bool:
    """True if `date` (default: today in Eastern) is an NYSE trading day.

    Weekends and US market holidays return False. The gate is what keeps the
    agent from emailing on days the market is closed.
    """
    if date is None:
        date = today_eastern()
    schedule = _nyse().schedule(start_date=date, end_date=date)
    return not schedule.empty


if __name__ == "__main__":
    d = today_eastern()
    print(f"{d} ({d:%A}) trading day? {is_trading_day(d)}")
