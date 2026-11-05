"""Eval-set sampler: stratified by ranker score, shuffled, no scores in the file."""
import hashlib
import json

import pytest
import yaml

import src.config as config
import src.evalset as evalset
from src.evalset import BANDS, exclude_overlap, has_labels, pick, render, too_similar

WORDS = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel", "india", "juliet",
         "kilo", "lima", "mike", "november", "oscar", "papa", "quebec", "romeo", "sierra", "tango"]


def item(n, score, **kw):
    # Unique, unrelated vocabulary per item (hex words), so neither the near-duplicate filter nor the
    # held-out "same story" exclusion ever fires by accident.
    h = hashlib.md5(str(n).encode()).hexdigest()
    title = f"{h[0:6]} {h[6:12]} {h[12:18]} {h[18:24]} {h[24:30]}"
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


# ------------------------------------------------------------- the held-out set

def reference(items):
    return [{"headline": i["title"], "link": i["link"]} for i in items]


def test_an_item_with_the_same_link_or_a_near_identical_title_is_excluded():
    items = pool()
    ref = reference(items[:3])
    same_link = {**item(500, 1), "link": items[0]["link"]}
    renamed = {**item(501, 1), "title": items[1]["title"] + " - Reuters"}
    kept = exclude_overlap(items[3:] + [same_link, renamed], ref)
    assert same_link not in kept and renamed not in kept and len(kept) == len(items) - 3


def test_loosely_similar_coverage_of_the_same_event_is_excluded_but_unrelated_news_is_not():
    a = "CoreWeave bonds hit new lows as Texas data centers come under scrutiny"
    assert too_similar(a, "CoreWeave bonds tumble to new lows after Texas elected a data center foe")
    assert too_similar(a, "Texas data centers in crosshairs as CoreWeave bonds hit lows")
    assert not too_similar(a, "Nvidia shipped CUDA 13.5 with Vera Rubin support for production")
    assert not too_similar(a, "Spark Liquid modular data center debuts in Brighton Colorado")


def test_the_whole_story_group_of_an_excluded_headline_goes_with_it():
    items = pool()
    ref = reference(items[:1])
    story = items[0]["story"]
    matched = {**item(601, 1), "title": items[0]["title"] + " - AP", "story": story}   # today's copy: excluded by title
    sibling = {**item(600, 1), "story": story}                                          # same story, different words
    other = item(602, 1, story=9999)
    kept = exclude_overlap(items[1:] + [matched, sibling, other], ref)
    assert matched not in kept and sibling not in kept       # the whole story group goes
    assert other in kept                                      # unrelated stories stay


def test_nothing_is_excluded_when_there_is_nothing_to_exclude_against():
    items = pool()
    assert exclude_overlap(items, []) == items


def test_the_heldout_file_explains_it_must_not_be_used_to_tune_the_prompt():
    text = render(pick(pool())[0], "Crusoe", "crusoe", heldout=True)
    assert text.startswith("# HELD-OUT set") and "do NOT change the prompt" in text
    assert "signal  = something Crusoe's strategy team would want to know" in text      # the label note is still there
    assert "# HELD-OUT" not in render(pick(pool())[0], "Crusoe", "crusoe")             # the main set does not carry it


@pytest.fixture
def two_sets(repo, monkeypatch):
    """The main labeled set (from the first 20 picks) already exists; build the held-out set beside it."""
    tmp = repo.parent.parent
    main_items = pool(40, 40, 40)
    (config.data_dir() / "2026-11-05_scores.json").write_text(json.dumps({"items": main_items}))
    first, _ = pick(main_items)
    labeled = yaml.safe_load(render(first, "Crusoe", "crusoe"))
    for h in labeled["headlines"]:
        h["label"] = "signal"
    repo.parent.mkdir(exist_ok=True)
    repo.write_text(yaml.safe_dump(labeled))
    monkeypatch.setattr("sys.argv", ["evalset", "2026-11-05", "--out", "evals/heldout_headlines.yaml",
                                     "--exclude", "evals/labeled_headlines.yaml"])
    return repo, tmp / "evals" / "heldout_headlines.yaml", first


def test_main_builds_a_heldout_set_that_shares_nothing_with_the_main_set(two_sets, capsys):
    labeled_file, heldout_file, first = two_sets
    before = labeled_file.read_text()
    assert evalset.main() == 0
    out = capsys.readouterr().out
    held = yaml.safe_load(heldout_file.read_text())["headlines"]
    assert len(held) == 20 and all(h["label"] is None for h in held)
    first_links = {i["link"] for i in first}
    first_stories = {i["story"] for i in first}
    chosen = {h["link"] for h in held}
    assert not chosen & first_links
    by_link = {i["link"]: i for i in pool(40, 40, 40)}
    assert not {by_link[l]["story"] for l in chosen} & first_stories
    assert not any(too_similar(h["headline"], f["title"]) for h in held for f in first)
    assert labeled_file.read_text() == before                                          # the main set is untouched
    assert "excluded" in out and "7 / 7 / 6" in out                                    # same score mix, and it says so


def test_the_heldout_file_has_the_heldout_note_and_no_scores(two_sets):
    _, heldout_file, _ = two_sets
    evalset.main()
    text = heldout_file.read_text()
    assert text.startswith("# HELD-OUT set") and "score:" not in text.lower()


def test_the_heldout_run_never_overwrites_its_own_labels(two_sets, capsys):
    _, heldout_file, _ = two_sets
    evalset.main()
    filled = heldout_file.read_text().replace("label:                 # signal | noise", "label: noise", 1)
    heldout_file.write_text(filled)
    assert evalset.main() == 1 and heldout_file.read_text() == filled
    assert "not overwriting" in capsys.readouterr().out
