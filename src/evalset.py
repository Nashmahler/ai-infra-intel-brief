"""Build the eval set: 20 real headlines to be labeled by hand.

    python -m src.evalset [YYYY-MM-DD] [--seed N] [--force] [--out FILE] [--exclude FILE]

Reads  data/<profile>/YYYY-MM-DD_scores.json   (today's collected, ranked items)
Writes evals/labeled_headlines.yaml            (headlines with an EMPTY `label:` each)

The sample is stratified by what the ranker thought, so the eval has both easy and
hard cases: about 7 items it scored 4-5, 7 scored 2-3, and 6 scored 1, then
shuffled. The scores are used only to choose; they are NOT written to the file,
and the order is random, so the person labeling can't be nudged by the ranker.

Only one item per story is considered (no five copies of the same event), and
near-identical titles are never both picked. The file is never overwritten once
any label has been filled in, unless --force is given.

A HELD-OUT set (a second sample the prompt was never tuned on) is built with
`--out evals/heldout_headlines.yaml --exclude evals/labeled_headlines.yaml`: nothing
that is in, or about the same story as, an excluded headline can be picked.
"""
import argparse
import json
import random
import re
import sys
from difflib import SequenceMatcher

import yaml

from .config import ROOT, company_name, data_dir, profile_name, today
from .fetch import normalize_link, normalize_title

EVALS_FILE = ROOT / "evals" / "labeled_headlines.yaml"
HELDOUT_FILE = ROOT / "evals" / "heldout_headlines.yaml"
BANDS = (("high", 4, 5, 7), ("mid", 2, 3, 7), ("low", 1, 1, 6))   # name, min score, max score, how many
SIMILAR = 0.85          # titles this alike count as the same headline
EXCLUDE_SIMILAR = 0.6   # to keep a held-out set apart, even loosely similar titles count as the same story
EXCLUDE_WORDS = 0.5     # ...or sharing at least this fraction of their significant words
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


HELDOUT_NOTE = """\
# HELD-OUT set: 20 headlines the ranking prompt has never been tuned on. They do not overlap
# the main eval set (no shared headline, link, or story). Label them, run the eval ONCE per
# prompt version, and do NOT change the prompt in response to these results; that would turn
# this back into a training set. It exists to check how much of the main eval's score
# carries over to headlines the prompt has not seen.
#
"""


def _is_lead(item: dict) -> bool:
    return item.get("is_lead", True)


def _words(title: str) -> set:
    return {w for w in re.findall(r"[a-z0-9]+", normalize_title(title)) if len(w) > 3}


def too_similar(a: str, b: str) -> bool:
    """Loosely 'the same story': near-identical or mostly shared significant words."""
    if SequenceMatcher(None, normalize_title(a), normalize_title(b)).ratio() >= EXCLUDE_SIMILAR:
        return True
    wa, wb = _words(a), _words(b)
    return bool(wa and wb) and len(wa & wb) / len(wa | wb) >= EXCLUDE_WORDS


def exclude_overlap(items: list[dict], reference: list[dict]) -> list[dict]:
    """Drop every item that is in, or about the same story as, a reference headline.

    `reference` rows have `headline` and `link`. An item is dropped if its link matches,
    its title is loosely similar, or it belongs to the same story group (the ranker's
    `story` number) as an item that was dropped for either reason.
    """
    links = {normalize_link(r["link"]) for r in reference if r.get("link")}
    hit = [i for i in items if normalize_link(i.get("link", "")) in links
           or any(too_similar(i["title"], r["headline"]) for r in reference)]
    stories = {i["story"] for i in hit if "story" in i}
    return [i for i in items if i not in hit and i.get("story") not in stories]


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


def render(chosen: list[dict], company: str, profile: str, heldout: bool = False) -> str:
    """The YAML text: a note, then each headline with an empty label."""
    q = lambda s: json.dumps(str(s), ensure_ascii=False)                  # JSON strings are valid YAML
    note = NOTE.format(company=company)
    if heldout:                                                            # explain what this set is for, first
        note = HELDOUT_NOTE + note
    lines = [note, f"profile: {profile}", "headlines:"]
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
    ap = argparse.ArgumentParser(prog="python -m src.evalset")
    ap.add_argument("day", nargs="?", default=None, help="YYYY-MM-DD (default: today, Denver)")
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--force", action="store_true", help="overwrite a file that already has labels")
    ap.add_argument("--out", default=None, help="file to write (default evals/labeled_headlines.yaml)")
    ap.add_argument("--exclude", action="append", default=[], help="labeled file whose headlines/stories to avoid")
    args = ap.parse_args()
    out = (ROOT / args.out) if args.out else EVALS_FILE
    heldout = out.resolve() != EVALS_FILE.resolve() and bool(args.exclude)
    day = args.day or today()
    if has_labels(out) and not args.force:
        print(f"{out.name} already has labels: not overwriting (use --force to replace it).")
        return 1
    try:
        items = json.loads((data_dir() / f"{day}_scores.json").read_text(encoding="utf-8"))["items"]
        reference = [h for path in args.exclude
                     for h in (yaml.safe_load((ROOT / path).read_text(encoding="utf-8")) or {}).get("headlines", [])]
    except (OSError, ValueError):
        print(f"No scores file for {day} (or an unreadable --exclude file): run fetch and rank first.")
        return 1
    before = len(items)
    items = exclude_overlap(items, reference) if reference else items
    chosen, counts = pick(items, args.seed)
    if len(chosen) < 20:
        print(f"Only {len(chosen)} suitable headlines in today's data (wanted 20).")
    out.parent.mkdir(exist_ok=True)
    out.write_text(render(chosen, company_name(), profile_name(), heldout), encoding="utf-8")
    print(f"excluded {before - len(items)} of {before} items overlapping the reference set" if reference else "no exclusions")
    print(f"drawn from the score bands (4-5 / 2-3 / 1): {counts['high']} / {counts['mid']} / {counts['low']}")
    print(f"wrote {len(chosen)} headlines to {out} (seed {args.seed}); labels are empty.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
