"""Index and 'Latest brief' link tests, in temp folders."""
import pytest

import src.config as config
import src.index as index
from src.index import latest_line, list_briefs, render_index, update_readme

OK = "# T\n\n## Top 3 developments\n\n---\n*footer*\n"
WEEKLY = OK.replace("---", "## This week's themes\n\nx\n\n---")
FAILED = "# T\n\n**No verified brief today.**\n"
README = "# AI Infrastructure Intelligence Brief\n\nIntro paragraph.\n\n## Section\n"


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setattr(index, "ROOT", tmp_path)
    monkeypatch.delenv("TARGET_PROFILE", raising=False)
    (tmp_path / "README.md").write_text(README)
    folder = config.briefs_dir()
    for day, text in {"2026-11-04": OK, "2026-11-05": FAILED, "2026-11-06": WEEKLY}.items():
        (folder / f"{day}.md").write_text(text)
    return tmp_path


def test_list_briefs_newest_first_ignoring_the_index_itself(repo):
    folder = config.briefs_dir()
    (folder / "README.md").write_text("# index")
    briefs = list_briefs(folder)
    assert [b["day"] for b in briefs] == ["2026-11-06", "2026-11-05", "2026-11-04"]
    assert [b["verified"] for b in briefs] == [True, False, True]
    assert [b["weekly"] for b in briefs] == [True, False, False]


def test_index_lists_every_brief_newest_first_and_marks_failed_days(repo):
    text = render_index("Crusoe", list_briefs(config.briefs_dir()))
    lines = [l for l in text.splitlines() if l.startswith("- ")]
    assert lines == ["- [November 6, 2026](2026-11-06.md) · weekly themes",
                     "- [November 5, 2026](2026-11-05.md) — *no verified brief*",
                     "- [November 4, 2026](2026-11-04.md)"]
    assert text.startswith("# Briefs prepared for Crusoe") and "3 briefs" in text


def test_latest_line_points_at_the_newest_verified_brief(repo):
    briefs = list_briefs(config.briefs_dir())
    line = latest_line("crusoe", "Crusoe", briefs)
    assert "[November 6, 2026](briefs/crusoe/2026-11-06.md)" in line
    assert "[all briefs](briefs/crusoe/README.md)" in line and "no verified brief" not in line


def test_latest_line_mentions_a_newer_failed_day():
    briefs = [{"day": "2026-11-07", "verified": False, "weekly": False},
              {"day": "2026-11-06", "verified": True, "weekly": False}]
    line = latest_line("crusoe", "Crusoe", briefs)
    assert "2026-11-06.md" in line and "(no verified brief on November 7, 2026)" in line


def test_no_verified_brief_at_all_means_no_latest_line():
    assert latest_line("crusoe", "Crusoe", [{"day": "2026-11-07", "verified": False, "weekly": False}]) is None


def test_update_readme_puts_the_link_right_under_the_title_and_keeps_the_rest():
    out = update_readme(README, "crusoe", "**Latest brief — Crusoe:** x <!--profile:crusoe-->")
    assert out.startswith("# AI Infrastructure Intelligence Brief\n\n<!-- latest-brief:start -->\n**Latest")
    assert "<!-- latest-brief:end -->\n\nIntro paragraph.\n\n## Section\n" in out


def test_update_readme_replaces_this_profiles_line_and_keeps_others():
    first = update_readme(README, "crusoe", "OLD crusoe <!--profile:crusoe-->")
    second = update_readme(first, "acme", "acme line <!--profile:acme-->")
    third = update_readme(second, "crusoe", "NEW crusoe <!--profile:crusoe-->")
    assert "OLD" not in third and "NEW crusoe" in third and "acme line" in third
    assert third.count("<!-- latest-brief:start -->") == 1
    assert third.index("acme line") < third.index("NEW crusoe")        # sorted by profile name


def test_update_readme_is_idempotent():
    line = "same <!--profile:crusoe-->"
    once = update_readme(README, "crusoe", line)
    assert update_readme(once, "crusoe", line) == once


def test_main_writes_the_index_and_updates_the_readme(repo, monkeypatch):
    assert index.main() == 0
    assert (config.briefs_dir() / "README.md").read_text().startswith("# Briefs prepared for Crusoe")
    readme = (repo / "README.md").read_text()
    assert "[November 6, 2026](briefs/crusoe/2026-11-06.md)" in readme
    assert readme.startswith("# AI Infrastructure Intelligence Brief\n\n<!-- latest-brief:start -->")
    before = (repo / "README.md").read_text()
    index.main()                                                        # a second run changes nothing
    assert (repo / "README.md").read_text() == before


def test_main_with_no_briefs_changes_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setattr(index, "ROOT", tmp_path)
    (tmp_path / "README.md").write_text(README)
    assert index.main() == 0 and (tmp_path / "README.md").read_text() == README
