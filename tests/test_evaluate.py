"""Eval script tests: stub client, temp folders, no network. Plus a check of the real eval file."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import src.evaluate as evaluate
from src.evaluate import (EvalError, compare, format_multi_report, format_report, load_labeled, parse_runs,
                          summarize_runs, to_items)

REAL_FILE = Path(__file__).resolve().parent.parent / "evals" / "labeled_headlines.yaml"


def rows(labels):
    return [{"id": i + 1, "headline": f"Headline {i + 1}", "source": f"Pub{i + 1}", "published": "2026-11-05T12:00:00+00:00",
             "link": f"https://pub.com/{i + 1}", "summary": f"Summary {i + 1}.", "label": lab} for i, lab in enumerate(labels)]


def scored(scores):
    return [{"id": i + 1, "score": s, "reason": f"reason {i + 1}"} for i, s in enumerate(scores)]


# ---------------------------------------------------------------- the real file

def test_the_committed_eval_file_is_complete_and_labeled():
    loaded = load_labeled(REAL_FILE)
    assert len(loaded) == 20 and [r["id"] for r in loaded] == list(range(1, 21))
    assert {r["label"] for r in loaded} == {"signal", "noise"}
    assert sum(r["label"] == "signal" for r in loaded) == 8
    assert all(r["headline"] and r["source"] for r in loaded)


# ---------------------------------------------------------------------- loading

def write(tmp_path, labels):
    path = tmp_path / "labeled.yaml"
    path.write_text(yaml.safe_dump({"profile": "crusoe", "headlines": [
        {**{k: v for k, v in r.items() if k != "label"}, "label": lab} for r, lab in zip(rows(["x"] * len(labels)), labels)]}))
    return path


def test_labels_are_normalized_and_validated(tmp_path):
    assert [r["label"] for r in load_labeled(write(tmp_path, ["Signal", " NOISE ", "noise"]))] == ["signal", "noise", "noise"]


@pytest.mark.parametrize("labels,ids", [(["signal", None, "noise"], "2"), (["signal", "maybe", "noise"], "2"),
                                        ([None, None, "noise"], "1, 2"), (["", "signal"], "1")])
def test_missing_or_invalid_labels_are_listed_by_id(tmp_path, labels, ids):
    with pytest.raises(EvalError, match=f"id\\(s\\) {ids}"):
        load_labeled(write(tmp_path, labels))


def test_duplicate_ids_empty_and_missing_files_are_errors(tmp_path):
    dup = tmp_path / "dup.yaml"
    dup.write_text(yaml.safe_dump({"headlines": [{"id": 1, "label": "signal"}, {"id": 1, "label": "noise"}]}))
    with pytest.raises(EvalError, match="duplicate"):
        load_labeled(dup)
    empty = tmp_path / "empty.yaml"
    empty.write_text("headlines: []")
    with pytest.raises(EvalError, match="no headlines"):
        load_labeled(empty)
    with pytest.raises(EvalError, match="not found"):
        load_labeled(tmp_path / "nope.yaml")


def test_items_have_the_shape_the_ranker_expects():
    [item] = to_items(rows(["signal"]))
    assert item == {"id": 1, "title": "Headline 1", "link": "https://pub.com/1", "source": "Pub1", "publisher": "Pub1",
                    "published": "2026-11-05T12:00:00+00:00", "summary": "Summary 1."}


# -------------------------------------------------------------------- comparing

def test_confusion_counts_agreement_precision_recall_and_the_lists():
    labels = ["signal", "signal", "signal", "noise", "noise", "noise", "noise", "signal"]
    scores = [5, 4, 2, 3, 1, 1, 2, 1]       # TP, TP, FN, FP, TN, TN, TN, FN
    r = compare(rows(labels), scored(scores))
    assert (r["tp"], r["tn"], r["fp"], r["fn"]) == (2, 3, 1, 2) and r["n"] == 8
    assert r["agreement"] == 5 / 8 and r["precision"] == 2 / 3 and r["recall"] == 2 / 4
    assert [i["id"] for i in r["false_positives"]] == [4] and [i["id"] for i in r["false_negatives"]] == [3, 8]


def test_a_score_of_exactly_three_is_signal_and_two_is_noise():
    r = compare(rows(["signal", "noise"]), scored([3, 2]))
    assert r["agreement"] == 1.0 and [i["predicted"] for i in r["items"]] == ["signal", "noise"]


def test_perfect_agreement_and_no_signal_cases_do_not_divide_by_zero():
    perfect = compare(rows(["signal", "noise"]), scored([5, 1]))
    assert perfect["agreement"] == 1.0 and perfect["false_positives"] == perfect["false_negatives"] == []
    none_called = compare(rows(["noise", "noise"]), scored([1, 2]))
    assert none_called["precision"] is None and none_called["recall"] is None and none_called["agreement"] == 1.0
    assert "Precision (of what the ranker called signal, how much you agreed): n/a" in format_report(none_called)


def test_a_missing_score_is_an_error_not_a_silent_miss():
    with pytest.raises(EvalError, match="no score for id"):
        compare(rows(["signal", "noise"]), scored([5]))


def test_the_report_leads_with_agreement_and_lists_the_misses_with_the_rankers_reason():
    r = compare(rows(["signal", "noise", "noise"]), scored([1, 4, 1]))
    text = format_report(r)
    assert "Agreement: 1/3 (33%)" in text and "False positives (ranker said signal, you said noise): 1" in text
    assert "#2 score 4: Headline 2  [Pub2]" in text and "ranker: reason 2" in text
    assert "False negatives (ranker said noise, you said signal): 1" in text and "#1 score 1: Headline 1" in text
    assert "score >= 3 counts as signal" in text


# -------------------------------------------------------------------- the command

def stub_client(scores):
    reply = {"scores": [{"id": i, "score": s, "story": i, "reason": f"reason {i}"} for i, s in enumerate(scores)]}
    msg = SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=json.dumps(reply))])
    return SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: msg))


@pytest.fixture
def repo(tmp_path, monkeypatch):
    out = tmp_path / "data"
    out.mkdir()
    monkeypatch.setattr(evaluate, "data_dir", lambda: out)        # only the output goes to the temp folder:
    monkeypatch.delenv("TARGET_PROFILE", raising=False)           # the ranker still reads the real config
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path / "summary.md"))
    return tmp_path


def test_main_runs_the_ranker_on_the_labeled_headlines_and_reports(repo, monkeypatch, capsys):
    path = write(repo, ["signal", "noise", "noise", "signal"])
    monkeypatch.setattr(evaluate, "EVALS_FILE", path)
    monkeypatch.setattr(evaluate.anthropic, "Anthropic", lambda: stub_client([5, 4, 1, 1]))   # ids by position
    assert evaluate.main() == 0
    out = capsys.readouterr().out
    assert "Agreement: 2/4 (50%)" in out
    saved = json.loads((repo / "data" / "eval_report.json").read_text())
    assert (saved["tp"], saved["tn"], saved["fp"], saved["fn"]) == (1, 1, 1, 1)
    assert "Ranker eval (crusoe)" in (repo / "summary.md").read_text()


def test_main_refuses_an_unlabeled_file_and_a_missing_key(repo, monkeypatch, capsys):
    monkeypatch.setattr(evaluate, "EVALS_FILE", write(repo, ["signal", None]))
    assert evaluate.main() == 1 and "Eval not ready" in capsys.readouterr().out
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert evaluate.main() == 1 and "ANTHROPIC_API_KEY is not set" in capsys.readouterr().out


# ----------------------------------------------------------------- several runs

def runs_of(labels, *score_lists):
    return [compare(rows(labels), scored(s)) for s in score_lists]


def test_summary_averages_agreement_and_finds_stable_and_flaky_misses():
    labels = ["signal", "signal", "noise", "noise"]
    summary = summarize_runs(runs_of(labels,
                                     [5, 2, 1, 1],       # #2 wrong
                                     [5, 2, 3, 1],       # #2 wrong, #3 wrong
                                     [5, 3, 1, 1]))      # all right
    assert summary["runs"] == 3 and summary["agreements"] == [3, 2, 4]
    assert summary["mean_correct"] == 3.0 and summary["mean_agreement"] == 0.75
    assert summary["mean_fp"] == 1 / 3 and summary["mean_fn"] == 2 / 3
    assert [i["id"] for i in summary["wrong_every_run"]] == []
    assert [(i["id"], i["wrong"], i["scores"]) for i in summary["wrong_some_runs"]] == [(2, 2, [2, 2, 3]), (3, 1, [1, 3, 1])]


def test_a_headline_wrong_in_every_run_is_called_out_with_its_direction():
    summary = summarize_runs(runs_of(["signal", "noise"], [2, 4], [1, 3], [2, 3]))
    assert [i["id"] for i in summary["wrong_every_run"]] == [1, 2]
    text = format_multi_report(summary)
    assert "Wrong in every run (2):" in text and "(false negative)" in text and "(false positive)" in text
    assert "ranker scores 2,1,2" in text and "wrong 3/3" in text


def test_the_multi_run_report_leads_with_per_run_and_mean_agreement():
    summary = summarize_runs(runs_of(["signal", "noise"] * 2, [5, 1, 5, 1], [5, 1, 2, 1], [5, 1, 5, 3]))
    text = format_multi_report(summary)
    assert "Ranker eval over 3 runs: score >= 3 counts as signal" in text
    assert "Agreement per run: 4/4, 3/4, 3/4" in text and "Mean agreement: 3.3/4 (83%)" in text
    assert "Wrong in some runs (2):" in text and "All headlines" in text


def test_parse_runs_defaults_to_one_and_validates():
    assert parse_runs([]) == 1 and parse_runs(["--runs", "3"]) == 3
    for bad in (["--runs"], ["--runs", "x"], ["--runs", "0"], ["--runs", "11"]):
        with pytest.raises(EvalError):
            parse_runs(bad)


def test_main_with_runs_ranks_that_many_times_and_reports_the_mean(repo, monkeypatch, capsys):
    path = write(repo, ["signal", "noise"])
    monkeypatch.setattr(evaluate, "EVALS_FILE", path)
    answers = iter([[5, 1], [2, 1], [5, 4]])                         # run 2 misses #1, run 3 flags #2

    def client_with_a_new_answer_each_call():
        def create(**kw):
            return stub_client(next(answers)).messages.create(**kw)
        return SimpleNamespace(messages=SimpleNamespace(create=create))
    monkeypatch.setattr(evaluate.anthropic, "Anthropic", client_with_a_new_answer_each_call)
    monkeypatch.setattr("sys.argv", ["evaluate", "--runs", "3"])
    assert evaluate.main() == 0
    out = capsys.readouterr().out
    assert "Agreement per run: 2/2, 1/2, 1/2" in out and "Mean agreement: 1.3/2 (67%)" in out
    saved = json.loads((repo / "data" / "eval_report.json").read_text())
    assert saved["runs"] == 3 and saved["agreements"] == [2, 1, 1]
