"""Step 1 helper: check that every configured feed URL returns items.

Usage:  python -m src.check_feeds
Exit code is 1 if any feed failed, so this can also run in CI.
"""
import sys

import feedparser

from .config import USER_AGENT, all_feeds


def check(feed: dict) -> tuple[bool | None, str]:
    """Return (ok, detail). ok is True, False, or None (could not be tested)."""
    parsed = feedparser.parse(feed["url"], agent=USER_AGENT)
    status = parsed.get("status", "no response")
    n = len(parsed.entries)
    if n == 0:
        err = str(parsed.get("bozo_exception", ""))
        # A proxy/firewall refusal says nothing about the feed itself.
        if "Tunnel connection failed" in err:
            return None, "BLOCKED by network policy (feed not tested)"
        return False, f"HTTP {status}, 0 items {err}"
    return True, f"HTTP {status}, {n} items"


def main() -> int:
    failed = blocked = 0
    for feed in all_feeds():
        ok, detail = check(feed)
        failed += ok is False
        blocked += ok is None
        label = {True: "OK   ", False: "FAIL ", None: "SKIP "}[ok]
        print(f"{label}{feed['name']:<40} {detail}")
    print(f"\n{failed} failed, {blocked} untestable (network blocked)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
