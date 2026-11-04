# AI Infrastructure Intelligence Brief

A daily, source-verified intelligence brief on AI infrastructure markets (AI
compute and cloud, power and energy, data center construction, and chips and
hardware), **prepared for a target company you choose**. The target is a
**profile**: one YAML file that says who the brief is for, what to look for,
and what to weigh. **[Crusoe](https://www.crusoe.ai) is the first demo
profile** (and the default); [adding another company](#adding-a-new-company)
takes one config file and no code changes.

Every morning (6:00 a.m. Mountain) it collects news from free feeds, ranks it
with Claude, writes a short brief, **checks in code that every link in the
brief points to an article it actually collected**, and commits the result to
[`briefs/<profile>/`](briefs/). If it can't verify anything, it publishes a "no verified
brief today" note instead of an unsupported brief.

**Design principle:** it augments judgment, it doesn't replace it. The brief
says what happened, why it might matter, and how confident the sourcing is.
The conclusion stays with the reader.

Full requirements: [`SPEC.md`](SPEC.md).

## What the brief looks like

```
# AI Infrastructure Intelligence Brief — prepared for Crusoe

*November 4, 2026*

## Top 3 developments
**1.**
- What happened:          one or two sentences, facts from the article only
- Why it matters to Crusoe: the part of the company's business affected, the
                            mechanism, and what to watch next
- Confidence:             Confirmed | Reported
- Source:                 [Article title](link) (Publisher)
...
## Watchlist roundup      3–6 one-line items by market, each with a link
## Noise we ignored       3–5 skipped items, each with a one-line reason
---
Articles scanned · kept · sources that failed to load
```

**Confirmed** means the story itself shows a company earnings report or press
release, an SEC or other filing, or an official election or regulatory result.
**Reported** means anonymous sources, "reportedly" stories, analyst estimates,
or the outlet's own analysis. When in doubt, it's Reported.

## How it works

One Python pipeline, four commands, run in order by GitHub Actions:

| Step | Command | What it does | Output (git-ignored `data/<profile>/`) |
|---|---|---|---|
| 1. Fetch | `python -m src.fetch` | Reads every feed in `sources.yaml` (plus the profile's own Google News searches), keeps items from the last 48 hours, **deduplicates** (same link, or titles ≥ 85% alike), and **filters** to items that mention a watchlist term (shared `watchlist.yaml` terms plus the profile's). A failed or empty feed is logged and skipped; it never stops the run. | `YYYY-MM-DD_raw.json` |
| 2. Rank | `python -m src.rank` | Claude scores each item 1–5 (relevance to the target company, novelty, source quality) with a one-line reason, and groups items into **stories**. A story covered by 3+ outlets gets a +1 boost; only its best article is a candidate, so wide coverage raises a story instead of crowding out others. | `YYYY-MM-DD_scores.json` |
| 3. Write | `python -m src.write` | Claude writes the brief as structured data from the strongest stories. Our code renders the exact format, enforces one story per top/watchlist slot, and fills in the footer from the collected data. | `YYYY-MM-DD_brief.json` + a draft `.md` |
| 4. Verify | `python -m src.verify` | **A code check, not an AI check.** See below. | `briefs/<profile>/YYYY-MM-DD.md` |

Then the workflow commits `briefs/<profile>/YYYY-MM-DD.md` (for the demo profile: `briefs/crusoe/`).

### Where the configuration lives (all editable, no code changes)

| File | Scope | What it holds |
|---|---|---|
| [`watchlist.yaml`](watchlist.yaml) | shared | The four industry markets and the terms that make an item relevant. |
| [`sources.yaml`](sources.yaml) | shared | The RSS feeds and the general industry Google News searches. |
| [`profiles/crusoe.yaml`](profiles/crusoe.yaml) | one company | Company name and description, customers, competitors, the parts of its business a story can affect, key facts, always-relevant terms, and its own Google News searches. |
| `TARGET_PROFILE` | setting | Which profile to use. Environment variable locally, repository variable on GitHub. Default: `crusoe`. |

The code contains no company name. The ranker prompt, the writer prompt, the
brief title, and the "Why it matters to ..." label are all filled in from the
profile. The profile's facts are background, not article facts: the writer may
use them to explain why something matters, and is told never to present one as
something an article said.

## Adding a new company

1. **Copy the template:** `cp profiles/_template.yaml profiles/acme.yaml`. The
   name is lowercase letters, digits, `-` or `_`; it is what you will put in
   `TARGET_PROFILE`. (Files starting with `_` can't be selected.)
2. **Fill it in:**
   - `company`: `name` (appears in the title), a one-line `description`,
     `customers`, `competitors`, and `business_areas` (the parts of its
     business a story can affect, e.g. `[generation, transmission, retail]`).
   - `facts`: verified background, one per line: capacity, sites, contracts,
     products, plans. Mark anything unconfirmed as reported. Keep these
     accurate: they steer the ranking and the "why it matters" text.
   - `watchlist_terms`: names, people, and products whose mention is always
     relevant to this company.
   - `google_news_terms`: searches that only this company needs. The shared
     industry searches in `sources.yaml` are added automatically.
3. **Try it locally:**
   ```bash
   export TARGET_PROFILE=acme
   python -m src.check_feeds                      # does it find the right feeds?
   python -m src.fetch && python -m src.rank && python -m src.write && python -m src.verify
   ```
   A missing or incomplete profile stops the run with a message that says what
   is wrong and which profiles exist.
4. **Use it on GitHub:** Settings → Secrets and variables → Actions →
   **Variables** → New repository variable named `TARGET_PROFILE` with value
   `acme`. Delete the variable (or leave it empty) to go back to `crusoe`.
5. **Check the first brief by eye** (`briefs/acme/YYYY-MM-DD.md`). Do the top stories make sense for this
   company? If a story is missing, add a term to its `watchlist_terms`; if
   noise gets through, tighten them.

Output is kept per profile: briefs go to `briefs/<profile>/YYYY-MM-DD.md` and
working files to `data/<profile>/`, so profiles never overwrite each other. The
scheduled workflow builds the one profile named by `TARGET_PROFILE`; to get
briefs for several companies each day you would run the pipeline once per
profile (see limitations).

## How verification works

The model can make mistakes, including inventing a link, so the last step is
ordinary code (`src/verify.py`) that the model cannot influence:

1. **Source check.** Every link in the brief (top developments, watchlist, and
   noise) must match an article collected in step 1. Links are compared after
   harmless normalization (trailing slash, `utm_` tags, letter case in the
   host). An item with a missing or unmatched link is **removed**, and the
   removal is **logged** (section, link, reason, a text snippet) to the
   workflow log and `data/<profile>/YYYY-MM-DD_verification.json`. A link that is one
   character off is removed, not trusted.
2. **Fail closed.** If collection returned nothing, the draft is missing, or
   **no top development survives** the check, the file written is a short
   "**No verified brief today**" note with the reason and the footer counts.
   The brief is never published with unsupported claims.
3. **Claim check (prompt rule).** The writer may only use facts present in the
   supplied article text and must label anything uncertain as Reported. This
   part is a rule given to the model, not something code can prove (see
   limitations).

The verify step runs even if an earlier step crashed, so a failure still
produces the "no verified brief" note rather than nothing.

## Setup

1. **Python 3.12+**, then `pip install -r requirements.txt`
   (`feedparser`, `pyyaml`, `anthropic`, `pytest`).
2. **API key.** The key is read from the `ANTHROPIC_API_KEY` environment
   variable and is **never in code or config**.
   - On GitHub: Settings → Secrets and variables → Actions → New repository
     secret, named `ANTHROPIC_API_KEY`.
3. **Pick the company** (optional): set `TARGET_PROFILE` (default `crusoe`); see
   [Adding a new company](#adding-a-new-company).
   - Locally: `export ANTHROPIC_API_KEY=...` (or keep it in a git-ignored `.env`).
4. **Let the workflow commit.** The daily workflow pushes to the branch it runs
   on using the built-in token. If `main` has branch protection, allow
   GitHub Actions to push there, or the commit step will fail.

### Run it

```bash
python -m pytest -q          # offline, no API key needed
python -m src.check_feeds    # check every feed URL returns items
python -m src.fetch && python -m src.rank && python -m src.write && python -m src.verify
```

On GitHub: **Actions → Daily brief → Run workflow** for a manual run. It also
runs on schedule. GitHub's cron is UTC and ignores daylight saving, so the
workflow fires at both 12:00 and 13:00 UTC and a "gate" step lets through only
the run that lands on 6:00 a.m. in Denver. The **Check feeds** workflow tests
all feed URLs from GitHub's runners; the check passes if at least half work and
prints which ones don't.

## Tests

`python -m pytest -q`. All offline: Claude is replaced by stubs and feeds are
saved samples under `tests/samples/`. They cover:

- **Dedup** (same link, tracking params, similar titles), **filtering**
  (whole-word matching, recorded matched terms), the 48-hour window.
- **Failed and empty feeds:** one dead feed never stops the run, and an empty
  feed counts as a failure.
- **Ranking:** score validation, story grouping and the coverage boost.
- **Writing:** exact output format, section limits, one story per slot.
- **Verification:** a **deliberately fake link** is removed and logged,
  missing and near-miss links are removed, and the pipeline **fails closed**
  when feeds return nothing or the check removes every top item.
- **Profiles:** the default is Crusoe, `TARGET_PROFILE` switches company terms
  and searches, bad or incomplete profiles fail with a clear message, profile
  names can't escape the `profiles/` folder, and the prompts, schema and title
  contain no trace of Crusoe when another profile is selected (plus a check that
  no company name is hardcoded in the code).
- An end-to-end test where the "writer" invents a link and it never reaches the
  published brief; and checks that the workflow files are valid and wired as intended.

## Known limitations

- **Paywalled sources and stories that never reach free feeds** are invisible.
- **Rumors that look like news.** The Reported label helps, but the model
  decides it, and a confident-sounding outlet can still be wrong.
- **One profile per workflow run.** Output folders are per profile, but the
  scheduled workflow only builds the profile named by `TARGET_PROFILE`. Running
  several companies every day needs a workflow matrix over profiles, which is
  not built yet.
- **A profile is only as good as its facts.** They are supplied by a person and
  not checked; stale or wrong facts will skew the ranking and "why it matters".
  The shared markets and feeds are tuned for AI infrastructure; a company
  outside it would need new shared terms too.
- **Important stories that don't use watchlist terms** are filtered out before
  Claude ever sees them. Review `watchlist.yaml` as the markets change.
- **"Why it matters" is a judgment call** and should be reviewed by a person.
  It is explicitly framed as inference, but it is the model's inference.
- **Verification proves a link was collected, not that a sentence is accurate.**
  A real link attached to a slightly wrong summary passes the source check. The
  claim check is a prompt rule plus the structure of the pipeline, not a proof.
- **Google News links.** Most are redirects and can't be resolved to the
  publisher's page offline (newer ones are encrypted), so the brief links to
  Google's redirect and shows the publisher name beside it. When a link can be
  decoded, the publisher URL is used.
- **Feed coverage.** Data Center Frontier and The Register's data centre feed
  were dropped because no working RSS URL could be confirmed (the candidates are
  noted in `sources.yaml`). Some feeds may fail or move at any time; the footer
  lists the ones that failed that day.
- **Story grouping and confidence labels come from the model**; they are
  checked for shape in code, not for correctness.
- **Undated items are skipped** (if a feed doesn't say when something was
  published, we can't show it is recent), and at most 100 items per day are
  ranked (the newest).
- **No eval set yet.** SPEC.md calls for 20 hand-labeled headlines
  (`evals/labeled_headlines.yaml`) and a script that measures how often the
  ranker agrees. That is not built in v1; ranking quality has been judged by
  eye.

## What's next

- **SEC filings.** EDGAR feeds for CoreWeave, Nebius, and Oracle were cut from
  v1. The SEC rejects requests without a descriptive User-Agent that includes
  contact info, so adding them means setting a `SEC_USER_AGENT` secret (e.g.
  `ai-infra-intel-brief you@example.com`) and sending it with those requests.
- **The eval set** described above, re-run after every prompt change.
- More profiles, and a workflow matrix so several companies run side by side
  each morning.
- Primary-source monitoring beyond filings: regulator dockets and interconnection queues.
- A structured market map of companies, customers, and capacity.
- Weekly trend summaries.
- Email delivery (e.g., Resend).
