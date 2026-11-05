# Evals

Part of the [AI Infrastructure Intelligence Brief](../README.md). Also: [Architecture and design](architecture.md) · [Setup, configuration and tests](setup.md) · [Full spec](../SPEC.md)

## The eval set

How well does the ranker's "this matters" judgment match a person's? The answer
lives in [`evals/labeled_headlines.yaml`](../evals/labeled_headlines.yaml): **20 real
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
result. Because the ranker is a language model and the set is small, a single run is
noisy: `python -m src.evaluate --runs 3` (the workflow's `runs` input) ranks the
headlines several times and reports the mean agreement, plus which headlines are wrong
every time and which only sometimes.

**Results so far** (full tables, per-item scores and caveats in
[`evals/results.md`](../evals/results.md)):

- **The first run** (single run, original prompt): **14/20 (70%) agreement, 3 false
  positives, 3 false negatives**. The ranker was right on everything it scored 4-5 or 1,
  and all the disagreements were in the middle; it also tended to mark down good
  stories from low-tier outlets.
- **Before the prompt fix** (3 runs): **mean 15.0/20 (75%)**, with 2.0 false positives
  and 3.0 false negatives on average.
- **After the prompt fix** (3 runs, same code): **18/20 in every run, mean 90%**, with
  1.3 false positives and 0.7 false negatives on average. The fix: score relevance
  first, treat a weak source as lower *confidence* (the brief labels it "Reported")
  rather than a lower score, and score vendor product announcements 2 unless they
  directly affect the company's cost, capacity, or supply.
- **Caveat:** the fix was written after looking at these same 20 headlines, so the
  90% is optimistic. The run-to-run ranges do not overlap (14-16 before, 18 after),
  so it is not noise, but only a fresh set of labeled headlines can say how much of
  the gain carries over.

The sample was built by the **Eval sample** workflow (`python -m src.evalset`), which
refuses to overwrite a file that already has labels; to rebuild it, delete the file
first and expect to relabel.
