"""Eval-set sampler: stratified by ranker score, shuffled, no scores in the file."""
import json

import pytest
import yaml

import src.config as config
import src.evalset as evalset
from src.evalset import BANDS, has_labels, pick, render

WORDS = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel", "india", "juliet",
         "kilo", "lima", "mike", "november", "oscar", "papa", "quebec", "romeo", "sierra", "tango"]


def item(n, score, **kw):
    # Distinct, unrelated titles so the near-duplicate filter never fires by accident.
    title = f"{WORDS[n % 20]} {WORDS[(n * 7 + 3) % 20]} {n * 9973} announces unrelated {WORDS[(n * 3) % 20]} plan {n}"
    return {"title": title, "link": f"https://pub.com/{n}", "source": "Feed", "publisher": f"Pub{n}",
            "published": "2026-11-05T12:00:00+00:00", "summary": f"Summary {n}.", "score": score,
            "story": n, "is_lead": True, **kw}


def pool(high=30, mid=30, low=30):
    scores = [5, 4] * (high // 2) + [3, 2] * (mid // 2) + [1] * low
    return [item(n, s) for n, s in enumerate(scores)]


def band(i):
    return next(name for name, lo, hi, _ in BANDS if lo <= i["score"] <= hi)


def test_picks_twenty_stratified_7_7_6():
    chosen, counts = pick(pool())
    assert len(chosen) == 20 and counts == {"high": 7, "mid": 7, "low": 6}
    assert [sum(band(i) == b for i in chosen) for b in ("high", "mid", "low")] == [7, 7, 6]


def test_no_duplicates_and_only_one_item_per_story():
    items = pool()
    items += [item(1000 + n, 1, story=n, is_lead=False) for n in range(10)]       # copies of existing stories
    chosen, _ = pick(items)
    assert len({i["link"] for i in chosen}) == 20 and all(i["is_lead"] for i in chosen)


def test_near_identical_titles_are_never_both_picked():
    items = [item(n, 5) for n in range(8)] + [{**item(100 + n, 5), "title": item(n, 5)["title"] + " - Reuters"}
                                                for n in range(8)]
    items += pool(0, 30, 30)
    chosen, _ = pick(items)
    titles = [i["title"].removesuffix(" - Reuters") for i in chosen]
    assert len(titles) == len(set(titles))


def test_the_order_is_shuffled_not_grouped_by_band():
    grouped = lambda chosen: [band(i) for i in chosen] == sorted((band(i) for i in chosen), key=("high", "mid", "low").index)
    results = [grouped(pick(pool(), seed)[0]) for seed in range(25)]
    assert not all(results) and not any(results)         # essentially never ordered by band


def test_same_seed_same_sample_different_seed_different_sample():
    a, b, c = pick(pool(), 1)[0], pick(pool(), 1)[0], pick(pool(), 2)[0]
    assert [i["link"] for i in a] == [i["link"] for i in b] and [i["link"] for i in a] != [i["link"] for i in c]


def test_a_thin_band_is_topped_up_so_the_total_stays_twenty():
    chosen, counts = pick(pool(high=2, mid=30, low=30))
    assert len(chosen) == 20 and counts["high"] == 2 and sum(counts.values()) == 20


def test_too_little_data_gives_fewer_rather_than_repeats():
    chosen, _ = pick(pool(2, 2, 2))
    assert len(chosen) == 6 and len({i["link"] for i in chosen}) == 6


def test_items_without_a_title_or_source_are_skipped():
    items = pool() + [{**item(999, 5), "title": ""}, {**item(998, 5), "publisher": "", "source": ""}]
    assert all(i["title"] for i in pick(items)[0])


# -------------------------------------------------------------- the file itself

def written(chosen):
    return yaml.safe_load(render(chosen, "Crusoe", "crusoe"))


def test_every_headline_has_an_empty_label_and_no_ranker_score_anywhere():
    chosen, _ = pick(pool())
    text = render(chosen, "Crusoe", "crusoe")
    data = yaml.safe_load(text)
    assert [h["id"] for h in data["headlines"]] == list(range(1, 21))
    assert all(h["label"] is None for h in data["headlines"])
    assert all(set(h) == {"id", "headline", "source", "published", "link", "summary", "label"}
               for h in data["headlines"])
    assert "score:" not in text.lower() and "band" not in text.lower()          # no score field or value
    assert "ranker scores are stored here" in text                             # (the note says so, on purpose)


def test_the_note_explains_the_labels_and_names_the_company_from_the_profile():
    text = render(pick(pool())[0], "Acme Power", "acme")
    assert "signal  = something Acme Power's strategy team would want to know" in text
    assert "noise   = not worth their attention" in text and "profile: acme" in text


def test_awkward_characters_survive_the_round_trip():
    odd = {**item(1, 5), "title": 'He said: "go" — it\'s 50% off # not a comment', "summary": "line one\nline two"}
    [h] = written([odd])["headlines"]
    assert h["headline"] == odd["title"] and h["summary"] == "line one\nline two"


# --------------------------------------------------------------------- the command

@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setattr(evalset, "ROOT", tmp_path)
    monkeypatch.setattr(evalset, "EVALS_FILE", tmp_path / "evals" / "labeled_headlines.yaml")
    monkeypatch.delenv("TARGET_PROFILE", raising=False)
    monkeypatch.setattr("sys.argv", ["evalset", "2026-11-05"])
    (config.data_dir() / "2026-11-05_scores.json").write_text(json.dumps({"items": pool()}))
    return tmp_path / "evals" / "labeled_headlines.yaml"


def test_main_writes_twenty_unlabeled_headlines(repo, capsys):
    assert evalset.main() == 0
    data = yaml.safe_load(repo.read_text())
    assert len(data["headlines"]) == 20 and data["profile"] == "crusoe"
    assert not has_labels(repo) and "labels are empty" in capsys.readouterr().out


def test_main_never_overwrites_labels_without_force(repo, capsys):
    evalset.main()
    filled = repo.read_text().replace("label:                 # signal | noise", "label: signal", 1)
    repo.write_text(filled)
    assert has_labels(repo)
    assert evalset.main() == 1 and repo.read_text() == filled and "not overwriting" in capsys.readouterr().out
    monkey_args = ["evalset", "2026-11-05", "--force"]
    import sys
    sys.argv = monkey_args
    assert evalset.main() == 0 and not has_labels(repo)


def test_main_without_scores_explains_and_fails(repo, capsys):
    (config.data_dir() / "2026-11-05_scores.json").unlink()
    assert evalset.main() == 1 and "run fetch and rank first" in capsys.readouterr().out
