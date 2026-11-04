# Crusoe Intelligence Brief — Build Spec

A daily, source-verified intelligence brief on the markets that matter to Crusoe. Built by Nash as a working prototype of the "AI-powered intelligence infrastructure" described in the Senior Associate, Strategic Initiatives posting.

## 1. What it does

Every morning it:

1. **Collects** news from a fixed set of sources across Crusoe's four markets.
2. **Filters and ranks** items by how much they could matter to Crusoe.
3. **Writes** a short brief: the top 3 developments, a watchlist roundup, and a "noise we ignored" list.
4. **Verifies** that every claim links to an article the system actually collected, and drops anything it can't source.
5. **Delivers** the brief by saving a copy to this repo (email delivery is a later step).

**Design principle:** it should augment judgment, not replace it. The brief says what happened, why it might matter, and how confident it is. The conclusion stays with the reader.

## 2. The brief format

**Title:** Crusoe Intelligence Brief — [date]

**Top 3 developments.** For each one:
- **What happened:** one or two sentences.
- **Why it matters to Crusoe:** one or two sentences tied to a specific part of the business (power, manufacturing, data centers, cloud).
- **Confidence:** Confirmed (company announcement, filing, or regulator) or Reported (press citing sources).
- **Source:** link to the primary article.

**Watchlist roundup:** 3–6 one-line items by market, each with a link.

**Noise we ignored:** 3–5 items it skipped, each with a one-line reason (e.g., "opinion piece, no new facts," "duplicate of item 2," "not relevant to Crusoe's markets").

**Footer:** number of articles scanned, number kept, and any sources that failed to load.

## 3. Watchlist

**Markets**
- **AI compute & cloud:** CoreWeave, Lambda, Nebius, Together AI, Oracle Cloud, AWS, Microsoft Azure, Google Cloud, OpenAI and Stargate, Anthropic, xAI
- **Power & energy:** utility and PPA deals, gas and nuclear for data centers, interconnection queues, FERC and state rules, ERCOT
- **Data center construction:** hyperscale campus announcements, Abilene, Texas, modular data centers, land and permitting, local moratoriums and ballot measures
- **Chips & hardware:** Nvidia, AMD, GPU generations and delays, HBM supply, Broadcom and custom silicon

**Crusoe itself:** any mention of Crusoe, Chase Lochmiller, Crusoe Cloud, or Spark modular data centers.

Keep the watchlist in a separate config file (`watchlist.yaml`) so it's easy to change without touching code.

## 4. Sources (v1)

Start with free RSS feeds so nothing requires a login:

- Data Center Dynamics (datacenterdynamics.com) RSS
- Utility Dive RSS
- Data Center Frontier RSS
- TechCrunch AI category RSS
- The Register data center section RSS
- Google News RSS searches, one per watchlist term (e.g., `https://news.google.com/rss/search?q=CoreWeave`)
- SEC EDGAR filings feeds for public competitors (CoreWeave, Nebius, Oracle)

Keep the list in `sources.yaml`. Confirm each feed URL works before relying on it, and drop any that fail.

## 5. How it works (architecture)

A single Python script that runs once a day on GitHub Actions:

1. **Fetch:** read every feed in `sources.yaml`; keep items from the last 24–48 hours.
2. **Deduplicate:** merge items covering the same story (same link, or very similar titles).
3. **Filter:** keep items that mention a watchlist term.
4. **Rank:** send the filtered list to Claude with a scoring prompt (relevance to Crusoe, novelty, source quality). Each item gets a score from 1 to 5 and a one-line reason.
5. **Write:** send the top-ranked items to Claude with the brief-writing prompt and the exact format above.
6. **Verify:** a code check, not an AI check. Every link in the brief must match an article collected in step 1. Any item with a missing or unmatched link is removed, and the removal is logged.
7. **Deliver:** save the brief as `briefs/YYYY-MM-DD.md` in the repo.

**Tools**
- Python, with `feedparser`, `pyyaml`, and the `anthropic` package
- Claude API for ranking and writing (costs cents per day); the key is read from the `ANTHROPIC_API_KEY` environment variable / repository secret
- GitHub Actions for the daily schedule (free)
- Email delivery (e.g., Resend) is a later addition

**Secrets:** API keys live only in GitHub repository secrets or a local `.env` file that is git-ignored. Never commit keys to code.

## 6. Verification and testing

- **Source check (code):** every link must come from the collected set. Unmatched links are removed.
- **Claim check (prompt rule):** the writing prompt may only use facts present in the supplied article text, and must label anything uncertain as Reported.
- **Unit tests (pytest):** use saved sample feeds as test data; confirm deduplication, filtering, and the source check behave correctly, including when a feed is down or empty, and when the brief contains a deliberately fake link.
- **Eval set:** 20 real headlines labeled by hand as signal or noise for Crusoe (`evals/labeled_headlines.yaml`). Run the ranking step against them and record how often it agrees. Re-run after every prompt change.
- **Fail closed:** if collection fails or the source check removes everything, write a short "no verified brief today" file instead of a brief with unsupported claims.

## 7. Build steps (one at a time; test each before moving on)

1. Set up a Python project with feedparser, pyyaml, anthropic, and pytest. Create `sources.yaml` and `watchlist.yaml` from this spec, and verify each feed URL returns items.
2. Write the fetch, deduplicate, and filter steps. Save today's raw results to a JSON file. Add pytest tests using saved sample feeds.
3. Write the ranking step using the Claude API with a scoring prompt (relevance to Crusoe, novelty, source quality, 1–5 with a reason). Save scores to JSON.
4. Write the brief-writing step using the exact format in this spec. Facts may only come from the supplied articles.
5. Write the source-verification check in code: remove any brief item whose link isn't in the collected set, and log removals. Add tests, including a deliberately fake link.
6. Add an eval script that runs the ranking step against `evals/labeled_headlines.yaml` and reports agreement. (Nash writes the 20 labels.)
7. Add a GitHub Actions workflow that runs daily at 6:00 a.m. Mountain time, can also be run manually, and commits the brief to `briefs/YYYY-MM-DD.md`.
8. Write a README: what it does, how it works, how verification works, known limitations.

Keep the code simple and well-commented; it will be walked through with a hiring team.

## 8. Known limitations to document

- Paywalled sources and stories that never reach free feeds
- Rumors that look like news
- Important stories that don't use watchlist terms
- "Why it matters" is a judgment call and should be reviewed by a person

## 9. What's next (after v1)

- Primary-source monitoring: SEC filings, regulator dockets, interconnection queues
- A structured market map of companies, customers, and capacity
- Weekly trend summaries
- Email delivery
