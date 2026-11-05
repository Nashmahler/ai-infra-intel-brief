# AI Infrastructure Intelligence Brief

<!-- latest-brief:start -->
**Latest brief — Crusoe:** [November 5, 2026](briefs/crusoe/2026-11-05.md) · [all briefs](briefs/crusoe/README.md) <!--profile:crusoe-->
<!-- latest-brief:end -->

A daily, source-verified intelligence brief on AI infrastructure markets (AI
compute and cloud, power and energy, data center construction, and chips and
hardware), **prepared for a target company you choose**. The target is a
**profile**: one YAML file that says who the brief is for, what to look for,
and what to weigh. **[Crusoe](https://www.crusoe.ai) is the first demo
profile** (and the default); [adding another company](#adding-a-new-company)
takes one config file and no code changes.

Every morning (from 6:00 a.m. Mountain) it collects news from free feeds, ranks it
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
- Business impact:        Direction (Opportunity | Risk), Channel (one of five),
                          Size (a stated figure, else "unsized"), Consider (one
                          specific option or question for the company)
- Confidence:             Confirmed | Reported
- Source:                 [Article title](link) (Publisher)
- Evidence (small print): a short quote from the article that supports
                          "What happened", checked in code
...
## Watchlist roundup      3–6 one-line items by market, each with a link
## Noise we ignored       3–5 skipped items, each with a one-line reason
## This week's themes   Fridays only: 3 themes, each citing the daily briefs
## Opportunities         Fridays only: customers, distressed assets or power
                          contracts, partnerships, pricing signals
---
Articles scanned · kept · failed sources · top stories with full text vs summary only
```

**Confirmed** means the story itself shows a company earnings report or press
release, an SEC or other filing, or an official election or regulatory result.
**Reported** means anonymous sources, "reportedly" stories, analyst estimates,
or the outlet's own analysis. When in doubt, it's Reported.

## How it works

One Python pipeline, run in order by GitHub Actions:

| Step | Command | What it does | Output (git-ignored `data/<profile>/`) |
|---|---|---|---|
| 1. Fetch | `python -m src.fetch` | Reads every feed in `sources.yaml` (plus the profile's own Google News searches), keeps items from the last 48 hours, **deduplicates** (same link, or titles ≥ 85% alike), and **filters** to items that mention a watchlist term (shared `watchlist.yaml` terms plus the profile's). A failed or empty feed is logged and skipped; it never stops the run. | `YYYY-MM-DD_raw.json` |
| 2. Rank | `python -m src.rank` | Claude scores each item 1–5 (relevance to the target company, novelty, source quality) with a one-line reason, and groups items into **stories**. A story covered by 3+ outlets gets a +1 boost; only its best article is a candidate, so wide coverage raises a story instead of crowding out others. | `YYYY-MM-DD_scores.json` |
| 3. Decode | `python -m src.decode` | Decodes **Google News links to publisher URLs for the top 60 ranked items only** (see below). Never blocks the brief; logs a warning if Google starts refusing. | updates `_raw.json` and `_scores.json`; `YYYY-MM-DD_decode.json` |
| 4. Full text | `python -m src.fulltext` | Tries to fetch the full article text of the 10 strongest stories, **obeying robots.txt** and skipping paywalled or blocked pages, pages with almost no text, and Google News redirect links. Anything that can't be fetched falls back to the RSS summary, and the reason is recorded. | `YYYY-MM-DD_fulltext.json` |
| 5. Write | `python -m src.write` | Claude writes the brief as structured data from the strongest stories, including a **short supporting quote** (4–24 words) for each "What happened". Our code renders the exact format, enforces one story per top/watchlist slot, and fills in the footer from the collected data. | `YYYY-MM-DD_brief.json` + a draft `.md` |
| 6. Verify | `python -m src.verify` | **A code check, not an AI check.** Links and quotes. See below. | `briefs/<profile>/YYYY-MM-DD.md` |
| 7. Weekly | `python -m src.weekly` | **Fridays only** (or on request): reads the week's verified briefs and adds **"This week's themes"** (3 themes, each citing the daily briefs it draws on) and **"Opportunities"** (potential customers, distressed assets or power contracts, partnerships, pricing signals; each citing one daily brief with a quote), verified in code. | adds a section to today's brief |
| 8. Index | `python -m src.index` | Rebuilds `briefs/<profile>/README.md` (every brief, newest first) and the **Latest brief** link at the top of this README. | `briefs/<profile>/README.md`, `README.md` |

Then the workflow commits `briefs/<profile>/` (for the demo profile: `briefs/crusoe/`) and the README. The weekly and index steps never block the daily brief: if either fails, the brief is committed as it was.

**Dates.** Briefs and data folders are named by the **America/Denver** date, not
the UTC date: a 5 p.m. Mountain run on Nov 4 is already Nov 5 in UTC, and used to
produce a Nov 5 brief. The 6 a.m. Mountain schedule lands on the same calendar day
in both zones all year; the Friday check for the weekly section uses the Denver date too.

**Google News links.** Most stories arrive as Google News redirect links. Right
after ranking, the decode step turns the links of the **top 60 ranked items** into
publisher URLs with the [`googlenewsdecoder`](https://pypi.org/project/googlenewsdecoder/)
package, best-ranked first, one request per second, at most 5 minutes per run, and it
stops early if Google refuses 5 in a row. Ranking comes first so Google requests are
spent only on stories that can reach the brief. The decoded URL is the story's `link`
(used for full-text fetching and for display); the Google link is kept as
`original_link` in both the raw and scores files, so **both count as collected for
verification**. A link that can't be decoded keeps its original Google link and is
shown with the publisher name. If decoding starts failing, the step logs it at once
(`::warning::` lines on the run page: how many links had worked, the reason, and
when it gave up) and records the reasons in `YYYY-MM-DD_decode.json`.
The footer reports how many of the brief's top stories had full article text versus
summary only.

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
   python -m src.fetch && python -m src.rank && python -m src.fulltext && python -m src.write && python -m src.verify
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
2. **Quote check.** Each top development's supporting quote must appear **word
   for word** in the text we actually hold: the fetched article if we have it,
   otherwise the RSS title and summary. Only meaningless differences are
   forgiven (whitespace, curly vs straight quotes, dash styles); case,
   wording, and order must match, a quote can't splice two passages, and it
   must be 4–24 words. A missing, malformed, or non-matching quote **removes
   the item** (logged with the quote). A **Confirmed** label also needs the
   quote to come from the full article; if only the RSS summary backs it, the
   label is **downgraded to Reported** (also logged). The brief's small
   "Evidence" line shows the quote and whether it came from the article text or
   the RSS summary.
3. **Fail closed.** If collection returned nothing, the draft is missing, or
   **no top development survives** the checks, the file written is a short
   "**No verified brief today**" note with the reason and the footer counts.
   The brief is never published with unsupported claims.
4. **Claim check (prompt rule).** The writer may only use facts present in the
   supplied article text and must label anything uncertain as Reported. The
   quote check makes this much harder to fake, but it is still a rule given to
   the model, not something code can prove (see limitations).

**The business-impact line is checked too.** Direction must be Opportunity or Risk
and Channel one of the five allowed values (Revenue & pricing; Costs & margins;
Financing & cost of capital; Customers & pipeline; Siting & timeline), otherwise
the item is removed. **Size** may only be a figure copied word for word from **the
story's own quote**, one that itself passes the quote check. **Company-profile
figures (such as a campus capacity) never count as a Size**: they describe the
company's exposure, not how big the story is, so they belong in "Why it matters",
where they are still welcome. An invented, estimated, rounded, rewritten, vague, or
profile-sourced amount is reset to exactly **"unsized"** (and logged), and the item
keeps its other fields. The figure's quote is shown in the Evidence line.

**Weekly sections follow the same rules.** Each theme must cite at least two
different daily briefs, and every cited date must be a brief that was actually
read (unmatched citations are removed). Each theme also needs a verbatim quote
from one of the briefs it cites. Each **opportunity** cites one daily brief with a
verbatim quote from it, has one of four categories, and may contain a number only if
that number appears in the brief it cites. Anything that fails is dropped and
logged; if nothing survives, the brief is left exactly as it was.

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
python -m src.fetch && python -m src.rank && python -m src.fulltext && python -m src.write && python -m src.verify
python -m src.weekly --force   # optional: add this week's themes now (otherwise Fridays only)
python -m src.index            # refresh the briefs index and the Latest brief link
python -m src.evaluate         # check the ranker against the hand labels (needs the API key)
```

On GitHub: **Actions → Daily brief → Run workflow** for a manual run (tick
**Also add this week's themes** to run the weekly synthesis on a day that isn't
a Friday; untick **Commit the brief to the repo** for a test run that leaves
nothing behind. The finished brief is printed into the run's log and summary). It also runs on schedule.

**How the schedule works.** GitHub's cron is UTC and ignores daylight saving, so
the workflow fires at both 12:00 and 13:00 UTC (6 a.m. Mountain in summer and in
winter respectively). GitHub can also start a scheduled run hours late, so a
"gate" step (`src/gate.py`) lets a scheduled run through **any time from 6:00 to
11:59 a.m. Denver, but only if `briefs/<profile>/<today>.md` isn't already on
`main`** (the date is the Denver date). That makes the second cron a safe retry:
whichever starts first builds the brief and commits it, and the other finds the
file and stops. Manual and push runs always proceed. The run page prints the
gate's reason ("outside 06:00-11:59", "today's brief already exists", ...).
A "No verified brief today" note counts as today's file, so it is not retried
by a later trigger, and if GitHub starts no scheduled run before noon Denver there is no brief that day.

The **Check feeds** workflow tests
all feed URLs from GitHub's runners; the check passes if at least half work and
prints which ones don't.

## The eval set

How well does the ranker's "this matters" judgment match a person's? The answer
lives in [`evals/labeled_headlines.yaml`](evals/labeled_headlines.yaml): **20 real
headlines**, each with its source, summary and link, labeled by hand as
**signal** (something the target company's strategy team would want to know) or
**noise** (not worth their attention). It was sampled from one day's ranked data,
about a third each from what the ranker scored 4-5, 2-3 and 1, then shuffled, with
**no scores stored in the file** so the labeler couldn't be nudged.

`python -m src.evaluate` (or **Actions → Ranker eval → Run workflow**, a few cents)
runs the real ranking step on exactly those headlines, treats **a score of 3 or more
as signal**, and reports:

- **agreement:** how often the ranker and the person said the same thing
- **false positives:** the ranker said signal, the person said noise (noise gets into the brief)
- **false negatives:** the ranker said noise, the person said signal (a story is missed)
- precision and recall, plus every headline with its score and the ranker's reason

**Re-run it after every change to the ranking prompt**, and compare with the last
result. The first run: **14/20 (70%) agreement, 3 false positives, 3 false
negatives**. The ranker was right on everything it scored 4-5 or 1, and all the
disagreements were in the middle; it also tended to mark down good stories from
low-tier outlets. Details and caveats: [`evals/results.md`](evals/results.md).

The sample was built by the **Eval sample** workflow (`python -m src.evalset`), which
refuses to overwrite a file that already has labels; to rebuild it, delete the file
first and expect to relabel.

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
- **Quote checks:** a **fabricated quote** (even on a real link) removes the
  item; quotes that are too short, too long, spliced, or the wrong case fail;
  curly quotes, odd dashes, and extra whitespace are forgiven; a Confirmed
  label backed only by the RSS summary is downgraded.
- **Full-text fetching:** robots.txt disallow (and an unreadable robots.txt)
  stops the request, paywall signals and stub pages fall back to the summary,
  Google News redirects are never scraped, and network errors never raise.
- **Dates:** the Denver date at the UTC boundary (a 5:18 p.m. Mountain run is still
  that day), midnight rollover in winter and summer, daylight-saving days, every
  step using the same helper, and no step computing a date from UTC itself.
- **Google News decoding:** only the top 60 ranked items are decoded, in rank order;
  decoded links become the link with the Google link kept in both files, failures
  keep the original, requests are spaced, a time budget and five failures in a row
  stop it, only Google links are sent, and decoded duplicates merge. **Failure
  logging:** a warning at the first failure (with how many links had worked), a
  warning when it gives up (with the last reason), the failure reasons counted, and
  no warnings when everything works.
- **Footer:** full-text vs summary-only counts for the top stories.
- **Business impact:** a model-invented dollar figure becomes "unsized" (with or
  without a fabricated quote), a figure must be copied exactly from the story's own
  quote, **every figure in the company profile is rejected as a Size** (with no quote,
  a real quote that lacks it, or a fabricated one) while staying untouched in "Why it
  matters", vague amounts are not figures, every allowed Direction and Channel is
  accepted and invalid ones remove the item.
- **Weekly themes and opportunities:** the last-seven-days window, failed days and the index file
  excluded, a fabricated quote or a citation to a brief that doesn't exist
  removes the theme, Friday-only gating with a manual override, and the brief is
  untouched when nothing survives.
- **Index and latest link:** newest-first listing, failed days marked, the
  README link sits under the title, replaces only its own profile's line, and
  is idempotent.
- **Profiles:** the default is Crusoe, `TARGET_PROFILE` switches company terms
  and searches, bad or incomplete profiles fail with a clear message, profile
  names can't escape the `profiles/` folder, and the prompts, schema and title
  contain no trace of Crusoe when another profile is selected (plus a check that
  no company name is hardcoded in the code).
- An end-to-end test where the "writer" invents a link and it never reaches the
  published brief; and checks that the workflow files are valid and wired as intended.

## Known limitations

- **Paywalled sources and stories that never reach free feeds** are invisible.
- **Full text is only sometimes available.** Anything blocked by robots.txt or a
  paywall, any page with little text, and any Google News link that could not be
  decoded is checked against the RSS title and summary instead. The Evidence line
  says which, and the footer counts how many top stories had full text. A story
  backed only by a summary can only be labeled Reported.
- **A matching quote proves the words exist in the text, not that the claim is
  right.** A real quote can still be summarized slightly wrong, or taken out of
  context. The reader still decides.
- **Weekly themes rest on the daily briefs, not the articles.** They are
  checked against the briefs they cite, so they can only be as good as those
  briefs, and they need at least two verified briefs in the last seven days.
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
- **"Why it matters", Direction, Channel, and Consider are judgment calls** and
  should be reviewed by a person. They are explicitly framed as inference, but
  they are the model's inference. Code checks that Direction and Channel are valid
  values and that Size is a stated figure, not that the choices are *right*, and
  "no generic advice" in Consider is a prompt rule, not something code can prove.
- **Size is deliberately conservative.** A figure must be copied exactly from the
  story's own verified quote, so a number the model rounded or restated
  ("$3.5B" for "$3.5 billion") becomes "unsized" even if it was correct. The
  weekly Opportunities have no Size field; their figures must appear in the cited brief.
- **Verification proves a link was collected, not that a sentence is accurate.**
  A real link attached to a slightly wrong summary passes the source check. The
  claim check is a prompt rule plus the structure of the pipeline, not a proof.
- **Google News decoding is unofficial.** It relies on a third-party package that
  talks to Google's own endpoints, which can change, block, or rate-limit us at any
  time. When it fails we keep the Google link (and show the publisher), so a bad day
  means less full text, not a broken brief. Decoding the top 60 links adds
  about a minute to a run.
- **Feed coverage.** Data Center Frontier and The Register's data centre feed
  were dropped because no working RSS URL could be confirmed (the candidates are
  noted in `sources.yaml`). Some feeds may fail or move at any time; the footer
  lists the ones that failed that day.
- **Story grouping and confidence labels come from the model**; they are
  checked for shape in code, not for correctness.
- **Undated items are skipped** (if a feed doesn't say when something was
  published, we can't show it is recent), and at most 100 items per day are
  ranked (the newest).
- **The eval set is small.** 20 headlines labeled by one person, and the ranker
  is not deterministic, so a change of one or two in the agreement number is noise
  (see [the eval set](#the-eval-set)). The eval also ranks its 20 headlines as one
  batch, unlike the ~100-item daily batch.

## What's next

- **SEC filings.** EDGAR feeds for CoreWeave, Nebius, and Oracle were cut from
  v1. The SEC rejects requests without a descriptive User-Agent that includes
  contact info, so adding them means setting a `SEC_USER_AGENT` secret (e.g.
  `ai-infra-intel-brief you@example.com`) and sending it with those requests.
- Grow the eval set (more headlines, a second labeler, repeated runs to average out the ranker's run-to-run variation).
- More profiles, and a workflow matrix so several companies run side by side
  each morning.
- Primary-source monitoring beyond filings: regulator dockets and interconnection queues.
- A structured market map of companies, customers, and capacity.
- Weekly trend summaries.
- Email delivery (e.g., Resend).
