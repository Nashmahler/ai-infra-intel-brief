"""Build the eval set: 20 real headlines to be labeled by hand.

    python -m src.evalset [YYYY-MM-DD] [--seed N] [--force]

Reads  data/<profile>/YYYY-MM-DD_scores.json   (today's collected, ranked items)
Writes evals/labeled_headlines.yaml            (headlines with an EMPTY `label:` each)

The sample is stratified by what the ranker thought, so the eval has both easy and
hard cases: about 7 items it scored 4-5, 7 scored 2-3, and 6 scored 1, then
shuffled. The scores are used only to choose; they are NOT written to the file,
and the order is random, so the person labeling can't be nudged by the ranker.

Only one item per story is considered (no five copies of the same event), and
near-identical titles are never both picked. The file is never overwritten once
any label has been filled in, unless --force is given.
"""
import json
import random
import sys
from difflib import SequenceMatcher

import yaml

from .config import ROOT, company_name, data_dir, profile_name, today
from .fetch import normalize_title

EVALS_FILE = ROOT / "evals" / "labeled_headlines.yaml"
BANDS = (("high", 4, 5, 7), ("mid", 2, 3, 7), ("low", 1, 1, 6))   # name, min score, max score, how many
SIMILAR = 0.85          # titles this alike count as the same headline
DEFAULT_SEED = 20261105

NOTE = """\
# Hand-labeled headlines for checking the ranker (SPEC.md section 6, "Eval set").
#
# Fill in `label:` for every headline with exactly one of:
#   signal  = something {company}'s strategy team would want to know
#   noise   = not worth their attention
#
# Judge the headline (and summary) as a person, not what a ranking model would say:
# the point of this file is to measure how often the ranker agrees with you.
# The order is shuffled and no ranker scores are stored here, on purpose.
#
# Check the ranker against these labels with:   python -m src.evaluate
"""


def _is_lead(item: dict) -> bool:
    return item.get("is_lead", True)


def pick(items: list[dict], seed: int = DEFAULT_SEED) -> tuple[list[dict], dict]:
    """Choose the sample. Returns (shuffled items, {band: how many came from it}).

    If a band has too few distinct stories, the shortfall is topped up from the
    other bands (nearest first), so the total stays the same.
    """
    rng = random.Random(seed)
    pool = [i for i in items if _is_lead(i) and i.get("title") and (i.get("publisher") or i.get("source"))]
    rng.shuffle(pool)
    chosen, titles, counts = [], [], {}

    def take(candidates, want):
        got = 0
        for item in candidates:
            if got == want:
                break
            t = normalize_title(item["title"])
            if any(SequenceMatcher(None, t, seen).ratio() >= SIMILAR for seen in titles) or item in chosen:
                continue
            chosen.append(item)
            titles.append(t)
            got += 1
        return got

    short = 0
    for name, lo, hi, want in BANDS:
        got = take([i for i in pool if lo <= i["score"] <= hi], want)
        counts[name] = got
        short += want - got
    for name, lo, hi, _ in sorted(BANDS, key=lambda b: -b[3]):          # top up any shortfall
        if short:
            added = take([i for i in pool if lo <= i["score"] <= hi], short)
            counts[name] += added
            short -= added
    rng.shuffle(chosen)                                                   # no band order left in the file
    return chosen, counts


def render(chosen: list[dict], company: str, profile: str) -> str:
    """The YAML text: a note, then each headline with an empty label."""
    q = lambda s: json.dumps(str(s), ensure_ascii=False)                  # JSON strings are valid YAML
    lines = [NOTE.format(company=company), f"profile: {profile}", "headlines:"]
    for n, item in enumerate(chosen, 1):
        lines += [f"  - id: {n}",
                  f"    headline: {q(item['title'])}",
                  f"    source: {q(item.get('publisher') or item['source'])}",
                  f"    published: {q(item.get('published', ''))}",
                  f"    link: {q(item.get('link', ''))}",
                  f"    summary: {q(item.get('summary', ''))}",
                  "    label:                 # signal | noise", ""]
    return "\n".join(lines)


def has_labels(path) -> bool:
    """True if the file exists and any headline already has a label."""
    if not path.exists():
        return False
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return any((h.get("label") or "").strip() for h in data.get("headlines", []))


def main() -> int:
    args = sys.argv[1:]
    force = "--force" in args
    seed = int(args[args.index("--seed") + 1]) if "--seed" in args else DEFAULT_SEED
    positional = [a for i, a in enumerate(args) if not a.startswith("--") and (i == 0 or args[i - 1] != "--seed")]
    day = positional[0] if positional else today()
    if has_labels(EVALS_FILE) and not force:
        print(f"{EVALS_FILE.name} already has labels: not overwriting (use --force to replace it).")
        return 1
    try:
        items = json.loads((data_dir() / f"{day}_scores.json").read_text(encoding="utf-8"))["items"]
    except (OSError, ValueError):
        print(f"No scores file for {day}: run fetch and rank first.")
        return 1
    chosen, counts = pick(items, seed)
    if len(chosen) < 20:
        print(f"Only {len(chosen)} suitable headlines in today's data (wanted 20).")
    EVALS_FILE.parent.mkdir(exist_ok=True)
    EVALS_FILE.write_text(render(chosen, company_name(), profile_name()), encoding="utf-8")
    print(f"wrote {len(chosen)} headlines to {EVALS_FILE} (seed {seed}); labels are empty.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
