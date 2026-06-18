"""Load and expose `config.toml` (the source of truth) and `.env` secrets.

`config.toml` is read with the stdlib `tomllib` (Python 3.11+); secrets come from
`.env` via python-dotenv. Keeping all config access here means watchlist/sector/
source/schedule changes are one-line edits to `config.toml` with no code changes.

TODO (Phase 0/1): implement `load_config()` and `get_secret()` helpers.
"""
