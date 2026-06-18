"""Persistent state: ledger (JSON) + lessons (Markdown) + archive (Phase 2).

The ledger is the system's memory and source of truth. Prediction schema:
date, item, call, horizon, status, outcome, why. The lessons file holds
distilled, generalizable rules — kept curated and SMALL, and read by the AM run
before predicting. The archive stores full sent emails as dated markdown.

PRIVACY: the real `data/ledger.json`, `data/lessons.md`, and `data/archive/`
contents are gitignored (personal track record stays local). Only blank
`*.example.*` templates are committed. On first run, if a real file is missing,
create it from its template (e.g. `ledger.example.json` -> `ledger.json`).

TODO (Phase 2): implement read/write for `data/ledger.json` and `data/lessons.md`,
including the create-from-template bootstrap when the real file is absent.
"""
