# PLAN.md

The ordered build plan for this project. **Work top to bottom.** Don't jump ahead — each phase assumes the previous one works. Check items off (`- [x]`) as you complete them and keep this file current. `CLAUDE.md` holds the rules and constraints that govern *how* each item is built; this file is the *what* and the *order*. If something here is ambiguous or an "open item," ask before assuming.

A phase is "done" only when it runs end-to-end and the output has been reviewed by the owner.

---

## Phase 0 — Scaffolding

Goal: an empty but runnable skeleton with config and secrets wired.

- [ ] Initialize the repo and the structure from `CLAUDE.md` ("Target repo structure").
- [ ] Set up a Python virtual environment and a `requirements.txt` with the stack from `CLAUDE.md`.
- [ ] Create `.gitignore` — ignore `.env` and any local cruft. Decide whether `data/` (ledger, lessons, archive) is committed (it should be, so the track record persists in the repo).
- [ ] Create the `config` file with: send times (7:45 AM / 5:00 PM ET), watchlist (`META`, `GOOGL`), the 8 sectors, and the source list.
- [ ] Create `.env` with placeholders: FRED API key, Finnhub key, Gmail address + app password.
- [ ] Confirm Claude Code is authenticated on the Max subscription and **no `ANTHROPIC_API_KEY` is set** in the runtime environment.

## Phase 1 — MVP: a hand-run AM Briefing

Goal: run one command and get a real, well-formatted AM Briefing in the inbox. No predictions or scheduling yet.

- [ ] `calendar.py` — trading-day / holiday gate (`pandas-market-calendars`). Entry points exit early on non-trading days.
- [ ] `fetch.py` — pull from sources: AP (native RSS), Reuters (via feed generator), Ars Technica + IEEE Spectrum (native RSS), and FRED API for economic data. Respect **recency-first** (prefer the latest).
- [ ] `extract.py` — pull headline + 2–3 key points from each article via `trafilatura`. Never store/emit full article text.
- [ ] `llm.py` — the single swappable LLM interface (Claude Code headless under Max).
- [ ] Curation prompt — select ~3 items across the 3 pillars; enforce no-filler, no-AI-slop, recency-first; produce the per-item "why it matters" line. Politics worldwide-but-mostly-US; economy = serious US metrics only.
- [ ] `email.py` — build the HTML email: top TL;DR summary, pillar sections, per-item format, subject `AM Briefing | M/D/YY`, and the "Open in Claude" button (prefilled with the day's digest, defaulting to the most recent email).
- [ ] Gmail send via `yagmail`/`smtplib` + app password.
- [ ] `am_briefing.py` entry point wiring the above together; write the sent email to `archive/`.
- [ ] Run end-to-end by hand; iterate with the owner on output quality before moving on.

## Phase 2 — The PM Debrief + prediction/feedback loop

Goal: the loop that makes it improve. AM predicts, PM grades and learns. Still hand-run.

- [ ] `ledger.py` — read/write the ledger (JSON) and the lessons file. Define the prediction schema: date, item, call, horizon, status, outcome, why.
- [ ] Prediction step in the AM run — for each item, pick the right horizon(s) from the locked ladder (same-day, 1wk, 1mo, 1Q, 6mo, 1yr) and append to the ledger. The AM run **reads the lessons file before predicting.**
- [ ] `market.py` — outcome data: `yfinance` for prices (with `finnhub-python` fallback), FRED for data outcomes.
- [ ] `grade.py` — strict, data-grounded grading. Load this morning's predictions plus any long-horizon ones now due; mark right/wrong/partial with why, anchored to real prices/data.
- [ ] Lessons distillation — when the PM finds misses, write concise, generalizable rules into the lessons file; keep it curated and small.
- [ ] `pm_debrief.py` — PM email: open with the prediction grades, then the market wrap (what moved + why), ~2 items, and the learning piece (anything, guaranteed-novel). Subject `PM Debrief | M/D/YY`. Archive it.
- [ ] Run AM → PM end-to-end by hand across a few days; confirm the loop reads/writes state correctly.

## Phase 3 — Automation: hands-off scheduling

Goal: it runs itself on trading days without you touching it.

- [ ] Schedule both runs via cron (Mac/Linux) or Task Scheduler (Windows) at 7:45 AM / 5:00 PM in the `America/New_York` timezone (not a fixed offset). Enable wake-to-run.
- [ ] Confirm the trading-day gate prevents weekend/holiday sends.
- [ ] Run logging — record each run's outcome so you can tell it fired.
- [ ] Basic error handling — a dead source or an API hiccup degrades gracefully instead of killing the whole email.

## Phase 4 — Reliability & polish

Goal: trustworthy day after day.

- [ ] Story de-duplication — don't repeat the same item across sends or days.
- [ ] Source fallbacks verified (yfinance → Finnhub; a missing feed doesn't break the run).
- [ ] Lessons-file size cap / periodic curation so it stays small and high-signal.
- [ ] Owner tasks (not code): set up the two Gmail label filters (AM vs PM); optionally connect the repo to a Claude Project for chatting over past briefings.

## Phase 5 — Stage two: make it agentic (the learning goal)

Goal: turn the single LLM call into an agent that finds what matters.

- [ ] Give the LLM real tools through the swappable interface — web search first.
- [ ] Let it decide what to chase and iterate (pull threads, verify, dig) rather than only summarizing what it's handed.
- [ ] Keep everything above intact — this is an upgrade to the curation/prediction brain, not a rewrite.

---

## Open items (resolve before the relevant step)

- None currently outstanding. (Send times, sources, and Reuters are all decided — see `CLAUDE.md`.) The owner intends to add specific watchlist tickers/ETFs later; the watchlist must stay a one-line-edit config list.
