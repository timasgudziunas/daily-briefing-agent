# News Digest Automation — Build Spec

A twice-daily curated news email (**AM Briefing** + **PM Debrief**), trading days only, built to sharpen investing decisions (mix of ETFs + individual stocks, aiming for consistent returns) while learning something genuinely new every day. Lean by design — never a firehose.

---

## 1. Delivery & cadence

- Email delivered via **Gmail**.
- Sent on **trading days only** — weekdays Mon–Fri, automatically skipping NYSE market holidays.
- **AM Briefing** before market open, **PM Debrief** in the evening. Exact times TBD.
- Subject lines: `AM Briefing | M/D/YY` and `PM Debrief | M/D/YY`, dates rolling automatically.
- AM and PM go to **different Gmail labels** (set up via Gmail filters by you).

## 2. Shared email features (both emails)

- **Top TL;DR summary** — a few punchy lines at the very top capturing the day's takeaways, so skimming back through old emails is fast.
- Content organized by **3 pillars**:
  - **Politics** — worldwide, weighted to the US.
  - **Technology** — newest *genuine* breakthroughs; explicitly filters out AI hype / filler.
  - **Economy** — serious metrics only (inflation, rates, jobs, GDP), mostly US.
- **Per item:** headline + source link + 2–3 key points pulling the *real article substance* (not a lossy summary) + a one-line **"why it matters / real-world application"** (which doubles as the signal-vs-noise read).
- **Strict no-filler curation** — the LLM is instructed to drop fluff and only surface what's materially relevant.
- **"Open in Claude" button** — opens a new Claude chat preloaded with the day's digest, defaulting to the most recent email unless told otherwise.
- Every email is **saved to the archive**.

## 3. AM Briefing (forward-looking)

- ~3 items, roughly one per pillar.
- A one-line **"what to watch today"** plus the day's **economic release calendar** (CPI, jobs, Fed, etc.) so nothing blindsides you.
- For **each item**, a concrete **prediction** at the appropriate horizon(s), written to the ledger.
- **Reads the lessons file first**, so past mistakes shape today's calls.

## 4. PM Debrief (recap + learning)

- **Opens by grading that morning's predictions** — right / wrong / partial, *with the why*, graded strictly against real outcomes (prices, data), not vibes.
- **Sweeps the ledger** for older long-horizon predictions now coming due and grades them.
- **Distills new lessons** into the lessons file when it finds misses.
- **Market wrap** — what moved today and the real why (built to help you spot patterns yourself).
- ~2 items, plus notable after-hours/earnings items as relevant.
- **Learning piece** — about *absolutely anything* (any domain), guaranteed to teach you something you almost certainly didn't know. Not investing-scoped.

## 5. Prediction & feedback loop (the core engine)

- **Prediction horizons (locked):** same-day (by close), 1 week, 1 month, 1 quarter, 6 months, 1 year. The model picks the right horizon(s) per item.
- **Ledger file** — every prediction: date, item, the call, horizon, status, outcome, and why.
- **Lessons file** — distilled, curated, generalizable rules; kept small; fed back into AM runs.
- **How it "gets smarter":** in-context learning via an accumulating track record + distilled lessons — *not* model retraining. Real but bounded improvement; markets cap how "right" anything can get, so the deeper payoff is sharpening *your* judgment.

## 6. Personalization

- **Sector focus (8):** technology, healthcare, consumer discretionary, energy, industrials, utilities, materials, financials. Used as a *prioritization signal*, not a hard filter.
- **Watchlist:** Meta + Alphabet for now. Kept minimal on purpose (learning-first). Built as a **simple editable config list** — add any stock/ETF later with a one-line edit, no rework.

## 7. Storage & archive

- A **Git repo** holds the three persistent files: **ledger**, **lessons**, and **archive** (full sent emails as dated markdown).
- Powers the "Open in Claude" button and your own skim-back.
- Optional later: connect the repo to a **Claude Project** so all past briefings are on tap in normal chats.

## 8. Scheduling & runtime

- Runs on your **everyday machine** with **"wake to run"** enabled as a safety net for the AM slot.
- A **trading-day check** (skip weekends + holidays) gates every run.
- **Cost:** stays on your **Max plan** — Claude Code logged in with your subscription, **no `ANTHROPIC_API_KEY` set** (which would silently bill the API). The LLM step is kept **swappable** in case the (currently paused) Agent-SDK billing change takes effect later.

## 9. Sources (recommended set)

- **Wires:** AP News (native RSS) as the backbone; Reuters optional (via a feed generator, since its native RSS is unreliable).
- **Economic:** FRED API (aggregates CPI, GDP, PCE, yields, unemployment) + Fed/BLS/Census release calendars for timing.
- **Technology:** Ars Technica + IEEE Spectrum (native RSS).
- **Market prices:** yfinance (free daily closes) with Finnhub free tier as backup.

---

## 10. Recommended tech stack

| Job | Tool |
|---|---|
| Language | **Python** |
| RSS fetching | `feedparser` |
| Article text extraction | `trafilatura` (pull key points from linked articles) |
| Economic data | FRED API via `fredapi` (free key) |
| Market prices | `yfinance` (primary), `finnhub-python` (backup) |
| Trading-day / holiday check | `pandas-market-calendars` |
| LLM (curate / predict / grade) | **Claude via Claude Code headless** (`claude -p`) under Max login — swappable to the Anthropic API later |
| Email send | `yagmail` (or `smtplib`) + Gmail app password; HTML email |
| Scheduling | `cron` (Mac/Linux) or Task Scheduler (Windows), wake-to-run enabled |
| State + storage | Git repo; **JSON** for ledger + lessons; dated **Markdown** for the archive |
| Secrets & config | `python-dotenv` for keys/app password; a simple config file for watchlist, sectors, sources, send times |

---

## 11. Build phases

1. **MVP (stage one):** fetch → curate with one LLM call → email → save. Run by hand first, then schedule. Then layer in the prediction ledger + lessons loop.
2. **Stage two (agentic — your learning goal):** give the LLM real tools — web search, the ability to decide what to chase and iterate — turning it from "summarizing what it's fed" into "going and finding what matters."
