"""Ranking tests use a stub client, so they need no API key or network."""
import json
from types import SimpleNamespace

import pytest

from src.rank import add_story_fields, build_prompt, build_system_prompt, parse_scores, rank_items

ITEMS = [
    {"title": "CoreWeave signs power deal", "link": "https://a.com/1", "source": "DCD",
     "published": "2026-11-04T01:00:00+00:00", "summary": "A deal."},
    {"title": "Lambda function tips", "link": "https://b.com/2", "source": "Blog",
     "published": "2026-11-04T02:00:00+00:00", "summary": "Python."},
]


def stub_client(reply, stop_reason="end_turn"):
    """A fake Anthropic client that returns `reply` (a dict) as JSON text."""
    msg = SimpleNamespace(stop_reason=stop_reason,
                          content=[SimpleNamespace(type="text", text=json.dumps(reply))])
    return SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: msg))


def test_prompt_numbers_items_and_omits_links():
    prompt = build_prompt(ITEMS)
    assert "[0] CoreWeave" in prompt and "[1] Lambda" in prompt
    assert "https://" not in prompt


def test_parse_scores_drops_bad_ids_and_out_of_range_scores():
    good = parse_scores({"scores": [
        {"id": 0, "score": 5, "reason": "ok"},
        {"id": 7, "score": 3, "reason": "no such item"},
        {"id": 1, "score": 9, "reason": "out of range"},
    ]}, n_items=2)
    assert list(good) == [0]


def test_rank_sorts_best_first_and_keeps_links():
    reply = {"scores": [{"id": 0, "score": 5, "reason": "major"},
                        {"id": 1, "score": 1, "reason": "unrelated"}]}
    ranked = rank_items(ITEMS, stub_client(reply))
    assert [r["score"] for r in ranked] == [5, 1]
    assert ranked[0]["link"] == "https://a.com/1"


def test_item_the_model_skipped_gets_lowest_score():
    ranked = rank_items(ITEMS, stub_client({"scores": [{"id": 0, "score": 4, "reason": "x"}]}))
    assert ranked[-1]["score"] == 1 and "not scored" in ranked[-1]["reason"]


def test_refusal_raises_instead_of_guessing():
    with pytest.raises(RuntimeError):
        rank_items(ITEMS, stub_client({"scores": []}, stop_reason="refusal"))


def test_no_items_means_no_api_call():
    assert rank_items([], client=None) == []


def scored(i, score, story, pub, published="2026-11-04T00:00:00+00:00"):
    return {"title": f"t{i}", "source": "feed", "publisher": pub, "published": published,
            "score": score, "story": story}


def test_wide_coverage_boosts_story_but_only_one_lead():
    items = [scored(0, 3, 0, "A"), scored(1, 2, 0, "B"), scored(2, 2, 0, "C"),
             scored(3, 3, 3, "D")]
    out = add_story_fields(items)
    story0 = [i for i in out if i["story"] == 0]
    assert all(i["story_score"] == 4 and i["coverage"] == 3 for i in story0)   # 3 + boost
    assert sum(i["is_lead"] for i in story0) == 1
    assert out[0]["story"] == 0                      # outranks the single-source 3


def test_same_outlet_repeats_and_noise_get_no_boost():
    same = add_story_fields([scored(0, 3, 0, "A"), scored(1, 3, 0, "A"), scored(2, 3, 0, "A")])
    assert same[0]["story_score"] == 3               # one outlet, no boost
    noise = add_story_fields([scored(i, 1, 0, p) for i, p in enumerate("ABC")])
    assert noise[0]["story_score"] == 1              # never lifts a 1


def test_ranker_prompt_has_profile_and_story_grouping():
    p = build_system_prompt()
    assert "1.2 GW Abilene" in p and "same underlying event" in p
    assert "scoring news items for Crusoe" in p and "Oracle, Microsoft" in p
    assert "AI compute & cloud" in p            # markets come from watchlist.yaml


# ------------------------------------------------- the relevance-first ranking rules

def flat(text):
    return " ".join(text.split())


def test_relevance_is_decided_before_novelty_and_source_quality():
    p = build_system_prompt()
    assert p.index("1. Relevance") < p.index("2. Novelty") < p.index("3. Source quality")
    assert "comes FIRST" in p


def test_a_weak_source_lowers_confidence_never_the_score_of_a_relevant_story():
    p = flat(build_system_prompt())
    assert "Source quality is about CONFIDENCE, not relevance" in p
    assert 'the brief labels it "Reported"' in p
    assert "must NEVER lower the score of a story that is relevant and new" in p
    assert "A relevant, new story from a weak outlet scores at least 3" in p
    assert "its reason must say that the outlet is weak" in p
    assert "and say in it when the source is weak" in p


def test_opinion_with_no_new_facts_is_penalised_for_novelty_not_for_its_source():
    p = flat(build_system_prompt())
    assert "Opinion and commentary with no new facts score low for THIS reason" in p
    assert "opinion pieces and aggregator reposts lowest" not in p.lower()        # the old source-quality rule is gone


def test_vendor_and_supplier_announcements_score_2_unless_cost_capacity_or_supply_is_affected():
    p = flat(build_system_prompt())
    assert "Vendor and supplier product announcements" in p and "score 2, unless" in p
    assert "directly affects Crusoe's cost, capacity, or supply" in p
    assert "only then may they score 3 or more" in p


def test_the_profile_and_story_grouping_rules_are_untouched():
    p = build_system_prompt()
    assert "1.2 GW Abilene" in p and "same underlying event" in p and "Oracle, Microsoft" in p
