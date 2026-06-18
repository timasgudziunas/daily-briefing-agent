"""Trading-day / holiday gate (Phase 1).

Uses `pandas-market-calendars` (NYSE) to decide whether today is a trading day.
Both entry points call this first and exit early on weekends/market holidays.

TODO (Phase 1): implement `is_trading_day(date)` against the NYSE calendar.
"""
