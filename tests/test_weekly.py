"""Weekly synthesis tests: stub client, temp folders, no network."""
import json
from datetime import date
from types import SimpleNamespace

import pytest

import src.config as config
import src.weekly as weekly
from src.weekly import (add_section, build_system_prompt, collect_briefs, plain_text,
                        render_section, verify_themes)

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
    assert "No theme survived verification" in capsys.readouterr().out


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
