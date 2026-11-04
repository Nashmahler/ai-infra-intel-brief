"""Step 1 helper: check that every configured feed URL returns items.

Usage:  python -m src.check_feeds

One bad feed never fails the check. The exit code is 1 only if fewer than
half of the feeds work, so CI goes red only when something is badly wrong.
"""
import os
import sys

import feedparser

from .config import USER_AGENT, all_feeds


def check(feed: dict) -> tuple[bool | None, str]:
    """Return (ok, detail). ok is True, False, or None (could not be tested)."""
    parsed = feedparser.parse(feed["url"], agent=USER_AGENT)
    status = parsed.get("status", "no response")
    if not parsed.entries:
        err = str(parsed.get("bozo_exception", ""))
        # A proxy/firewall refusal says nothing about the feed itself.
        if "Tunnel connection failed" in err:
            return None, "BLOCKED by network policy (feed not tested)"
        return False, f"HTTP {status}, 0 items {err}"
    return True, f"HTTP {status}, {len(parsed.entries)} items"


def main() -> int:
    feeds = all_feeds()
    lines, working, bad = [], 0, []
    for feed in feeds:
        ok, detail = check(feed)
        working += ok is True
        if ok is not True:
            bad.append(f"{feed['name']}: {detail}")
        label = {True: "OK   ", False: "FAIL ", None: "SKIP "}[ok]
        lines.append(f"{label}{feed['name']:<40} {detail}")

    passed = working * 2 >= len(feeds)  # at least half must work
    summary = [f"{working} of {len(feeds)} feeds working "
               f"({'PASS' if passed else 'FAIL: fewer than half work'})"]
    if bad:
        summary.append("Not working:")
        summary += [f"  - {b}" for b in bad]

    print("\n".join(lines) + "\n\n" + "\n".join(summary))
    # On GitHub, also show the summary on the run page (easy to read on a phone).
    if path := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(path, "a", encoding="utf-8") as f:
            f.write("### Feed check\n```\n" + "\n".join(summary) + "\n```\n")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
