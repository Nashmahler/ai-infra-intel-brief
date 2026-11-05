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
    return {"what_happened": f"W{i}", "quote": f"quote number {i} here", "why_it_matters": f"Y{i}", "area": "power",
            "direction": "Risk", "channel": "Siting & timeline", "size": "unsized", "size_quote": "",
            "consider": "Ask whether to bring the Abilene date forward.",

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
    assert md.startswith("# AI Infrastructure Intelligence Brief — prepared for Crusoe\n\n*November 4, 2026*")
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


def test_writer_prompt_schema_and_title_follow_the_selected_profile(tmp_path, monkeypatch):
    """With another profile selected, no trace of Crusoe remains in what the model sees."""
    import yaml

    import src.config as config
    from src.write import build_schema, build_system_prompt
    (tmp_path / "acme.yaml").write_text(yaml.safe_dump({
        "company": {"name": "Acme Power", "description": "a developer of test fixtures",
                    "customers": ["Customer A"], "competitors": ["Rival A"],
                    "business_areas": ["generation", "retail"]},
        "facts": ["Acme has one fact."]}))
    monkeypatch.setattr(config, "PROFILES_DIR", tmp_path)
    monkeypatch.setenv("TARGET_PROFILE", "acme")

    prompt = build_system_prompt()
    assert "Acme Power" in prompt and "ACME POWER PROFILE" in prompt
    assert "generation, retail" in prompt and "Acme has one fact." in prompt
    assert "Crusoe" not in prompt
    schema = build_schema()["properties"]
    assert schema["top"]["items"]["properties"]["area"]["enum"] == ["generation", "retail"]
    assert "Acme Power" in schema["watchlist"]["items"]["properties"]["market"]["enum"]
    md = render_markdown({"top": [top(1)], "watchlist": [], "noise": []}, "2026-11-04", {},
                         {"scanned": 1, "kept": 1}, [])
    assert md.startswith("# AI Infrastructure Intelligence Brief — prepared for Acme Power")
    assert "Why it matters to Acme Power:" in md and "Crusoe" not in md


def test_prompt_shows_full_article_text_when_fetched_and_rss_summary_otherwise():
    from src.write import TEXT_CHARS, build_prompt
    prompt = build_prompt(RANKED, {"https://x.com/0": "FULL TEXT " * 1000})
    assert f"text (full article, first {TEXT_CHARS} chars): FULL TEXT" in prompt
    assert prompt.count("full article") == 1                 # only the fetched story
    assert "text (RSS summary only): text" in prompt          # the others fall back
    assert "FULL TEXT " * 1000 not in prompt                  # truncated, not dumped whole


def test_writer_prompt_requires_an_exact_quote_and_schema_has_the_field():
    from src.write import build_schema, build_system_prompt
    assert "copied EXACTLY" in build_system_prompt() and "4 and 24 words" in build_system_prompt()
    item = build_schema()["properties"]["top"]["items"]
    assert "quote" in item["properties"] and "quote" in item["required"]


def test_evidence_line_renders_small_with_its_source():
    from src.write import evidence_line
    base = {"quote": "a short quote here"}
    assert evidence_line({**base, "evidence_source": "article"}) == \
        '- <sub>**Evidence:** "a short quote here" (article text)</sub>'
    assert evidence_line({**base, "evidence_source": "summary"}).endswith('(RSS summary)</sub>')
    assert evidence_line(base) == '- <sub>**Evidence:** "a short quote here"</sub>'


def test_schema_limits_direction_and_channel_to_the_allowed_values():
    from src.write import CHANNELS, DIRECTIONS, build_schema
    props = build_schema()["properties"]["top"]["items"]
    assert props["properties"]["direction"]["enum"] == DIRECTIONS == ["Opportunity", "Risk"]
    assert props["properties"]["channel"]["enum"] == CHANNELS
    assert CHANNELS == ["Revenue & pricing", "Costs & margins", "Financing & cost of capital",
                        "Customers & pipeline", "Siting & timeline"]
    for field in ("direction", "channel", "size", "size_quote", "consider"):
        assert field in props["required"]


def test_writer_prompt_forbids_estimated_figures_and_generic_advice():
    from src.write import build_system_prompt
    p = build_system_prompt()
    assert "NEVER estimate" in p and "write exactly: unsized" in p
    assert "Financing & cost of capital" in p and "Siting & timeline" in p
    assert "No generic advice" in p and "BECAUSE of this story" in p


def test_draft_rendering_shows_the_impact_block_without_a_basis_note():
    from src.write import impact_lines
    item = {"direction": "Risk", "channel": "Costs & margins", "size": "$1 billion", "consider": "Ask X."}
    assert impact_lines(item)[3] == "  - **Size:** $1 billion"              # not verified yet: no 'stated in' claim
    assert impact_lines({**item, "size": "unsized"})[3] == "  - **Size:** unsized"


def test_writer_prompt_keeps_profile_figures_out_of_size_but_allows_them_as_exposure():
    from src.write import build_system_prompt
    p = " ".join(build_system_prompt().split())
    assert "NEVER take a figure from the Crusoe profile as the Size" in p
    assert "may appear in why_it_matters as Crusoe's exposure, but NEVER in Size" in p
    assert "or in the Crusoe profile above" not in p                       # the old permission is gone


def test_a_legacy_profile_basis_is_not_rendered_as_a_claim():
    from src.write import impact_lines
    item = {"direction": "Risk", "channel": "Costs & margins", "size": "1.2 GW",
            "size_basis": "profile", "consider": "Ask X."}
    assert impact_lines(item)[3] == "  - **Size:** 1.2 GW"                  # no "(from the company profile)"
