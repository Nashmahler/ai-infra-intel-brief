"""Writer tests: stub client, no API key or network."""
import json
from types import SimpleNamespace

from src.write import render_markdown, write_brief

RANKED = [{"title": f"Item {i}", "link": f"https://x.com/{i}", "source": "S",
           "publisher": "Pub", "published": "2026-11-04T00:00:00+00:00", "summary": "text",
           "score": 5 - i % 5, "reason": "r", "story": i, "coverage": 1,
           "story_score": 5 - i % 5, "is_lead": True} for i in range(30)]


def stub(reply):
    msg = SimpleNamespace(stop_reason="end_turn",
                          content=[SimpleNamespace(type="text", text=json.dumps(reply))])
    return SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: msg))


def top(i):
    return {"what_happened": f"W{i}", "why_it_matters": f"Y{i}", "area": "power",
            "confidence": "Reported", "link": f"https://x.com/{i}"}


def test_sections_are_trimmed_to_spec_limits():
    reply = {"top": [top(i) for i in range(5)],
             "watchlist": [{"market": "Chips & hardware", "line": "l", "link": f"https://x.com/{i}"}
                           for i in range(10, 19)],
             "noise": [{"reason": "r", "link": f"https://x.com/{i}"} for i in range(20, 29)]}
    b = write_brief(RANKED, stub(reply))
    assert (len(b["top"]), len(b["watchlist"]), len(b["noise"])) == (3, 6, 5)


def test_markdown_follows_spec_format():
    brief = {"top": [top(1)],
             "watchlist": [{"market": "Power & energy", "line": "A line", "link": "https://x.com/2"}],
             "noise": [{"reason": "opinion piece", "link": "https://x.com/3"}]}
    articles = {f"https://x.com/{i}": {"title": f"Item {i}", "publisher": "Pub"}
                for i in (1, 2, 3)}
    md = render_markdown(brief, "2026-11-04", articles, {"scanned": 90, "kept": 12}, ["Feed A"])
    assert md.startswith("# Crusoe Intelligence Brief — November 4, 2026")
    for part in ["## Top 3 developments", "- **What happened:** W1",
                 "- **Why it matters to Crusoe:** Y1", "- **Confidence:** Reported",
                 "- **Source:** [Item 1](https://x.com/1) (Pub)", "## Watchlist roundup",
                 "- **Power & energy:** A line — [Pub](https://x.com/2)",
                 "## Noise we ignored", "- [Item 3](https://x.com/3) (Pub) — opinion piece",
                 "Articles scanned: 90 · kept: 12 · sources that failed to load: Feed A"]:
        assert part in md


def test_footer_says_none_when_no_sources_failed():
    md = render_markdown({"top": [], "watchlist": [], "noise": []}, "2026-11-04", {},
                         {"scanned": 1, "kept": 0}, [])
    assert "failed to load: none" in md


def test_one_story_cannot_fill_the_top_three():
    """Items 0 and 1 are the same story: only the first may appear."""
    ranked = [{**r, "story": 0 if r["link"] in ("https://x.com/0", "https://x.com/1") else r["story"]}
              for r in RANKED]
    reply = {"top": [top(0), top(1), top(2), top(3)], "watchlist": [], "noise": []}
    out = write_brief(ranked, stub(reply))
    assert [t["link"] for t in out["top"]] == ["https://x.com/0", "https://x.com/2", "https://x.com/3"]


def test_story_in_top_is_not_repeated_in_watchlist_and_links_are_unique():
    wl = lambda i: {"market": "Chips & hardware", "line": "l", "link": f"https://x.com/{i}"}
    reply = {"top": [top(0)], "watchlist": [wl(0), wl(4), wl(4)],
             "noise": [{"reason": "r", "link": "https://x.com/4"}]}
    out = write_brief(RANKED, stub(reply))
    assert [w["link"] for w in out["watchlist"]] == ["https://x.com/4"]
    assert out["noise"] == []          # link 4 already used


def test_prompt_includes_profile_and_coverage():
    from src.write import build_prompt, build_system_prompt
    assert "Abilene" in build_system_prompt() and "Brighton" in build_system_prompt()
    assert "coverage: 1 outlet" in build_prompt(RANKED)
