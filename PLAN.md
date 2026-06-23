# PLAN.md

The ordered build plan for this project. **Work top to bottom.** Don't jump ahead — each phase assumes the previous one works. Check items off (`- [x]`) as you complete them and keep this file current. `CLAUDE.md` holds the rules and constraints that govern *how* each item is built; this file is the *what* and the *order*. If something here is ambiguous or an "open item," ask before assuming.

A phase is "done" only when it runs end-to-end and the output has been reviewed by the owner.

---

## Phase 0 — Scaffolding

Goal: an empty but runnable skeleton with config and secrets wired.

- [x] Initialize the repo and the structure from `CLAUDE.md` ("Target repo structure"). _(config is `config.toml`, read via stdlib `tomllib`.)_
- [x] Set up a Python virtual environment (`.venv/`) and a `requirements.txt` with the stack from `CLAUDE.md`. _(All deps installed & imports verified on Python 3.13.)_
- [x] Create `.gitignore` — ignore `.env` and any local cruft. Decide whether `data/` (ledger, lessons, archive) is committed. _(DECISION: real ledger/lessons/archive are **gitignored for privacy** — only blank `*.example.*` templates + `archive/.gitkeep` are committed so structure stays visible. `.venv`/`.env` ignored. See CLAUDE.md "Privacy".)_
- [x] Create the `config` file with: send times (7:45 AM / 5:00 PM ET), watchlist (`META`, `GOOGL`), the 8 sectors, and the source list. _(`config.toml`. AP/Reuters feed URLs are marked placeholders to confirm in Phase 1.)_
- [x] Create `.env` with placeholders: FRED API key, Finnhub key, Gmail address + app password. _(Plus committed `.env.example` template.)_
- [x] Confirm Claude Code is authenticated on the Max subscription and **no `ANTHROPIC_API_KEY` is set** in the runtime environment. _(`claude` CLI on PATH; `ANTHROPIC_API_KEY` confirmed unset.)_

## Phase 1 — MVP: a hand-run AM Briefing

Goal: run one command and get a real, well-formatted AM Briefing in the inbox. No predictions or scheduling yet.

- [x] `calendar.py` — trading-day / holiday gate (`pandas-market-calendars`). Entry points exit early on non-trading days. _(NYSE calendar; `is_trading_day()` + `today_eastern()`. AM entry gates on it unless `--force`.)_
- [x] `fetch.py` — pull from sources: AP (native RSS), Reuters (via feed generator), Ars Technica + IEEE Spectrum (native RSS), and FRED API for economic data. Respect **recency-first** (prefer the latest). _(feedparser + fredapi. Recency: stale items dropped, newest-first, per-feed cap. **Placeholder feeds are skipped + dead source/missing key degrades gracefully.** AP+Reuters now come via **Google News RSS** (free, no account/expiry; `site:` filter per wire) instead of rss.app — its encoded redirect links are resolved to the real article URL in `extract.resolve_link()` (finalists only, stdlib, no new dep). AP extracts cleanly; Reuters blocks extraction (401) so it stays a SELECT-pool candidate with an AP-preference tie-breaker for finalists.)_
- [x] `extract.py` — pull headline + 2–3 key points from each article via `trafilatura`. Never store/emit full article text. _(extract.py returns a clean ~2k-char excerpt for the LLM; the curation pass distills the 2–3 key points. Full text never persisted; extraction runs on finalists only.)_
- [x] `llm.py` — the single swappable LLM interface (Claude Code headless under Max). _(`complete()`/`complete_json()` shell to `claude -p` via stdin; ANTHROPIC_API_KEY stripped from the child env as defense-in-depth.)_
- [x] Curation prompt — select ~3 items across the 3 pillars; enforce no-filler, no-AI-slop, recency-first; produce the per-item "why it matters" line. Politics worldwide-but-mostly-US; economy = serious US metrics only. _(`curate.py`, two passes: SELECT then COMPOSE. Small structural addition beyond CLAUDE.md's module list — keeps am_briefing thin; LLM transport still lives only in llm.py.)_
- [x] `email.py` — build the HTML email: top TL;DR summary, pillar sections, per-item format, subject `AM Briefing | M/D/YY`, and the "Open in Claude" button (prefilled with the day's digest, defaulting to the most recent email). _(Inline-styled responsive HTML; `claude.ai/new?q=` prefill carries the digest.)_
- [x] Gmail send via `yagmail`/`smtplib` + app password. _(`send_email()` via yagmail; defaults to self. **Code done; real send pending owner's Gmail App Password in `.env`.**)_
- [x] `am_briefing.py` entry point wiring the above together; write the sent email to `archive/`. _(Gate → fetch → curate → build → send → archive. Flags: `--no-send` (local HTML preview), `--force`, `--to`. Archive → gitignored `data/archive/YYYY-MM-DD-am.md`.)_
- [x] Run end-to-end by hand; iterate with the owner on output quality before moving on. _(Ran end-to-end in `--no-send` mode 6/18 — clean output. **6/19: full real send succeeded** — `AM Briefing | 6/19/26` delivered to inbox (3 lean items, one per pillar; resolved AP link, FRED economy, sharp why-it-matters lines). Trading-day gate correctly flagged Juneteenth as a holiday (used `--force` to test). Owner reviewed → Phase 1 done. AP+Reuters wires (Google News), `FRED_API_KEY`, and Gmail App Password are all in — real inbox send confirmed 6/19.)_

## Phase 2 — The PM Debrief + prediction/feedback loop

Goal: the loop that makes it improve. AM predicts, PM grades and learns. Still hand-run.

- [x] `ledger.py` — read/write the ledger (JSON) and the lessons file. Define the prediction schema: date, item, call, horizon, status, outcome, why. _(Full `Prediction` dataclass — id/created/run/item/pillar/call/horizon/due/ticker/metric/status/outcome/why/graded. Atomic save, `due_predictions()`, `update_predictions()`, horizon→due-date math (month-clamped, e.g. Jan 31 +1mo → Feb 28). Create-from-template bootstrap on first use; round-trip verified.)_
- [x] Prediction step in the AM run — for each item, pick the right horizon(s) from the locked ladder (same-day, 1wk, 1mo, 1Q, 6mo, 1yr) and append to the ledger. The AM run **reads the lessons file before predicting.** _(`predict.py`: one LLM pass, **1–2 predictions per item (model's call)**, anchored to a `ticker` or FRED `metric` where possible. AM reads lessons → predicts → appends; best-effort (a predict failure still sends the briefing). **Owner feedback (built):** calls are now SHORT/plain (claim only; reasoning moved to a stored `rationale`), the step does **live web research** before each call (WebSearch/WebFetch via the `llm` interface — Phase 5 pulled forward for predictions only, with a tool-free fallback) and **reads the track record** of past graded calls (`ledger.track_record`) + lessons to calibrate, and every call carries a **meaningful numeric `confidence` (0–100)** + `confidence_rationale`. Email "The call" block shows `horizon` then the claim with a color-graded confidence chip.)_
- [x] `market.py` — outcome data: `yfinance` for prices (with `finnhub-python` fallback), FRED for data outcomes. _(`close_on`/`latest_close`/`move_since`/`daily_move` (yfinance primary, Finnhub fallback for current quote) + `fred_latest`. Every accessor degrades to None on failure. Live-verified against META/SPY/QQQ + DGS10.)_
- [x] `grade.py` — strict, data-grounded grading. Load this morning's predictions plus any long-horizon ones now due; mark right/wrong/partial with why, anchored to real prices/data. _(`grade_due` gathers real outcome data per prediction (price move / FRED reading), then one strict LLM pass returns right/wrong/partial + outcome + why; vagueness counts as a miss. LLM failure leaves predictions open rather than fabricating verdicts. Verified on real META (right) and a contrived QQQ miss (wrong).)_
- [x] Lessons distillation — when the PM finds misses, write concise, generalizable rules into the lessons file; keep it curated and small. _(`grade.distill_lessons`: only misses/partials trigger it; the model merges/dedupes/cuts to ~8 bullets and returns the full file, which overwrites verbatim. Parser tolerates a stray fence/preamble before the `# Lessons` heading.)_
- [x] `pm_debrief.py` — PM email: open with the prediction grades, then the market wrap (what moved + why), ~2 items, and the learning piece (anything, guaranteed-novel). Subject `PM Debrief | M/D/YY`. Archive it. _(Gate → grade due → distill lessons → **fresh PM fetch** → compose → build → send/preview → archive `-pm.md`. Same flags as AM: `--no-send`/`--force`/`--to`. `debrief.py` reuses the AM curator for ~2 items; **wrap+TL;DR and the learning piece are two separate small LLM calls** — split after a single combined JSON call truncated. Email: shared page shell, verdict-pill scorecard, market-wrap section, "Something New" block, PM "Discuss in Claude" prefill.)_
- [x] Run AM → PM end-to-end by hand across a few days; confirm the loop reads/writes state correctly. _(Validated end-to-end 6/19 in `--no-send --force` (Juneteenth holiday): AM produced 3 lean items + 5 sharp anchored predictions appended to the ledger; PM graded a same-day call strictly against real prices, produced a clean scorecard + curated wrap + a novel learning piece ("The Triffin Dilemma"). Test ledger/lessons writes were then restored to blank. **Live trading-day run confirmed 6/22–6/23: AM made a real same-day call; PM graded it against the real close. Loop verified end-to-end. Phase 2 done.**)_

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

- [~] Give the LLM real tools through the swappable interface — web search first. _(Partially done early: the **AM prediction step** already researches via WebSearch/WebFetch through `llm.complete(..., allowed_tools=...)`. Remaining Phase 5 work: extend agentic tool use to curation/grading and let it iterate/chase threads, not just predict.)_
- [ ] Let it decide what to chase and iterate (pull threads, verify, dig) rather than only summarizing what it's handed.
- [ ] Keep everything above intact — this is an upgrade to the curation/prediction brain, not a rewrite.

---

## Open items (resolve before the relevant step)

- None currently outstanding. (Send times, sources, and Reuters are all decided — see `CLAUDE.md`.) The owner intends to add specific watchlist tickers/ETFs later; the watchlist must stay a one-line-edit config list.
