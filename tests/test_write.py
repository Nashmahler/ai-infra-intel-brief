"""Writer tests: stub client, no API key or network."""
import json
from types import SimpleNamespace

from src.config import agent_for
from src.write import render_markdown, write_brief

RANKED = [{"title": f"Item {i}", "link": f"https://x.com/{i}", "source": "S",
           "published": "2026-11-04T00:00:00+00:00", "summary": "text",
           "score": 5 - i % 5, "reason": "r"} for i in range(30)]


def stub(reply):
    msg = SimpleNamespace(stop_reason="end_turn",
                          content=[SimpleNamespace(type="text", text=json.dumps(reply))])
    return SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: msg))


def top(i):
    return {"what_happened": f"W{i}", "why_it_matters": f"Y{i}", "area": "power",
            "confidence": "Reported", "link": f"https://x.com/{i}"}


def test_sections_are_trimmed_to_spec_limits():
    reply = {"top": [top(i) for i in range(5)],
             "watchlist": [{"market": "Chips & hardware", "line": "l", "link": "u"}] * 9,
             "noise": [{"reason": "r", "link": "u"}] * 9}
    b = write_brief(RANKED, stub(reply))
    assert (len(b["top"]), len(b["watchlist"]), len(b["noise"])) == (3, 6, 5)


def test_markdown_follows_spec_format():
    brief = {"top": [top(1)],
             "watchlist": [{"market": "Power & energy", "line": "A line", "link": "https://x.com/2"}],
             "noise": [{"reason": "opinion piece", "link": "https://x.com/3"}]}
    titles = {"https://x.com/1": "Item 1", "https://x.com/2": "Item 2", "https://x.com/3": "Item 3"}
    md = render_markdown(brief, "2026-11-04", titles, {"scanned": 90, "kept": 12}, ["Feed A"])
    assert md.startswith("# Crusoe Intelligence Brief — November 4, 2026")
    for part in ["## Top 3 developments", "- **What happened:** W1",
                 "- **Why it matters to Crusoe:** Y1", "- **Confidence:** Reported",
                 "- **Source:** [Item 1](https://x.com/1)", "## Watchlist roundup",
                 "- **Power & energy:** A line — [Item 2](https://x.com/2)",
                 "## Noise we ignored", "- [Item 3](https://x.com/3) — opinion piece",
                 "Articles scanned: 90 · kept: 12 · sources that failed to load: Feed A"]:
        assert part in md


def test_footer_says_none_when_no_sources_failed():
    md = render_markdown({"top": [], "watchlist": [], "noise": []}, "2026-11-04", {},
                         {"scanned": 1, "kept": 0}, [])
    assert "failed to load: none" in md


def test_sec_feeds_need_a_user_agent(monkeypatch):
    import pytest
    from src.config import MissingConfig
    feed = {"name": "SEC", "url": "u", "agent_env": "SEC_USER_AGENT"}
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    with pytest.raises(MissingConfig):
        agent_for(feed)
    monkeypatch.setenv("SEC_USER_AGENT", "crusoe-intel-brief me@example.com")
    assert agent_for(feed) == "crusoe-intel-brief me@example.com"
