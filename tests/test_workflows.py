"""Workflow files must be valid YAML with the triggers and secrets we rely on.
(A broken workflow fails silently at GitHub, so catch it here.)"""
import glob
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def load(name):
    return yaml.safe_load((ROOT / ".github" / "workflows" / name).read_text())


def triggers(wf):
    return wf.get("on") or wf.get(True)    # YAML 1.1 reads a bare `on` as True


def test_all_workflows_parse():
    files = glob.glob(str(ROOT / ".github" / "workflows" / "*.yml"))
    assert files
    for f in files:
        assert yaml.safe_load(open(f))["jobs"]


def test_daily_brief_schedule_manual_run_and_secret():
    wf, text = load("daily-brief.yml"), (ROOT / ".github/workflows/daily-brief.yml").read_text()
    t = triggers(wf)
    assert {c["cron"] for c in t["schedule"]} == {"0 12 * * *", "0 13 * * *"}  # 6am MDT / MST
    assert "workflow_dispatch" in t
    assert "secrets.ANTHROPIC_API_KEY" in text
    assert "sk-ant" not in text                                # no key in code
    assert wf["permissions"]["contents"] == "write"            # needed to commit briefs/


def test_daily_brief_commits_briefs_but_not_on_push_test_runs():
    steps = load("daily-brief.yml")["jobs"]["brief"]["steps"]
    commit = next(s for s in steps if "Commit" in s.get("name", ""))
    assert "github.event_name == 'schedule'" in commit["if"]       # the daily run always commits
    assert "inputs.commit == true" in commit["if"]                 # a manual run can opt out
    assert "push" not in commit["if"]                              # pushes (test runs) never commit
    assert "git add briefs/ README.md" in commit["run"]       # the brief, its index, and the latest link
    assert "TARGET_PROFILE" in commit["run"]                  # commit message names the profile


def test_check_feeds_runs_on_push_and_manually():
    t = triggers(load("check-feeds.yml"))
    assert "workflow_dispatch" in t and "push" in t


def test_workflows_pass_the_target_profile_setting_through():
    for name in ("daily-brief.yml", "check-feeds.yml"):
        text = (ROOT / ".github" / "workflows" / name).read_text()
        assert "TARGET_PROFILE: ${{ vars.TARGET_PROFILE }}" in text, name


def test_pipeline_steps_run_in_the_intended_order():
    steps = [s.get("run", "") for s in load("daily-brief.yml")["jobs"]["brief"]["steps"]]
    order = [next(i for i, r in enumerate(steps) if f"src.{m}" in r)
             for m in ("fetch", "rank", "decode", "fulltext", "write", "verify", "weekly", "index")]
    assert order == sorted(order)
    commit = next(i for i, r in enumerate(steps) if "git commit" in r)
    assert commit > order[-1]                                   # commit comes after everything it commits


def test_weekly_step_cannot_block_the_daily_brief_and_has_a_manual_flag():
    wf = load("daily-brief.yml")
    steps = wf["jobs"]["brief"]["steps"]
    weekly = next(s for s in steps if "src.weekly" in s.get("run", ""))
    index = next(s for s in steps if "src.index" in s.get("run", ""))
    assert weekly["continue-on-error"] is True and index["continue-on-error"] is True
    assert weekly["env"]["FORCE_WEEKLY"] == "${{ inputs.weekly }}"
    assert triggers(wf)["workflow_dispatch"]["inputs"]["weekly"]["type"] == "boolean"


def test_manual_run_has_a_commit_switch_that_defaults_to_on_and_a_brief_printing_step():
    wf = load("daily-brief.yml")
    inputs = triggers(wf)["workflow_dispatch"]["inputs"]
    assert inputs["commit"]["type"] == "boolean" and inputs["commit"]["default"] is True
    steps = wf["jobs"]["brief"]["steps"]
    show = next(s for s in steps if "run summary" in s.get("name", ""))
    assert show["continue-on-error"] is True and "GITHUB_STEP_SUMMARY" in show["run"]
    names = [s.get("name", "") for s in steps]
    assert names.index(show["name"]) < next(i for i, n in enumerate(names) if n.startswith("Commit"))


def test_google_decoding_cannot_block_the_brief():
    steps = load("daily-brief.yml")["jobs"]["brief"]["steps"]
    decode = next(s for s in steps if "src.decode" in s.get("run", ""))
    assert decode["continue-on-error"] is True and "top 60" in decode["name"]


def test_the_gate_is_a_python_step_placed_after_checkout_and_install_and_gating_everything_after_it():
    steps = load("daily-brief.yml")["jobs"]["brief"]["steps"]
    names = [s.get("name") or s.get("uses", "") for s in steps]
    gate = next(i for i, s in enumerate(steps) if s.get("id") == "gate")
    assert steps[gate]["run"] == "python -m src.gate"
    assert [n for n in names[:gate]] == ["actions/checkout@v4", "actions/setup-python@v5", "Install"]
    for before in steps[:gate]:
        assert "if" not in before                                   # the gate needs these to have run
    for after in steps[gate + 1:]:
        assert "steps.gate.outputs.go == 'true'" in after["if"], after.get("name")


def test_the_old_shell_gate_that_only_allowed_the_6am_hour_is_gone_and_both_crons_remain():
    text = (ROOT / ".github/workflows/daily-brief.yml").read_text()
    assert "date +%H" not in text and '!= "06"' not in text
    assert {c["cron"] for c in triggers(load("daily-brief.yml"))["schedule"]} == {"0 12 * * *", "0 13 * * *"}
    assert "6:00 to 11:59 a.m." in text
