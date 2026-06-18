"""Article key-point extraction (Phase 1).

For each candidate article, pull the headline + 2-3 key points from the real
piece via `trafilatura`. NEVER store or emit full article text — key points +
source link only (copyright + the "preserve real articles, not lossy summaries"
rule in CLAUDE.md).

TODO (Phase 1): implement `extract_key_points(url)`.
"""
