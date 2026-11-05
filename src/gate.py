"""Decide whether this workflow run should build a brief.

GitHub's schedule can fire late (sometimes by hours), so the gate does not
require the run to start in the 6 a.m. hour. A scheduled run proceeds when BOTH:

  - it is between 6:00 and 11:59 a.m. in Denver, and
  - briefs/<profile>/<today>.md does not already exist (scheduled runs always
    check out main, so this is "does not already exist on main").

The second condition is what makes the two UTC crons safe: whichever fires
first builds the brief and commits it; the later one finds the file and stops.
Manual and push runs always proceed, because a person asked for them.

Writes `go=true` or `go=false` to $GITHUB_OUTPUT for the later steps, and
prints the reason, so the run page says why a trigger was skipped.
"""
import os
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .config import BRIEF_TIMEZONE, ROOT, profile_name, today

WINDOW_START_HOUR = 6      # 6:00 a.m. Denver, inclusive
WINDOW_END_HOUR = 12       # 12:00 p.m. Denver, exclusive: the window closes at 11:59


def decide(event_name: str, now: datetime, brief_exists: bool) -> tuple[bool, str]:
    """Return (go, reason). `now` must be timezone-aware."""
    if event_name != "schedule":
        return True, f"a {event_name} run always proceeds"
    local = now.astimezone(ZoneInfo(BRIEF_TIMEZONE))
    if not WINDOW_START_HOUR <= local.hour < WINDOW_END_HOUR:
        return False, (f"scheduled run at {local:%H:%M} Denver is outside "
                       f"{WINDOW_START_HOUR:02d}:00-{WINDOW_END_HOUR - 1:02d}:59: skipping")
    if brief_exists:
        return False, "today's brief already exists on main: skipping (an earlier trigger built it)"
    return True, f"scheduled run at {local:%H:%M} Denver, no brief yet today: proceeding"


def main(now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    brief = ROOT / "briefs" / profile_name() / f"{today(now)}.md"
    go, reason = decide(os.environ.get("GITHUB_EVENT_NAME", "workflow_dispatch"), now, brief.exists())
    print(f"Gate: {reason}")
    if path := os.environ.get("GITHUB_OUTPUT"):
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"go={'true' if go else 'false'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
