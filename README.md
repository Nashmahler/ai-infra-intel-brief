# AI Infrastructure Intelligence Brief

<!-- latest-brief:start -->
**Latest brief — Crusoe:** [November 6, 2026](briefs/crusoe/2026-11-06.md) · [all briefs](briefs/crusoe/README.md) <!--profile:crusoe-->
<!-- latest-brief:end -->

A daily brief on AI infrastructure for any target company in which every top-story claim is checked in code against the article it came from before it is published.

## What it does
- **Collects** about 550 items a day from trade-press RSS feeds and Google News searches, filtered to a company-specific watchlist.
- **Ranks** them with Claude, scoring relevance to the company first and grouping duplicate coverage into stories.
- **Writes** a short brief: top 3 developments with why they matter and a business-impact line, a watchlist, ignored noise, and weekly themes and opportunities on Fridays.
- **Verifies** the draft with plain code, not AI (links, quotes, figures), then **publishes** it to [`briefs/`](briefs/) from GitHub Actions every morning.
- **Retargets** to a competitor, a key customer, or a new market by swapping one YAML profile, with no code changes.

## How I know it's trustworthy
- **Quote-verified claims:** each top story needs a 4-24 word quote that appears word for word in the article, or the item is removed and logged; tests inject fake links and quotes to prove it.
- **Fails closed:** if nothing verifies, it publishes "No verified brief today" instead of an unsupported brief.
- **Measured ranking:** ranker agreement with my labels: 75% → 90% on the tuning set, and 90% on a held-out set it had never seen (3 runs each).
- **309 automated tests** run offline, and the whole pipeline runs live on GitHub every day.

## Known limitations
- Full article text depends on an unofficial Google News decoder and on sites allowing access (9 of 10 in the latest run); otherwise claims are checked against the RSS summary and labeled "Reported".
- A matching quote proves the words exist, not that the claim is right, and "why it matters" is the model's judgment that a person should review.
- The evals are small (40 headlines across a tuning set and a held-out set, one labeler).

## More detail
- [Architecture and design](docs/architecture.md): the pipeline, brief format, verification rules, limitations
- [Setup, configuration and tests](docs/setup.md): running it, adding a company, secrets, the test suite
- [The eval set](docs/evals.md): how the ranker is scored, with before and after
- [Full spec](SPEC.md)
