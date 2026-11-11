# Setup, configuration and tests

Part of the [AI Infrastructure Intelligence Brief](../README.md). Also: [Architecture and design](architecture.md) · [The eval set](evals.md) · [Full spec](../SPEC.md)

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

## Pausing and resuming

The daily workflow is the only thing that spends API credit (rank and write, plus weekly synthesis on Fridays). Runs skipped by the gate make no API calls.

- **Pause:** GitHub, Actions, "Daily brief", the "..." menu, **Disable workflow**. Manual runs are also blocked while it is disabled.
- **Resume:** the same menu, **Enable workflow**. Check that the `ANTHROPIC_API_KEY` secret is set and the Anthropic account has credit, then use "Run workflow" for an immediate brief, or wait for the next scheduled run.
- Nothing in the repository needs to change to pause or resume.

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
