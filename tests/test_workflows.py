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
    assert "github.event_name != 'push'" in commit["if"]
    assert "git add briefs/" in commit["run"]


def test_check_feeds_runs_on_push_and_manually():
    t = triggers(load("check-feeds.yml"))
    assert "workflow_dispatch" in t and "push" in t
