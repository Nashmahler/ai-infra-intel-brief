"""Ranking tests use a stub client, so they need no API key or network."""
import json
from types import SimpleNamespace

import pytest

from src.rank import build_prompt, parse_scores, rank_items

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
