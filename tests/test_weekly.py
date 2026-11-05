"""Weekly synthesis tests: stub client, temp folders, no network."""
import json
from datetime import date
from types import SimpleNamespace

import pytest

import src.config as config
import src.weekly as weekly
from src.weekly import (OPPORTUNITY_KINDS, SCHEMA, add_section, build_system_prompt, collect_briefs,
                        plain_text, render_opportunities, render_section, verify_opportunities,
                        verify_themes)

FRIDAY = "2026-11-06"


def brief_md(day, headline="Anti-data center ballot measures are reportedly on track to pass"):
    return (f"# AI Infrastructure Intelligence Brief — prepared for Crusoe\n\n*{day}*\n\n"
            f"## Top 3 developments\n\n**1.**\n- **What happened:** {headline}.\n"
            f"- **Source:** [Some headline](https://pub.com/{day}) (Pub)\n"
            f'- <sub>**Evidence:** "{headline[:40]}"</sub>\n\n'
            f"## Noise we ignored\n\n- nothing\n\n---\n*Articles scanned: 9 · kept: 3 · "
            f"sources that failed to load: none*\n")


NO_BRIEF = "# T\n\n**No verified brief today.**\n\nReason: x.\n"


@pytest.fixture
def folder(tmp_path, monkeypatch):
    """A temp repo root with briefs/crusoe/ holding a week of briefs."""
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.delenv("TARGET_PROFILE", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    d = config.briefs_dir()
    for day in ("2026-10-28", "2026-11-03", "2026-11-04", "2026-11-05", FRIDAY):
        (d / f"{day}.md").write_text(brief_md(day))
    (d / "2026-11-02.md").write_text(NO_BRIEF)             # a failed day
    (d / "README.md").write_text("# index")                 # not a brief
    return d


def stub_client(reply):
    msg = SimpleNamespace(stop_reason="end_turn",
                          content=[SimpleNamespace(type="text", text=json.dumps(reply))])
    return SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: msg))


def theme(days=("2026-11-03", "2026-11-04"), quote="ballot measures are reportedly on track to pass", **kw):
    return {"title": "Local backlash", "summary": "S1. S2.", "days": list(days), "quote": quote, **kw}


BRIEFS = {"2026-11-03": "Anti-data center ballot measures are reportedly on track to pass in Texas towns.",
          "2026-11-04": "Nvidia told partners to cut China exposure, according to DCD."}


# ------------------------------------------------------------ reading briefs

def test_plain_text_strips_markdown_but_keeps_the_words():
    md = "- **What happened:** See [Big news](https://x.com/a) now.\n<sub>**Evidence:** \"q\"</sub>"
    assert plain_text(md) == 'What happened: See Big news now.\nEvidence: "q"'


def test_collect_briefs_uses_the_last_seven_days_of_verified_briefs_only(folder):
    found = collect_briefs(folder, FRIDAY)
    assert list(found) == ["2026-11-03", "2026-11-04", "2026-11-05", FRIDAY]   # oldest first
    # excluded: 10-28 (older than a week), 11-02 (no verified brief), README.md (not a brief)


# ------------------------------------------------------ theme verification

def test_a_theme_with_two_real_citations_and_a_real_quote_survives():
    clean, log = verify_themes([theme()], BRIEFS)
    assert len(clean) == 1 and log == []


def test_fabricated_quote_removes_the_theme_and_is_logged():
    clean, log = verify_themes([theme(quote="data center moratoriums swept every Texas county")], BRIEFS)
    assert clean == [] and log[0]["reason"] == "quote not found in the source text"
    assert log[0]["quote"].startswith("data center moratoriums")


def test_quote_must_come_from_a_cited_brief_not_just_any_brief():
    clean, _ = verify_themes([theme(quote="Nvidia told partners to cut China exposure",
                                    days=("2026-11-03", "2026-11-05"))],
                             {**BRIEFS, "2026-11-05": "Something unrelated entirely."})
    assert clean == []


def test_quote_spliced_across_two_briefs_fails():
    spliced = "on track to pass in Texas towns Nvidia told partners to cut"
    assert verify_themes([theme(quote=spliced)], BRIEFS)[0] == []


def test_citing_a_brief_that_does_not_exist_is_removed_and_may_sink_the_theme():
    clean, log = verify_themes([theme(days=("2026-11-03", "2026-11-09"))], BRIEFS)   # 11-09 not read
    assert clean == [] and "at least 2 cited daily briefs" in log[0]["reason"]
    clean, _ = verify_themes([theme(days=("2026-11-03", "2026-11-04", "2026-11-09"))], BRIEFS)
    assert clean[0]["days"] == ["2026-11-03", "2026-11-04"]             # bad citation dropped


def test_a_single_day_is_not_a_theme_and_duplicate_days_do_not_count_twice():
    assert verify_themes([theme(days=("2026-11-03",))], BRIEFS)[0] == []
    assert verify_themes([theme(days=("2026-11-03", "2026-11-03"))], BRIEFS)[0] == []


def test_at_most_three_themes_are_considered():
    clean, _ = verify_themes([theme()] * 5, BRIEFS)
    assert len(clean) == 3


# ---------------------------------------------------------------- rendering

def test_section_cites_daily_briefs_with_links_and_an_evidence_line():
    section = render_section([theme()])
    assert section.startswith("## This week's themes")
    assert "**1. Local backlash**" in section
    assert "*Draws on:* [Nov 3](2026-11-03.md), [Nov 4](2026-11-04.md)" in section
    assert '<sub>**Evidence:** "ballot measures are reportedly on track to pass"</sub>' in section


def test_section_goes_before_the_footer_and_is_replaced_not_duplicated():
    md = brief_md(FRIDAY)
    once = add_section(md, render_section([theme(title="First")]))
    assert once.index("## Noise we ignored") < once.index("## This week's themes") < once.index("\n---\n")
    assert "Articles scanned" in once.split("\n---\n")[-1]
    twice = add_section(once, render_section([theme(title="Second")]))
    assert twice.count("## This week's themes") == 1 and "Second" in twice and "First" not in twice


def test_prompt_has_the_profile_the_rules_and_dated_briefs():
    p = build_system_prompt()
    assert "prepared for Crusoe" in p and "copied EXACTLY" in p and "1.2 GW Abilene" in p
    assert "=== BRIEF 2026-11-03 ===" in weekly.build_prompt(BRIEFS)


# --------------------------------------------------------------------- main

def run_main(monkeypatch, reply=None, *args):
    monkeypatch.setattr("sys.argv", ["weekly", *args])
    monkeypatch.setattr(weekly.anthropic, "Anthropic", lambda: stub_client(reply or {"themes": []}))
    return weekly.main()


def test_friday_adds_verified_themes_to_the_brief(folder, monkeypatch):
    assert date.fromisoformat(FRIDAY).weekday() == 4
    reply = {"themes": [theme(), theme(quote="made up quote that is not anywhere in these briefs")]}
    assert run_main(monkeypatch, reply, FRIDAY) == 0
    text = (folder / f"{FRIDAY}.md").read_text()
    assert text.count("## This week's themes") == 1 and "Local backlash" in text
    saved = json.loads((config.data_dir() / f"{FRIDAY}_weekly.json").read_text())
    assert len(saved["themes"]) == 1 and len(saved["log"]) == 1          # the fake one is logged


def test_not_friday_skips_unless_forced(folder, monkeypatch, capsys):
    thursday = "2026-11-05"
    before = (folder / f"{thursday}.md").read_text()
    run_main(monkeypatch, {"themes": [theme()]}, thursday)
    assert (folder / f"{thursday}.md").read_text() == before and "not a Friday" in capsys.readouterr().out
    run_main(monkeypatch, {"themes": [theme()]}, thursday, "--force")
    assert "This week's themes" in (folder / f"{thursday}.md").read_text()


def test_force_through_the_environment_variable(folder, monkeypatch):
    monkeypatch.setenv("FORCE_WEEKLY", "true")
    run_main(monkeypatch, {"themes": [theme()]}, "2026-11-05")
    assert "This week's themes" in (folder / "2026-11-05.md").read_text()


def test_brief_is_untouched_when_no_theme_survives(folder, monkeypatch, capsys):
    before = (folder / f"{FRIDAY}.md").read_text()
    run_main(monkeypatch, {"themes": [theme(quote="entirely fabricated sentence about nothing real")]}, FRIDAY)
    assert (folder / f"{FRIDAY}.md").read_text() == before
    assert "Nothing survived verification" in capsys.readouterr().out


def test_skips_when_todays_brief_failed_or_the_week_is_too_thin(folder, monkeypatch, capsys):
    (folder / f"{FRIDAY}.md").write_text(NO_BRIEF)
    assert run_main(monkeypatch, {"themes": [theme()]}, FRIDAY) == 0
    assert "No verified brief" in capsys.readouterr().out and "Local backlash" not in (folder / f"{FRIDAY}.md").read_text()
    for p in folder.glob("2026-11-0[345].md"):
        p.unlink()
    (folder / f"{FRIDAY}.md").write_text(brief_md(FRIDAY))
    run_main(monkeypatch, {"themes": [theme()]}, FRIDAY)
    assert "need 2" in capsys.readouterr().out


def test_missing_api_key_is_an_error_not_a_silent_skip(folder, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert run_main(monkeypatch, None, FRIDAY) == 1


# -------------------------------------------------------------- opportunities

OPP_BRIEFS = {"2026-11-04": "Nebius reportedly secured a $3.5 billion credit line ahead of earnings.",
              "2026-11-05": "Oracle reportedly dropped a deal with Tencent, freeing up GPU capacity."}


def opp(**kw):
    base = {"category": "Potential customer", "summary": "Tencent may need a new GPU supplier after Oracle reportedly walked away.",
            "day": "2026-11-05", "quote": "Oracle reportedly dropped a deal with Tencent"}
    return {**base, **kw}


def test_an_opportunity_with_a_cited_brief_and_a_real_quote_survives():
    clean, log = verify_opportunities([opp()], OPP_BRIEFS)
    assert len(clean) == 1 and log == []


def test_every_category_is_accepted_and_others_are_not():
    assert OPPORTUNITY_KINDS == ["Potential customer", "Distressed asset or power contract",
                                 "Partnership", "Pricing signal"]
    assert SCHEMA["properties"]["opportunities"]["items"]["properties"]["category"]["enum"] == OPPORTUNITY_KINDS
    for kind in OPPORTUNITY_KINDS:
        assert verify_opportunities([opp(category=kind)], OPP_BRIEFS)[0]
    clean, log = verify_opportunities([opp(category="Acquisition")], OPP_BRIEFS)
    assert clean == [] and "invalid category" in log[0]["reason"]


def test_an_opportunity_citing_a_brief_that_was_not_read_is_removed():
    clean, log = verify_opportunities([opp(day="2026-11-09")], OPP_BRIEFS)
    assert clean == [] and log[0]["reason"] == "cites a daily brief that was not read"


def test_a_fabricated_quote_removes_the_opportunity_and_is_logged():
    clean, log = verify_opportunities([opp(quote="Tencent signed an exclusive GPU contract with us")], OPP_BRIEFS)
    assert clean == [] and log[0]["reason"] == "quote not found in the source text"
    assert log[0]["quote"].startswith("Tencent signed") and log[0]["kind"] == "opportunity"


def test_the_quote_must_come_from_the_brief_it_cites_not_another_day():
    clean, _ = verify_opportunities([opp(day="2026-11-04")], OPP_BRIEFS)       # quote is from 11-05's brief
    assert clean == []


def test_a_figure_the_cited_brief_does_not_contain_removes_the_opportunity():
    invented = opp(summary="A $5 billion refinancing could be available to Crusoe.")
    clean, log = verify_opportunities([invented], OPP_BRIEFS)
    assert clean == [] and log[0]["reason"] == "figure not in the cited brief: 5"


def test_a_figure_from_the_cited_brief_is_fine_but_not_one_from_another_days_brief():
    good = opp(day="2026-11-04", quote="Nebius reportedly secured a $3.5 billion credit line",
               category="Pricing signal", summary="Nebius reportedly raised $3.5 billion, a financing-cost signal.")
    assert verify_opportunities([good], OPP_BRIEFS)[0]
    borrowed = opp(summary="Tencent may need capacity worth $3.5 billion.")       # 3.5 is in the OTHER brief
    assert verify_opportunities([borrowed], OPP_BRIEFS)[0] == []


def test_missing_summary_and_the_cap_of_five():
    assert verify_opportunities([opp(summary="  ")], OPP_BRIEFS)[0] == []
    assert len(verify_opportunities([opp()] * 8, OPP_BRIEFS)[0]) == 5


def test_opportunities_render_with_a_cited_brief_link_and_an_evidence_line():
    section = render_opportunities([opp()])
    assert section.startswith("## Opportunities")
    assert ("- **Potential customer:** Tencent may need a new GPU supplier after Oracle reportedly walked away. "
            "— [Nov 5](2026-11-05.md)") in section
    assert '<sub>**Evidence:** "Oracle reportedly dropped a deal with Tencent"</sub>' in section


def test_both_weekly_sections_sit_before_the_footer_and_are_replaced_together():
    both = render_section([theme()]) + "\n" + render_opportunities([opp(summary="First version.")])
    once = add_section(brief_md(FRIDAY), both)
    assert once.index("## This week's themes") < once.index("## Opportunities") < once.index("\n---\n")
    assert "Articles scanned" in once.split("\n---\n")[-1]
    twice = add_section(once, render_opportunities([opp(summary="Second version.")]))
    assert twice.count("## Opportunities") == 1 and "Second version." in twice and "First version." not in twice
    assert "## This week's themes" not in twice                                  # replaced as a pair, not left stale


def test_prompt_lists_the_categories_and_forbids_invented_figures():
    p = build_system_prompt()
    assert all(kind in p for kind in OPPORTUNITY_KINDS)
    assert "never estimate" in p and "ONLY if it appears in that brief" in p.replace("\n", " ").replace("  ", " ")


def test_friday_adds_themes_and_opportunities_and_logs_the_rejects(folder, monkeypatch):
    reply = {"themes": [theme()],
             "opportunities": [opp(day="2026-11-05", quote="Anti-data center ballot measures are reportedly on track to pass",
                                   summary="Local backlash could open stranded sites for sale."),
                               opp(quote="a quote nobody ever wrote down anywhere")]}
    assert run_main(monkeypatch, reply, FRIDAY) == 0
    text = (folder / f"{FRIDAY}.md").read_text()
    assert text.count("## This week's themes") == 1 and text.count("## Opportunities") == 1
    assert "Local backlash could open stranded sites for sale." in text
    saved = json.loads((config.data_dir() / f"{FRIDAY}_weekly.json").read_text())
    assert len(saved["opportunities"]) == 1 and saved["log"][0]["kind"] == "opportunity"


def test_opportunities_alone_are_published_when_no_theme_survives(folder, monkeypatch):
    reply = {"themes": [theme(quote="a made up sentence that is not in any brief at all")],
             "opportunities": [opp(day="2026-11-05", quote="Anti-data center ballot measures are reportedly on track to pass",
                                   summary="Backlash could free up sites.")]}
    run_main(monkeypatch, reply, FRIDAY)
    text = (folder / f"{FRIDAY}.md").read_text()
    assert "## Opportunities" in text and "## This week's themes" not in text
