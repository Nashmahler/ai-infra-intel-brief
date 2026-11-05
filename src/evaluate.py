"""Eval: how often does the ranker agree with the hand labels?

    python -m src.evaluate [--runs N]

Reads evals/labeled_headlines.yaml (20 headlines, each labeled signal or noise by
a person), runs the REAL ranking step on them (needs ANTHROPIC_API_KEY), and
treats a ranker score of 3 or more as "signal". Then it reports:

  agreement        how often the ranker and the person said the same thing
  false positives  ranker said signal, the person said noise  (noise gets through)
  false negatives  ranker said noise, the person said signal  (a story is missed)

Re-run it after every change to the ranking prompt (SPEC.md section 6). The ranker
is a language model, so scores can shift a little from run to run; with only 20
headlines, treat a change of one or two as noise. `--runs N` ranks the headlines N
times (default 1, at most 10) and reports the mean agreement plus which headlines
are wrong every time and which only sometimes, which is the fair way to compare two
versions of the prompt.
"""
import json
import os
import sys

import anthropic
import yaml

from .config import ROOT, data_dir, profile_name
from .rank import rank_items

EVALS_FILE = ROOT / "evals" / "labeled_headlines.yaml"
SIGNAL_THRESHOLD = 3                      # ranker score >= 3 counts as "signal"
MAX_RUNS = 10
LABELS = ("signal", "noise")


class EvalError(Exception):
    """The eval file is not ready (unlabeled, malformed, ...). The message says how to fix it."""


def load_labeled(path=None) -> list[dict]:
    """Load the headlines and check every one has a valid label."""
    path = path or EVALS_FILE
    try:
        rows = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("headlines", [])
    except OSError:
        raise EvalError(f"{path} not found") from None
    if not rows:
        raise EvalError(f"{path.name} has no headlines")
    ids = [r.get("id") for r in rows]
    if len(set(ids)) != len(ids):
        raise EvalError("duplicate ids in the eval file")
    bad = [r["id"] for r in rows if str(r.get("label") or "").strip().lower() not in LABELS]
    if bad:
        raise EvalError(f"every headline needs label: signal or noise; missing or invalid for id(s) "
                        f"{', '.join(map(str, bad))}")
    return [{**r, "label": r["label"].strip().lower()} for r in rows]


def to_items(rows: list[dict]) -> list[dict]:
    """Turn labeled rows into the same item shape the ranker gets in production."""
    return [{"id": r["id"], "title": r["headline"], "link": r.get("link", ""), "source": r["source"],
             "publisher": r["source"], "published": r.get("published", ""),
             "summary": r.get("summary", "")} for r in rows]


def compare(rows: list[dict], scored: list[dict]) -> dict:
    """Compare ranker scores with labels. `scored` items carry `id`, `score`, `reason`."""
    by_id = {s["id"]: s for s in scored}
    missing = [r["id"] for r in rows if r["id"] not in by_id]
    if missing:
        raise EvalError(f"the ranker returned no score for id(s) {missing}")
    items = []
    for r in rows:
        s = by_id[r["id"]]
        predicted = "signal" if s["score"] >= SIGNAL_THRESHOLD else "noise"
        items.append({"id": r["id"], "headline": r["headline"], "source": r["source"],
                      "label": r["label"], "score": s["score"], "predicted": predicted,
                      "correct": predicted == r["label"], "reason": s.get("reason", "")})
    count = lambda lab, pred: sum(i["label"] == lab and i["predicted"] == pred for i in items)
    tp, tn, fp, fn = count("signal", "signal"), count("noise", "noise"), count("noise", "signal"), count("signal", "noise")
    ratio = lambda a, b: a / b if b else None
    return {"n": len(items), "tp": tp, "tn": tn, "fp": fp, "fn": fn,
            "agreement": (tp + tn) / len(items), "precision": ratio(tp, tp + fp), "recall": ratio(tp, tp + fn),
            "false_positives": [i for i in items if i["label"] == "noise" and i["predicted"] == "signal"],
            "false_negatives": [i for i in items if i["label"] == "signal" and i["predicted"] == "noise"],
            "items": items}


def format_report(r: dict) -> str:
    """A plain-text (and markdown-friendly) report."""
    pct = lambda x: "n/a" if x is None else f"{x:.0%}"
    lines = [f"Ranker eval: score >= {SIGNAL_THRESHOLD} counts as signal",
             f"Agreement: {r['tp'] + r['tn']}/{r['n']} ({pct(r['agreement'])})",
             f"  you said signal, ranker said signal: {r['tp']}     you said noise, ranker said noise: {r['tn']}",
             f"False positives (ranker said signal, you said noise): {r['fp']}",
             *[f"  #{i['id']} score {i['score']}: {i['headline']}  [{i['source']}]\n      ranker: {i['reason']}"
               for i in r["false_positives"]],
             f"False negatives (ranker said noise, you said signal): {r['fn']}",
             *[f"  #{i['id']} score {i['score']}: {i['headline']}  [{i['source']}]\n      ranker: {i['reason']}"
               for i in r["false_negatives"]],
             f"Precision (of what the ranker called signal, how much you agreed): {pct(r['precision'])}",
             f"Recall (of what you called signal, how much the ranker caught): {pct(r['recall'])}",
             "", "All headlines (id, your label, ranker score):"]
    lines += [f"  {i['id']:>2}  {i['label']:6} {i['score']}  {'ok ' if i['correct'] else 'DIFF'}  {i['headline'][:70]}"
              for i in r["items"]]
    return "\n".join(lines)


def summarize_runs(results: list[dict]) -> dict:
    """Combine several runs of `compare`: mean agreement, and per headline how often it was wrong."""
    n_runs = len(results)
    per_item = {}
    for run in results:
        for item in run["items"]:
            entry = per_item.setdefault(item["id"], {"id": item["id"], "headline": item["headline"],
                                                     "source": item["source"], "label": item["label"],
                                                     "scores": [], "wrong": 0})
            entry["scores"].append(item["score"])
            entry["wrong"] += not item["correct"]
    items = list(per_item.values())
    agreements = [r["agreement"] for r in results]
    return {"runs": n_runs, "n": results[0]["n"],
            "agreements": [r["tp"] + r["tn"] for r in results],
            "mean_agreement": sum(agreements) / n_runs,
            "mean_correct": sum(r["tp"] + r["tn"] for r in results) / n_runs,
            "mean_fp": sum(r["fp"] for r in results) / n_runs, "mean_fn": sum(r["fn"] for r in results) / n_runs,
            "wrong_every_run": [i for i in items if i["wrong"] == n_runs],
            "wrong_some_runs": [i for i in items if 0 < i["wrong"] < n_runs],
            "items": items}


def format_multi_report(s: dict) -> str:
    """Plain-text report for several runs."""
    def kind(i):                                   # which way is it wrong?
        return "false positive" if i["label"] == "noise" else "false negative"

    def line(i):
        scores = ",".join(map(str, i["scores"]))
        return (f"  #{i['id']:>2} you said {i['label']:6} ranker scores {scores}  "
                f"wrong {i['wrong']}/{s['runs']} ({kind(i)})  {i['headline'][:62]}")
    lines = [f"Ranker eval over {s['runs']} runs: score >= {SIGNAL_THRESHOLD} counts as signal",
             f"Agreement per run: {', '.join(f'{a}/{s['n']}' for a in s['agreements'])}",
             f"Mean agreement: {s['mean_correct']:.1f}/{s['n']} ({s['mean_agreement']:.0%});  "
             f"mean false positives {s['mean_fp']:.1f}, mean false negatives {s['mean_fn']:.1f}",
             f"Wrong in every run ({len(s['wrong_every_run'])}):", *map(line, s["wrong_every_run"]),
             f"Wrong in some runs ({len(s['wrong_some_runs'])}):", *map(line, s["wrong_some_runs"]),
             "", "All headlines (id, your label, ranker scores in each run):"]
    lines += [f"  {i['id']:>2}  {i['label']:6} {','.join(map(str, i['scores'])):<9} "
              f"{'ok  ' if not i['wrong'] else 'DIFF'}  {i['headline'][:62]}" for i in s["items"]]
    return "\n".join(lines)


def parse_runs(argv: list[str]) -> int:
    """`--runs N` from the command line (default 1)."""
    if "--runs" not in argv:
        return 1
    try:
        runs = int(argv[argv.index("--runs") + 1])
    except (IndexError, ValueError):
        raise EvalError("--runs needs a whole number") from None
    if not 1 <= runs <= MAX_RUNS:
        raise EvalError(f"--runs must be between 1 and {MAX_RUNS}")
    return runs


def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set. Export it (never put it in code).")
        return 1
    try:
        runs = parse_runs(sys.argv[1:])
        rows = load_labeled()
        client = anthropic.Anthropic()
        results = [compare(rows, rank_items(to_items(rows), client)) for _ in range(runs)]
    except EvalError as err:
        print(f"Eval not ready: {err}")
        return 1
    if runs == 1:
        result = results[0]
        report = format_report(result)
    else:
        result = summarize_runs(results)
        report = format_multi_report(result)
    print(report)
    (data_dir() / "eval_report.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    if path := os.environ.get("GITHUB_STEP_SUMMARY"):      # show it on the run page too
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"### Ranker eval ({profile_name()})\n```\n{report}\n```\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
