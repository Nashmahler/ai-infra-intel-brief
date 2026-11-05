"""Briefs and data folders are named by the America/Denver date, not the UTC date."""
from datetime import datetime, timezone
from pathlib import Path

import pytest

import src.config as config
import src.fetch as fetch
import src.fulltext as fulltext
import src.rank as rank
import src.verify as verify
import src.weekly as weekly
import src.write as write
from src.config import today

SRC = Path(__file__).resolve().parent.parent / "src"


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


def test_a_5pm_mountain_run_on_nov_4_is_nov_4_not_nov_5():
    """The reported bug: 5 p.m. MST Nov 4 is 00:00 UTC Nov 5."""
    assert utc(2026, 11, 5, 0, 18).strftime("%Y-%m-%d") == "2026-11-05"      # what UTC says
    assert today(utc(2026, 11, 5, 0, 18)) == "2026-11-04"                    # what we now use


def test_the_day_rolls_over_at_midnight_mountain_in_winter_mst():
    assert today(utc(2026, 11, 5, 6, 59)) == "2026-11-04"      # 23:59 MST
    assert today(utc(2026, 11, 5, 7, 0)) == "2026-11-05"       # 00:00 MST


def test_the_day_rolls_over_at_midnight_mountain_in_summer_mdt():
    assert today(utc(2026, 7, 2, 5, 59)) == "2026-07-01"       # 23:59 MDT
    assert today(utc(2026, 7, 2, 6, 0)) == "2026-07-02"        # 00:00 MDT


def test_the_6am_mountain_scheduled_run_lands_on_the_same_calendar_day_all_year():
    assert today(utc(2026, 11, 5, 13, 0)) == "2026-11-05"      # 6am MST
    assert today(utc(2026, 7, 2, 12, 0)) == "2026-07-02"       # 6am MDT


def test_daylight_saving_changeover_days_are_handled():
    assert today(utc(2026, 3, 8, 8, 59)) == "2026-03-08"       # 01:59 MST, just before the jump
    assert today(utc(2026, 3, 8, 9, 0)) == "2026-03-08"        # 03:00 MDT, just after
    assert today(utc(2026, 11, 1, 7, 30)) == "2026-11-01"      # 01:30 MST, the repeated hour


def test_naive_input_defaults_to_now_and_returns_a_date_string():
    assert len(today()) == 10 and today()[4] == "-" and today()[7] == "-"


def test_fetch_names_its_file_by_the_denver_date(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.delenv("TARGET_PROFILE", raising=False)
    monkeypatch.setattr(fetch, "all_feeds", lambda: [])
    monkeypatch.setattr(config, "watchlist_terms", lambda: [])        # no watchlist.yaml in the temp folder
    fetch.main(now=utc(2026, 11, 5, 0, 18))                    # 5:18 p.m. Mountain on Nov 4
    assert (tmp_path / "data" / "crusoe" / "2026-11-04_raw.json").exists()
    assert not (tmp_path / "data" / "crusoe" / "2026-11-05_raw.json").exists()


@pytest.fixture
def future_day(tmp_path, monkeypatch):
    """Point every step's 'today' at one date and the repo at an empty temp folder."""
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.delenv("TARGET_PROFILE", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setattr("sys.argv", ["step"])
    for module in (fulltext, rank, verify, weekly, write):
        monkeypatch.setattr(module, "today", lambda: "2099-01-01")
    return tmp_path


def test_every_step_picks_its_default_day_through_the_same_helper(future_day, capsys):
    assert verify.main() == 0                                  # writes the fail-closed note
    assert (future_day / "briefs" / "crusoe" / "2099-01-01.md").exists()
    fulltext.main()
    assert "No scores file" in capsys.readouterr().out
    weekly.main()
    assert "2099-01-01 is not a Friday" in capsys.readouterr().out
    for step in (rank, write):
        with pytest.raises(FileNotFoundError, match="2099-01-01_raw.json"):
            step.main()


def test_no_step_computes_the_day_from_utc_itself():
    """Only config.today() may turn a clock into a file-name date."""
    for path in SRC.glob("*.py"):
        if path.name == "config.py":
            continue
        text = path.read_text()
        assert 'strftime("%Y-%m-%d")' not in text and ":%Y-%m-%d}" not in text, path.name


def test_the_workflow_names_its_commit_by_the_denver_date():
    text = (Path(__file__).resolve().parent.parent / ".github/workflows/daily-brief.yml").read_text()
    assert "TZ=America/Denver date +%F" in text and "date -u" not in text
