# CLAUDE.md

Context for Claude Code working in this repo. Read fully before making changes.

## What this project is

A personal Python automation that emails its owner a curated, twice-daily news digest on **trading days only** (weekdays minus US market holidays). Two emails:

- **AM Briefing** — forward-looking, sent before market open.
- **PM Debrief** — recap + learning, sent in the evening.

Purpose: sharpen the owner's investing decisions (mix of ETFs + individual stocks) and teach them something new daily. The defining feature is a **prediction/feedback loop** that improves over time by accumulating a track record and distilled lessons.

This is a learning project as much as a tool — favor clear, readable code over cleverness.

## Core principles (apply to every decision)

- **Lean is a feature.** The owner explicitly does NOT want a firehose. ~3 items in the AM, ~2 in the PM. When unsure whether to include something, cut it.
- **Just the facts, no filler.** Curation must aggressively drop fluff and low-signal "filler" stories.
- **No AI slop in the tech section.** Surface genuine breakthroughs (research, hardware, science); filter out AI hype and product-launch churn.
- **Preserve real articles.** Each item keeps headline + source link + 2–3 key points pulled from the actual piece. Do NOT replace articles with lossy summaries. Do NOT reproduce full copyrighted article text — key points + link only.
- **Strict, data-grounded grading.** When the PM run grades predictions, anchor verdicts to real prices/data, never to the model's own vibes. A model grading its own homework must not be lenient.
- **Recency first.** Always prioritize the most recent articles and freshest data over older items. When stories compete for a slot, newer wins; stale news gets deprioritized or dropped. This applies at both the fetch stage (prefer the latest) and the curation stage (rank by recency alongside relevance).

## Cost & runtime constraints (critical — do not violate)

- Runs on the owner's everyday machine via a scheduler, trading days only.
- **LLM calls go through Claude Code under the owner's Max subscription.** **NEVER set `ANTHROPIC_API_KEY` in the runtime environment** — doing so silently bills the pay-as-you-go API instead of the subscription. Staying on the subscription is a hard requirement.
- Put every LLM call behind a **single swappable interface** (one module/function), so it can be moved to the Anthropic API later if subscription billing for headless use changes.
- **Schedule (Eastern Time):** AM Briefing at **7:45 AM ET**, PM Debrief at **5:00 PM ET**, trading days only. Schedule against the `America/New_York` timezone — NOT a fixed UTC offset — so it stays correct across the EDT/EST switch.

## Architecture — the daily loop

**AM Briefing run:** read `lessons_active` → fetch news → curate items + make predictions → append predictions to `ledger` → send email → write to `archive`.

**PM Debrief run:** load this morning's predictions (plus any long-horizon ones now due) → fetch market/data outcomes → grade strictly (right/wrong/partial + why) → **if there were any misses**, run one LLM call to update lessons (distill new rules, confirm existing ones, select active view) → build market wrap + learning piece → send email → write to `archive`.

Persistent state is the system's memory and the reason it improves — treat it as the source of truth:

- `ledger` — every prediction: date, item, the call, horizon, status, outcome, why.
- `lessons_log` — **append-only master log** of every lesson ever distilled. Each entry: `id`, `text`, `created`, `last_confirmed`, `sources` (ledger IDs), `outcome_count`. Entries are NEVER deleted — only updated (outcome_count / last_confirmed incremented on confirmation). The master log grows over time and is the durable record.
- `lessons_active` — **curated active view** (~8 lessons selected from the master log by the PM run). This is the only file the AM Briefing ingests. Evicting a lesson from the active view does NOT remove it from the master log.
- `archive` — full sent emails, dated.

**Lessons gating rule:** The PM run only triggers the lessons LLM call when there are actual misses/partials in that run's graded predictions. If all predictions graded "right" (or none came due), both lessons files are left untouched — no re-running on stable data.

## Target repo structure

```
config.*            # watchlist, sectors, sources, send times — source of truth
am_briefing.py      # AM entrypoint
pm_debrief.py       # PM entrypoint
src/
  fetch.py          # RSS + API source fetching
  extract.py        # article key-point extraction
  llm.py            # SINGLE swappable LLM interface
  predict.py        # prediction + horizon logic
  grade.py          # strict grading + lessons update (update_lessons)
  market.py         # price/data lookups
  calendar.py       # trading-day / holiday gate
  email.py          # HTML email build + Gmail send
  ledger.py         # read/write ledger + two-file lessons system
  dedup.py          # rolling seen-story deduplication
data/
  ledger.example.json           # committed blank template
  lessons_log.example.json      # committed blank template (master log)
  lessons_active.example.md     # committed blank template (active view)
  ledger.json                   # gitignored: real predictions (private)
  lessons_log.json              # gitignored: append-only master lessons log (private)
  lessons_active.md             # gitignored: curated ~8-lesson active view (private)
  seen.json                     # gitignored: rolling 7-day story dedup cache
  archive/.gitkeep              # committed (keeps the folder)
  archive/YYYY-MM-DD-am.md (and -pm.md)  # gitignored: full sent emails (private)
.env                # gitignored: API keys, Gmail app password
```

**Note on the old `lessons.md`:** Still gitignored for legacy reasons. On first run after the upgrade, `ledger.py` automatically migrates its content into `lessons_active.md`. The file itself is not deleted but is no longer read or written by any code.

**Privacy (decided in Phase 0):** the ledger, lessons, and archive hold the
owner's personal track record and full emails — their real files are **gitignored**
and stay local. Only blank `*.example.*` templates and `archive/.gitkeep` are
committed, so the repo structure is visible on GitHub without exposing data.
Code must create a real file from its template on first run if missing. The
"Open in Claude" button does NOT depend on the archive (each email carries its
digest in the link). State is still the source of truth — just stored locally,
not pushed.

Config lives in `config.toml` (read via the stdlib `tomllib`, no extra dep).
Keep the watchlist, sectors, sources, and send times in `config.toml`, never hardcoded in code.

## Content & format rules

- Three pillars: **Politics** (worldwide, mostly US), **Technology** (real breakthroughs, not AI slop), **Economy** (serious US metrics — inflation, rates, jobs, GDP).
- Per item: headline + link + 2–3 key points + a one-line "why it matters / application" (doubles as a signal-vs-noise read) + a prediction.
- A short **TL;DR summary** at the very top of every email (for skim-back).
- An **"Open in Claude" button** that opens a new chat preloaded with the day's digest, defaulting to the most recent email.
- Subjects: `AM Briefing | M/D/YY` and `PM Debrief | M/D/YY` (rolling dates). AM and PM are labeled separately in Gmail by the owner.

## Prediction horizons (locked)

same-day (by close), 1 week, 1 month, 1 quarter, 6 months, 1 year. The model picks the appropriate horizon(s) per item — match the horizon to the item (intraday news ≠ 1-year call).

## Personalization

- Sector focus (8, prioritization signal, not a hard filter): technology, healthcare, consumer discretionary, energy, industrials, utilities, materials, financials.
- Watchlist: currently Meta + Alphabet. It MUST stay a trivially-editable list — adding a ticker/ETF later should be a one-line config edit with no code changes.

## Tech stack

Python · `feedparser` (RSS) · `trafilatura` (article extraction) · `fredapi` (economic data) · `yfinance` (prices, primary) + `finnhub-python` (backup) · `pandas-market-calendars` (holiday gate) · Claude Code headless for the LLM step · `yagmail`/`smtplib` + Gmail app password (HTML email) · cron / Task Scheduler · Git + JSON (ledger/lessons) + Markdown (archive) · `python-dotenv`.

## Sources

- Wires: AP News (native RSS) is the primary backbone, **plus Reuters** for additional quality articles. Reuters' native RSS is unreliable, so pull it through a feed generator (e.g. rss.app / newsloth) rather than expecting a clean official feed.
- Economic: FRED API + Fed/BLS/Census release calendars.
- Tech: Ars Technica + IEEE Spectrum (native RSS).
- Prices: yfinance, Finnhub backup.

## Build plan

The full, ordered build sequence lives in **`PLAN.md`**. Work through it top to bottom, check items off as you complete them, and keep it current. Consult `PLAN.md` before starting any new piece of work, and consult this file (`CLAUDE.md`) for the rules and constraints that govern *how* each piece is built.

## Open items (ask, don't assume)

- Don't add sources or features beyond this spec without checking — leanness is intentional.
