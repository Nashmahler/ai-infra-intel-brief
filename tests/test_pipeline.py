"""End-to-end (offline): sample feed -> collect -> rank -> write -> verify.

Claude is replaced by stubs; everything else is the real code. The 'writer'
invents one link, to prove the source check catches it at the end of the chain.
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import feedparser

from src.fetch import collect, entries_to_items
from src.rank import rank_items
from src.verify import build_final
from src.write import write_brief

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
SAMPLE = (Path(__file__).parent / "samples" / "sample_feed.xml").read_text()


def stub(reply):
    msg = SimpleNamespace(stop_reason="end_turn",
                          content=[SimpleNamespace(type="text", text=json.dumps(reply))])
    return SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: msg))


def test_fake_link_from_the_writer_never_reaches_the_published_brief():
    fetcher = lambda feed, now: entries_to_items(feedparser.parse(SAMPLE), feed["name"], now)
    raw = collect([{"name": "Sample", "url": ""}], ["CoreWeave"], NOW, fetcher)
    assert raw["stats"]["kept"] == 1

    ranked = rank_items(raw["items"], stub(
        {"scores": [{"id": 0, "score": 5, "story": 0, "reason": "major"}]}))
    real = ranked[0]["link"]

    top = lambda link: {"what_happened": "W", "quote": "announced a power purchase agreement",
                        "why_it_matters": "Y", "area": "power",
                        "direction": "Risk", "channel": "Siting & timeline", "size": "unsized",
                        "size_quote": "", "consider": "Ask whether the Abilene timeline holds.",
                        "confidence": "Reported", "link": link}
    brief = write_brief(ranked, stub({"top": [top(real), top("https://fake.example/invented")],
                                      "watchlist": [], "noise": []}))
    md, removals, verified = build_final("2026-11-04", raw, brief)

    assert verified
    assert real in md and "fake.example" not in md
    assert [r["link"] for r in removals] == ["https://fake.example/invented"]


def test_all_feeds_down_produces_the_no_brief_file():
    def down(feed, now):
        raise RuntimeError("connection refused")
    raw = collect([{"name": "A", "url": ""}, {"name": "B", "url": ""}], ["CoreWeave"], NOW, down)
    md, _, verified = build_final("2026-11-04", raw, None)
    assert not verified and "No verified brief today" in md
    assert "sources that failed to load: A, B" in md


def test_fabricated_quote_from_the_writer_fails_closed_end_to_end():
    fetcher = lambda feed, now: entries_to_items(feedparser.parse(SAMPLE), feed["name"], now)
    raw = collect([{"name": "Sample", "url": ""}], ["CoreWeave"], NOW, fetcher)
    ranked = rank_items(raw["items"], stub(
        {"scores": [{"id": 0, "score": 5, "story": 0, "reason": "major"}]}))
    invented = {"what_happened": "W", "quote": "CoreWeave will build a campus on the moon",
                "why_it_matters": "Y", "area": "power", "confidence": "Reported",
                "direction": "Risk", "channel": "Siting & timeline", "size": "unsized",
                "size_quote": "", "consider": "Ask whether the Abilene timeline holds.",
                "link": ranked[0]["link"]}                      # a REAL link, an invented quote
    brief = write_brief(ranked, stub({"top": [invented], "watchlist": [], "noise": []}))
    md, log, verified = build_final("2026-11-04", raw, brief)
    assert not verified and "No verified brief today" in md
    assert log[0]["reason"] == "quote not found in the source text"
