# AI Infrastructure Intelligence Brief — Build Spec

A daily, source-verified intelligence brief on AI infrastructure markets, **prepared for a target company chosen by a profile**. Crusoe is the first demo profile; adding another company means adding one config file (section 3a), not changing code. Built by Nash as a working prototype of the "AI-powered intelligence infrastructure" described in the Senior Associate, Strategic Initiatives posting.

## 1. What it does

Every morning it:

1. **Collects** news from a fixed set of sources across four industry markets, plus searches specific to the target company.
2. **Filters and ranks** items by how much they could matter to the target company.
3. **Writes** a short brief: the top 3 developments, a watchlist roundup, and a "noise we ignored" list.
4. **Verifies** that every claim links to an article the system actually collected, and drops anything it can't source.
5. **Delivers** the brief by saving a copy to this repo (email delivery is a later step).

**Design principle:** it should augment judgment, not replace it. The brief says what happened, why it might matter, and how confident it is. The conclusion stays with the reader.

## 2. The brief format

**Title:** AI Infrastructure Intelligence Brief — prepared for [company name from the profile], with the date on the line below.

**Top 3 developments.** For each one:
- **What happened:** one or two sentences.
- **Why it matters to [company]:** two sentences: the specific part of the company's business affected and the mechanism, then what to watch next. No generic advice. (The parts of the business come from the profile; for Crusoe: power, manufacturing, data centers, cloud.)
- **Business impact** (structured, right after Why it matters): **Direction** (Opportunity or Risk), **Channel** (one of: Revenue & pricing; Costs & margins; Financing & cost of capital; Customers & pipeline; Siting & timeline), **Size** (only a figure stated in the source text or the profile and verified by the quote check; otherwise exactly "unsized"; never estimated or invented), and **Consider** (one specific option or question for the company tied to this story; no generic advice).
- **Confidence:** Confirmed (company announcement, filing, or regulator) or Reported (press citing sources).
- **Source:** link to the primary article.
- **Evidence:** a short supporting quote (4–24 words) from the article, in small print, with whether it came from the article text or the RSS summary. Checked in code (section 6).

**Watchlist roundup:** 3–6 one-line items by market, each with a link.

**Noise we ignored:** 3–5 items it skipped, each with a one-line reason (e.g., "opinion piece, no new facts," "duplicate of item 2," "not relevant to the company's markets").

**This week's themes and Opportunities (Fridays only, or on request):** 3 themes from the week's verified briefs, each citing the daily briefs it draws on, with a supporting quote; and an Opportunities list (potential customers, distressed assets or power contracts, partnerships, pricing signals), each citing one daily brief with a supporting quote. Verified under the same rules (section 6).

**Footer:** number of articles scanned, number kept, any sources that failed to load, and how many of the top stories had full article text versus summary only.

## 3. Watchlist

**Markets** (shared by every profile, in `watchlist.yaml`)
- **AI compute & cloud:** CoreWeave, Lambda, Nebius, Together AI, Oracle Cloud, AWS, Microsoft Azure, Google Cloud, OpenAI, Anthropic, xAI
- **Power & energy:** utility and PPA deals, gas and nuclear for data centers, interconnection queues, FERC and state rules, ERCOT
- **Data center construction:** hyperscale campus announcements, modular data centers, land and permitting, local moratoriums and ballot measures
- **Chips & hardware:** Nvidia, AMD, GPU generations and delays, HBM supply, Broadcom and custom silicon

**The target company (from its profile):** any mention of the company's own names, people, and products is always relevant. For Crusoe: Crusoe, Chase Lochmiller, Crusoe Cloud, or Spark modular data centers, plus Abilene, Texas and Stargate (company-specific, so they live in the Crusoe profile, not the shared watchlist).

Keep the watchlist in config files so it's easy to change without touching code: `watchlist.yaml` for the shared markets, and the profile for company-specific terms.

### 3a. Profiles (the configurable target company)

Everything specific to the target company lives in `profiles/<name>.yaml`. The `TARGET_PROFILE` setting (an environment variable, or a repository variable on GitHub) picks one; the default is `crusoe`. A profile holds:

- **company:** name, a one-line description, customers, competitors, and the parts of its business a development can affect.
- **facts:** background the ranker and writer use for relevance and "why it matters". These are not article facts; the writer may not present them as something an article said.
- **watchlist_terms:** always-relevant terms, added to the shared watchlist.
- **google_news_terms:** searches that only make sense for this company, added to the shared searches.

The code contains no company name: prompts, the brief title, and the labels all read from the profile. `profiles/_template.yaml` is the starting point for a new company.

## 4. Sources (v1)

Start with free RSS feeds so nothing requires a login:

- Data Center Dynamics (datacenterdynamics.com) RSS
- Utility Dive RSS
- Data Center Frontier RSS
- TechCrunch AI category RSS
- The Register data center section RSS
- Google News RSS searches (e.g., `https://news.google.com/rss/search?q=CoreWeave`): shared industry searches in `sources.yaml`, plus the target company's own in its profile
- SEC EDGAR filings feeds for public competitors (CoreWeave, Nebius, Oracle) (deferred past v1; see the README)

Keep the shared list in `sources.yaml`. Confirm each feed URL works before relying on it, and drop any that fail.

## 5. How it works (architecture)

A single Python script that runs once a day on GitHub Actions:

1. **Fetch:** read every feed in `sources.yaml`; keep items from the last 24–48 hours. Files are named by the America/Denver date, not UTC.
2. **Deduplicate:** merge items covering the same story (same link, or very similar titles).
3. **Filter:** keep items that mention a watchlist term. Then decode Google News redirect links to the publisher's URL (rate-limited, with a fallback to the original link) and merge duplicates that now share a URL; both URLs stay in the collected set.
4. **Rank:** send the filtered list to Claude with a scoring prompt (relevance to the target company, novelty, source quality). Each item gets a score from 1 to 5 and a one-line reason.
5. **Fetch full text:** for the strongest stories, fetch the full article, obeying robots.txt and skipping paywalled, blocked, or near-empty pages and Google News redirects; fall back to the RSS summary and record why.
6. **Write:** send the top-ranked items (full text where available) to Claude with the brief-writing prompt and the exact format above. Each "What happened" comes with a short verbatim supporting quote.
7. **Verify:** a code check, not an AI check. Every link in the brief must match an article collected in step 1, and every top development's quote must appear in the text we hold. Any item that fails is removed, and the removal is logged.
8. **Weekly synthesis (Fridays, or on request):** read the week's verified briefs for the profile and add "This week's themes", verified in code.
9. **Deliver:** save the brief as `briefs/<profile>/YYYY-MM-DD.md` in the repo (one folder per profile, so companies never overwrite each other), rebuild the index `briefs/<profile>/README.md`, and update the "Latest brief" link at the top of the README.

**Tools**
- Python, with `feedparser`, `pyyaml`, and the `anthropic` package
- Claude API for ranking and writing (costs cents per day); the key is read from the `ANTHROPIC_API_KEY` environment variable / repository secret
- GitHub Actions for the daily schedule (free)
- Email delivery (e.g., Resend) is a later addition

**Secrets:** API keys live only in GitHub repository secrets or a local `.env` file that is git-ignored. Never commit keys to code.

## 6. Verification and testing

- **Source check (code):** every link must come from the collected set. Unmatched links are removed.
- **Quote check (code):** each top development's supporting quote must appear word for word (whitespace, quote styles, and dash styles aside) in the fetched article text, or in the RSS title and summary when the article is unavailable. A missing, malformed, or non-matching quote removes the item; a "Confirmed" label backed only by the RSS summary is downgraded to Reported. Every removal or downgrade is logged.
- **Business-impact check (code):** Direction and Channel must be allowed values (otherwise the item is removed). Size must be copied word for word from the profile or from a quote that passes the quote check; anything else becomes exactly "unsized" and is logged.
- **Weekly check (code):** every theme must cite at least two daily briefs that exist, and its quote must appear in one of them; every opportunity must cite one daily brief that exists, quote it, and contain no figure the brief lacks. Failing items are dropped.
- **Claim check (prompt rule):** the writing prompt may only use facts present in the supplied article text, and must label anything uncertain as Reported.
- **Unit tests (pytest):** use saved sample feeds as test data; confirm deduplication, filtering, and the source check behave correctly, including when a feed is down or empty, and when the brief contains a deliberately fake link or a fabricated quote.
- **Eval set:** 20 real headlines labeled by hand as signal or noise for the target company (`evals/labeled_headlines.yaml`). Run the ranking step against them and record how often it agrees. Re-run after every prompt change.
- **Fail closed:** if collection fails or the source and quote checks leave no top development, write a short "no verified brief today" file instead of a brief with unsupported claims.

## 7. Build steps (one at a time; test each before moving on)

1. Set up a Python project with feedparser, pyyaml, anthropic, and pytest. Create `sources.yaml` and `watchlist.yaml` from this spec, and verify each feed URL returns items.
2. Write the fetch, deduplicate, and filter steps. Save today's raw results to a JSON file. Add pytest tests using saved sample feeds.
3. Write the ranking step using the Claude API with a scoring prompt (relevance to the target company, novelty, source quality, 1–5 with a reason). Save scores to JSON.
4. Write the brief-writing step using the exact format in this spec. Facts may only come from the supplied articles.
5. Write the source-verification check in code: remove any brief item whose link isn't in the collected set, and log removals. Add tests, including a deliberately fake link.
6. Add an eval script that runs the ranking step against `evals/labeled_headlines.yaml` and reports agreement. (Nash writes the 20 labels.)
7. Add a GitHub Actions workflow that runs daily at 6:00 a.m. Mountain time, can also be run manually, and commits the brief to `briefs/<profile>/YYYY-MM-DD.md`.
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
- More company profiles, and a workflow matrix so several companies run side by side each morning
