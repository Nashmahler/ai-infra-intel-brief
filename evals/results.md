# Ranker eval results

Run with `python -m src.evaluate [--runs N]` on a GitHub runner against the 20 hand labels in
[`labeled_headlines.yaml`](labeled_headlines.yaml) (8 labeled signal, 12 noise). A ranker score of
3 or more counts as "signal". These are **snapshots**: re-run the eval after every prompt change and
compare. Because the ranker is not deterministic, comparisons below use **3 runs per prompt**.

## Ranker iteration, 2026-11-05: relevance first (before -> after)

The prompt change (in `src/rank.py`): score relevance to the company first; a weak source lowers
confidence (the brief labels it "Reported") and must never lower the score of a relevant, new story,
which scores at least 3 with the weakness noted in the reason; vendor and supplier product
announcements score 2 unless they directly affect the company's cost, capacity, or supply. The writer
prompt got the matching rule (a weak outlet means "Reported"). Both runs used identical code except the prompt.

| | before (old prompt, commit `3154649`) | after (new prompt, commit `b1b7729`) |
|---|---|---|
| agreement per run (of 20) | 14, 16, 15 | 18, 18, 18 |
| **mean agreement** | **15.0/20 (75%)** | **18.0/20 (90%)** |
| mean false positives | 2.0 | 1.3 |
| mean false negatives | 3.0 | 0.7 |

Per-item ranker scores in the three runs (**bold** = changed; "wrong" = disagrees with your label in that run):

| # | label | before | after | what changed |
|---|---|---|---|---|
| 11 | signal | 2,2,2 | **3,3,3** | false negative fixed (ballot-measures roundup from a lower-tier outlet) |
| 14 | signal | 2,2,2 | **3,3,3** | false negative fixed (Wisconsin secrecy agreements, lower-tier outlet) |
| 16 | noise | 3,3,3 | **2,2,2** | false positive fixed (NVIDIA CUDA / Vera Rubin vendor announcement) |
| 9 | noise | 3,2,2 | **2,2,2** | flaky false positive fixed (Enphase supplier milestone) |
| 1 | signal | 2,2,2 | **2,2,3** | still wrong in 2 of 3 runs (Chinese firms and Nvidia GPUs, crypto outlet) |
| 13 | noise | 2,2,2 | **2,2,3** | slightly worse: now a flaky false positive (Citi price target for CoreWeave) |
| 17 | noise | 3,2,3 | **3,3,3** | slightly worse: false positive in all 3 runs (possible Stargate investigation, weak outlet) |
| 2,3,4,5,6,7,8,10,12,15,18,19,20 | | | | unchanged, all right in every run |

How to read it: the three biggest fixes are exactly what the rules target (relevant stories from weak outlets no
longer lose points for their source; vendor announcements fall to 2). The remaining miss, #17, is the
mirror image: it is relevant to Crusoe (Stargate, Abilene) so the new rule keeps it at 3 even though it came
from a weak outlet, and the labeler called it noise.

**The "after" number is optimistic.** The new rules were written after looking at these exact failures, and
the same 20 headlines then measured the result, so part of the gain is fitting the test. The per-run ranges
do not overlap (14-16 before, 18-18 after), so it is not run-to-run noise, but only a fresh set of labeled
headlines the prompt has never seen can say how much carries over.

## Held-out set, 2026-11-05 (current prompt, never tuned on it)

[`heldout_headlines.yaml`](heldout_headlines.yaml): 20 fresh headlines from the same day's data that share no
headline, link, or story with the tuning set above (6 labeled signal, 14 noise). Scored with the **current prompt, unchanged**
(3 runs, commit `68abb83`); the set was never used to change the prompt.

| | held-out set |
|---|---|
| agreement per run (of 20) | 18, 18, 18 |
| **mean agreement** | **18.0/20 (90%)** |
| mean false positives / false negatives | 2.0 / 0.0 |
| precision / recall | 75% (6 of the 8 it called signal) / 100% (all 6 of your signals) |

**False positives, wrong in all 3 runs** (ranker scored 3, labeled noise):
- #8 The City of Tampa is considering a data center moratorium
- #16 AWS proceeds with data center project in Walla Walla, Washington

**False negatives:** none. Every headline labeled signal scored 3 or higher in every run.

**Not directly comparable to the tuning set** (read this before comparing the two 90% figures):
- **It leans toward mid-range headlines.** Only 1 of its 20 came from the ranker's 4-5 band (13 from 2-3, 6 from 1), not the
  7 / 7 / 6 mix of the tuning set. 44 of the day's 100 ranked items overlapped the tuning set (mostly the same CoreWeave and
  Texas story cluster, where the high scores were), so excluding them left almost no high scorers. The mid band is where the
  ranker was weakest, so this is a harder test in that respect.
- **The base rate differs.** With 14 noise of 20, a ranker that called everything noise would already agree 70% of the
  time (60% on the tuning set, 12 noise of 20). Against those baselines the held-out result is +20 points and the tuning
  result +30.
- The two 90% figures happening to match is a coincidence, not evidence they are equivalent.
- **The pattern:** all the errors are false positives on local or project-level data center news (a city moratorium, a
  hyperscaler site) that the relevance-first rule keeps at 3 and that you judged noise. The new prompt errs toward including
  a relevant story rather than missing one.
- Still 20 headlines and one labeler, from one day's data, so a miss or two moves the number by 5 points.

## Original single run, 2026-11-05 (old prompt, before the `--runs` option existed)

| | you said signal | you said noise |
|---|---|---|
| **ranker said signal (score 3+)** | 5 | 3 (false positives) |
| **ranker said noise (score 1-2)** | 3 (false negatives) | 9 |

Agreement **14/20 (70%)**. Precision 62.5% (5 of the 8 the ranker called signal), recall 62.5% (5 of your 8 signals).

**False positives** (ranker said signal, you said noise), all scored 3:
- #9 Enphase reaches 800 VDC AI data center power milestone: a supplier milestone
- #16 NVIDIA CUDA 13.5 brings Vera Rubin GA support: a vendor technical announcement
- #17 OpenAI could face Democratic investigation over Stargate (UNILAD Tech)

**False negatives** (ranker said noise, you said signal), all scored 2:
- #1 Chinese AI firms may receive 1% of 6 million Nvidia GPUs in four months (tokenpost.com)
- #11 41 Data Center Ballot Measures [2026]: What AI Teams Face (tech-insider.org)
- #14 Two secrecy agreements shadow OpenAI's $15 billion Wisconsin data center (the deep dive)

## What the pattern suggests (small sample, so treat as leads, not conclusions)
- **The ranker was right at both ends.** Every headline it scored 4-5 (3 of them) was signal, and every one it scored 1 (6 of them) was noise. All 6 disagreements are among the 11 it scored 2 or 3, where it agreed on 5.
- **It lets source quality outweigh relevance.** For all three false negatives its own reason blames a "low-tier", "lower-quality" or "lower-tier" outlet, while you labeled the content. (#17 is the opposite case: it cites a "low-quality source" and still scores 3.)
- **It over-credits vendor and supplier news** (#9, #16) as relevant to Crusoe's power and GPU dependencies.
- *What-if from the same table:* a threshold of 4 would give 75% agreement (0 false positives, 5 false negatives, recall 37.5%). Not a recommendation, just a sense of the trade-off.

## Caveats
- **20 headlines, one labeler, one run.** One or two changes are within noise.
- **The ranker is not deterministic**, and the sampling pass chose about 7 headlines from its 4-5 band, yet this pass scored only 3 headlines 4 or higher: scores moved between passes.
- **Different batch context:** the eval ranks these 20 as one batch, while production ranks about 100 at once, and the prompt tells the model "most items should score 1 or 2". The sample is also denser in relevant items than a normal day, so absolute scores are not directly comparable to the daily run.
