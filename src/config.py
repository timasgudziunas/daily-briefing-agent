"""Load and expose `config.toml` (the source of truth) and `.env` secrets.

`config.toml` is read with the stdlib `tomllib` (Python 3.11+); secrets come from
`.env` via python-dotenv. Keeping all config access here means watchlist/sector/
source/schedule changes are one-line edits to `config.toml` with no code changes.
"""

from __future__ import annotations

import os
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# Repo root = parent of this file's `src/` directory.
ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.toml"
ENV_PATH = ROOT / ".env"


@lru_cache(maxsize=1)
def load_config() -> dict[str, Any]:
    """Parse and cache `config.toml`. Raises if the file is missing."""
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"config.toml not found at {CONFIG_PATH}")
    with CONFIG_PATH.open("rb") as f:
        return tomllib.load(f)


@lru_cache(maxsize=1)
def _load_env() -> None:
    """Load `.env` into the process environment exactly once.

    Does NOT override variables already set in the real environment, so a value
    exported by the OS/scheduler wins over the file.
    """
    load_dotenv(ENV_PATH, override=False)


def get_secret(name: str, default: str | None = None) -> str | None:
    """Return a secret from the environment / `.env`.

    Returns `default` (None) when unset or blank, so callers can treat an empty
    placeholder the same as "not configured" and degrade gracefully.
    """
    _load_env()
    value = os.environ.get(name, default)
    if value is not None and value.strip() == "":
        return default
    return value


# ── Convenience accessors (thin wrappers over load_config) ──────────────────

def watchlist() -> list[str]:
    return load_config().get("watchlist", {}).get("tickers", [])


def sectors() -> list[str]:
    return load_config().get("sectors", {}).get("focus", [])


def horizons() -> list[str]:
    return load_config().get("predictions", {}).get("horizons", [])


def sources() -> dict[str, Any]:
    return load_config().get("sources", {})


def schedule() -> dict[str, Any]:
    return load_config().get("schedule", {})
