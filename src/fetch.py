"""Source fetching: RSS feeds + FRED economic data (Phase 1).

Pulls from the sources in `config.toml`: AP News (native RSS), Reuters (via a
feed generator), Ars Technica + IEEE Spectrum (native RSS), and FRED series.
Recency-first: always prefer the freshest items.

TODO (Phase 1): implement feed fetching (`feedparser`) and FRED pulls (`fredapi`).
"""
