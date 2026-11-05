"""Decode Google News redirect links for the top-ranked stories.

Runs after ranking, so we only spend Google requests on stories that can reach
the brief (the top DECODE_TOP_N ranked items), not on all ~200 collected items.

Reads and updates  data/<profile>/YYYY-MM-DD_raw.json and ..._scores.json
Writes             data/<profile>/YYYY-MM-DD_decode.json  (what happened and why)

For each decoded link the publisher URL becomes the item's `link` (used for
full-text fetching and display) and the Google link is kept as `original_link`,
in BOTH files, so both URLs stay in the collected set that verification checks.
A link that cannot be decoded keeps its original Google link.

The decoder is an unofficial third-party package that talks to Google, so this
step is polite (one request per interval, a time budget), gives up early if
Google starts refusing, and says so loudly in the log.
"""
import json
import sys
import time

from .config import data_dir, today
from .fetch import is_google_news, normalize_link

DECODE_TOP_N = 60               # only the best-ranked items are decoded
DECODE_INTERVAL = 1.0           # seconds between requests to Google (a short rate limit)
DECODE_BUDGET = 300.0           # stop after this many seconds in total
MAX_CONSECUTIVE_FAILURES = 5    # this many failures in a row = Google is refusing us; stop


class DecodeError(Exception):
    """A link could not be decoded; the message says why (it goes in the log)."""


def decode_with_package(url: str) -> str:
    """Ask the googlenewsdecoder package for a link's publisher URL.

    Makes a web request to Google. Returns the publisher URL, or raises
    DecodeError with the reason, so the caller can keep the original link.
    """
    try:
        from googlenewsdecoder import gnewsdecoder
    except ImportError:
        raise DecodeError("googlenewsdecoder is not installed") from None
    try:
        result = gnewsdecoder(url, timeout=10)       # we pace calls ourselves: no `interval`
    except Exception as err:
        raise DecodeError(f"decoder raised {type(err).__name__}: {str(err)[:80]}") from None
    if not isinstance(result, dict):
        raise DecodeError("unexpected result from the decoder")
    if not result.get("success", result.get("status")):   # newer versions say success, older status
        raise DecodeError(f"Google refused: {str(result.get('message', 'no message'))[:80]}")
    decoded = result.get("decoded_url")
    if not (isinstance(decoded, str) and decoded.startswith(("http://", "https://"))) \
            or is_google_news(decoded):
        raise DecodeError("decoded URL is not a publisher link")
    return decoded


def resolve_google_links(items: list[dict], decoder=None, interval: float = DECODE_INTERVAL,
                         budget: float = DECODE_BUDGET, sleep=time.sleep, clock=time.monotonic,
                         log=print) -> tuple[list[dict], dict]:
    """Replace Google News links with publisher URLs, in the order given (best first).

    Politeness and safety: `interval` seconds between requests; at most `budget`
    seconds in total (judged by when the next request would START); and after
    MAX_CONSECUTIVE_FAILURES failures in a row we stop asking Google.

    Logging: the first failure is reported at once ("started failing after N
    successes", or "failed on the first request"), as is the early stop, using
    GitHub's ::warning:: format so they show up on the run page.
    Returns (items in their original order, stats).
    """
    decoder = decoder or decode_with_package
    pending = [i for i, item in enumerate(items) if is_google_news(item["link"])]
    stats = {"google_links": len(pending), "decoded": 0, "failed": 0, "skipped": 0,
             "stopped_because": None, "reasons": {}}
    reasons, last_reason, out = {}, None, list(items)
    started, last_call, streak = clock(), None, 0
    for n, i in enumerate(pending):
        wait = 0.0 if last_call is None else max(0.0, interval - (clock() - last_call))
        if (clock() - started) + wait > budget:
            stats["stopped_because"] = "time budget used"
        elif streak >= MAX_CONSECUTIVE_FAILURES:
            stats["stopped_because"] = f"{streak} failures in a row"
        if stats["stopped_because"]:
            stats["skipped"] = len(pending) - n
            log(f"::warning::Google News decoding stopped ({stats['stopped_because']}); "
                f"{stats['skipped']} link(s) stay as Google links. "
                f"Last reason: {last_reason or 'n/a'}")
            break
        if wait:
            sleep(wait)
        last_call = clock()
        try:
            decoded = decoder(items[i]["link"])
            if not decoded:
                raise DecodeError("no result")
        except Exception as err:
            reason = str(err) or type(err).__name__
            if stats["failed"] == 0:                      # the moment it starts failing
                when = ("on the first request" if stats["decoded"] == 0
                        else f"after {stats['decoded']} successful link(s)")
                log(f"::warning::Google News decoding started failing {when}: {reason}")
            reasons[reason] = reasons.get(reason, 0) + 1
            last_reason = reason
            stats["failed"] += 1
            streak += 1
            continue
        out[i] = {**items[i], "link": decoded, "original_link": items[i]["link"]}
        stats["decoded"] += 1
        streak = 0
    stats["reasons"] = reasons
    return out, stats


def decode_ranked(raw: dict, scores: dict, decoder=None, **kw) -> tuple[dict, dict, dict]:
    """Decode the top DECODE_TOP_N ranked items and update raw and scores together.

    Returns (raw, scores, stats). Items ranked below the cutoff are untouched.
    If a decoded URL matches a better-ranked item's URL the two are one article,
    so the lower-ranked copy is dropped from the ranking (raw keeps every item).
    """
    ranked = scores["items"]                               # best first
    top, rest = ranked[:DECODE_TOP_N], ranked[DECODE_TOP_N:]
    resolved, stats = resolve_google_links(top, decoder, **kw)
    swaps = {old["link"]: new["link"] for old, new in zip(top, resolved) if new["link"] != old["link"]}

    new_raw = [{**r, "link": swaps[r["link"]], "original_link": r["link"]}
               if r["link"] in swaps else r for r in raw["items"]]
    seen, unique = set(), []
    for item in resolved + rest:
        key = normalize_link(item["link"])
        if key not in seen:
            seen.add(key)
            unique.append(item)
    stats["merged_duplicates"] = len(resolved) + len(rest) - len(unique)
    stats["considered"] = len(top)
    return {**raw, "items": new_raw}, {**scores, "items": unique}, stats


def main() -> int:
    day = sys.argv[1] if len(sys.argv) > 1 else today()
    data = data_dir()
    try:
        raw = json.loads((data / f"{day}_raw.json").read_text(encoding="utf-8"))
        scores = json.loads((data / f"{day}_scores.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print("No raw/scores files: skipping Google News decoding.")
        return 0
    raw, scores, stats = decode_ranked(raw, scores)
    (data / f"{day}_raw.json").write_text(json.dumps(raw, indent=2), encoding="utf-8")
    (data / f"{day}_scores.json").write_text(json.dumps(scores, indent=2), encoding="utf-8")
    (data / f"{day}_decode.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
    print(f"Google News links among the top {stats['considered']} ranked: "
          f"decoded {stats['decoded']} of {stats['google_links']} "
          f"({stats['failed']} failed and kept as Google links, {stats['skipped']} not attempted, "
          f"{stats['merged_duplicates']} duplicate(s) merged)")
    for reason, count in stats["reasons"].items():
        print(f"  failed x{count}: {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
