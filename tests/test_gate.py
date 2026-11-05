"""The scheduled-run gate: 6:00-11:59 a.m. Denver, and only if today's brief isn't on main yet."""
from datetime import datetime, timezone

import pytest

import src.config as config
import src.gate as gate
from src.gate import decide

# Nov 5, 2026 is standard time (MST, UTC-7); Jul 2, 2026 is daylight time (MDT, UTC-6).


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


def go(now, exists=False, event="schedule"):
    return decide(event, now, exists)[0]


# ----------------------------------------------------------------- the window

def test_winter_window_runs_6_00_to_11_59_mst_and_nothing_outside_it():
    assert not go(utc(2026, 11, 5, 12, 59))          # 05:59 MST
    assert go(utc(2026, 11, 5, 13, 0))               # 06:00 MST  <- the 13:00 UTC cron on time
    assert go(utc(2026, 11, 5, 18, 59))              # 11:59 MST
    assert not go(utc(2026, 11, 5, 19, 0))           # 12:00 MST
    assert not go(utc(2026, 11, 5, 3, 0))            # 20:00 MST the evening before


def test_summer_window_runs_6_00_to_11_59_mdt_and_nothing_outside_it():
    assert not go(utc(2026, 7, 2, 11, 59))           # 05:59 MDT
    assert go(utc(2026, 7, 2, 12, 0))                # 06:00 MDT  <- the 12:00 UTC cron on time
    assert go(utc(2026, 7, 2, 17, 59))               # 11:59 MDT
    assert not go(utc(2026, 7, 2, 18, 0))            # 12:00 MDT


def test_a_late_start_still_goes_as_long_as_it_is_inside_the_window():
    """The reason for this change: GitHub can start a scheduled run hours late."""
    assert go(utc(2026, 11, 5, 16, 0))               # the 13:00 UTC cron started 3 hours late (09:00 MST)
    assert go(utc(2026, 11, 5, 18, 30))              # 5.5 hours late (11:30 MST)
    assert not go(utc(2026, 11, 5, 19, 5))           # too late: the window has closed
    assert go(utc(2026, 7, 2, 16, 45))               # a summer 12:00 UTC cron 4h45m late (10:45 MDT)


def test_the_old_rule_would_have_skipped_these_late_starts():
    """Documents the behaviour being replaced (only the 06 o'clock hour passed)."""
    old = lambda now: now.astimezone(gate.ZoneInfo(config.BRIEF_TIMEZONE)).hour == 6
    for late in (utc(2026, 11, 5, 16, 0), utc(2026, 11, 5, 18, 30), utc(2026, 7, 2, 16, 45)):
        assert not old(late) and go(late)


# -------------------------------------------------- only if no brief exists yet

def test_an_existing_brief_stops_a_scheduled_run_even_inside_the_window():
    now = utc(2026, 11, 5, 14, 0)                    # 07:00 MST
    go_, reason = decide("schedule", now, brief_exists=True)
    assert not go_ and "already exists on main" in reason
    assert decide("schedule", now, brief_exists=False)[0]


def test_the_reason_always_says_why():
    assert "outside 06:00-11:59" in decide("schedule", utc(2026, 11, 5, 3, 0), False)[1]
    assert "05:00 Denver" in decide("schedule", utc(2026, 11, 5, 12, 0), False)[1]
    assert "proceeding" in decide("schedule", utc(2026, 11, 5, 13, 0), False)[1]


def test_exactly_one_of_the_two_crons_builds_the_brief_in_every_season():
    """Both UTC crons fire daily; whichever builds first writes the file, the other stops."""
    for crons in ([utc(2026, 11, 5, 12), utc(2026, 11, 5, 13)],       # winter: 05:00 MST, 06:00 MST
                  [utc(2026, 7, 2, 12), utc(2026, 7, 2, 13)],         # summer: 06:00 MDT, 07:00 MDT
                  [utc(2026, 3, 8, 12), utc(2026, 3, 8, 13)],         # spring-forward day
                  [utc(2026, 11, 1, 12), utc(2026, 11, 1, 13)]):      # fall-back day
        exists, built = False, 0
        for now in crons:
            if go(now, exists):
                built += 1
                exists = True                       # the run commits today's brief to main
        assert built == 1, crons


def test_if_the_first_cron_is_missed_entirely_the_second_one_still_builds_the_brief():
    assert go(utc(2026, 7, 2, 13), exists=False)    # summer, the 12:00 UTC run never started
    assert go(utc(2026, 11, 5, 13), exists=False)   # winter, the 13:00 UTC cron on time (12:00 UTC was before the window)


# ----------------------------------------------------- manual and push always go

@pytest.mark.parametrize("event", ["workflow_dispatch", "push", "anything_else"])
def test_only_scheduled_runs_are_gated(event):
    for now in (utc(2026, 11, 5, 3, 0), utc(2026, 11, 5, 20, 0)):             # outside the window
        assert go(now, exists=True, event=event)                              # even with a brief already there


# ------------------------------------------------------------ the real entry point

@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.delenv("TARGET_PROFILE", raising=False)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
    out = tmp_path / "github_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    return tmp_path, out


def test_main_writes_go_true_when_in_the_window_and_no_brief(repo, capsys):
    tmp, out = repo
    assert gate.main(utc(2026, 11, 5, 14, 0)) == 0                     # 07:00 MST
    assert out.read_text() == "go=true\n" and "proceeding" in capsys.readouterr().out


def test_main_writes_go_false_when_todays_brief_exists_on_main(repo, capsys):
    tmp, out = repo
    (tmp / "briefs" / "crusoe").mkdir(parents=True)
    (tmp / "briefs" / "crusoe" / "2026-11-05.md").write_text("# a brief")
    gate.main(utc(2026, 11, 5, 14, 0))
    assert out.read_text() == "go=false\n" and "already exists on main" in capsys.readouterr().out


def test_main_looks_for_the_denver_date_not_the_utc_date(repo):
    """14:00 UTC on Nov 6 is 07:00 on Nov 6 in Denver; a Nov 5 file must not block it."""
    tmp, out = repo
    (tmp / "briefs" / "crusoe").mkdir(parents=True)
    (tmp / "briefs" / "crusoe" / "2026-11-05.md").write_text("yesterday")
    gate.main(utc(2026, 11, 6, 14, 0))
    assert out.read_text() == "go=true\n"
    (tmp / "briefs" / "crusoe" / "2026-11-06.md").write_text("today")
    out.write_text("")
    gate.main(utc(2026, 11, 6, 14, 0))
    assert out.read_text() == "go=false\n"


def test_main_only_counts_the_selected_profiles_brief(repo, monkeypatch):
    tmp, out = repo
    (tmp / "briefs" / "crusoe").mkdir(parents=True)
    (tmp / "briefs" / "crusoe" / "2026-11-05.md").write_text("crusoe's brief")
    monkeypatch.setenv("TARGET_PROFILE", "acme")
    gate.main(utc(2026, 11, 5, 14, 0))
    assert out.read_text() == "go=true\n"                              # acme has no brief yet


def test_main_does_not_create_folders_and_survives_a_missing_output_file(repo, monkeypatch, capsys):
    tmp, out = repo
    monkeypatch.delenv("GITHUB_OUTPUT")
    assert gate.main(utc(2026, 11, 5, 14, 0)) == 0
    assert not (tmp / "briefs").exists() and "Gate:" in capsys.readouterr().out


def test_main_defaults_to_proceeding_when_run_by_hand(repo, monkeypatch):
    tmp, out = repo
    monkeypatch.delenv("GITHUB_EVENT_NAME")
    gate.main(utc(2026, 11, 5, 3, 0))                                  # the middle of the night
    assert out.read_text() == "go=true\n"
