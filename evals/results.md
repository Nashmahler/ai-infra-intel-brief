# Ranker eval: first result (snapshot, 2026-11-05)

Run with `python -m src.evaluate` on a GitHub runner against the 20 hand labels in
[`labeled_headlines.yaml`](labeled_headlines.yaml) (8 labeled signal, 12 noise). A ranker
score of 3 or more counts as "signal". This is a **snapshot**, not a live number: re-run
the eval after every prompt change and compare.

| | you said signal | you said noise |
|---|---|---|
| **ranker said signal (score 3+)** | 5 | 3 (false positives) |
| **ranker said noise (score 1-2)** | 3 (false negatives) | 9 |

**Agreement 14/20 (70%).** Precision 62.5% (5 of the 8 the ranker called signal), recall 62.5% (5 of your 8 signals).

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
