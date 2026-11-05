"""Step 2: fetch recent items, deduplicate them, filter by watchlist, save JSON.

Pipeline (each stage is its own small function so it can be tested alone):

    fetch_all()  ->  dedupe()  ->  filter_by_watchlist()  ->  data/<profile>/YYYY-MM-DD_raw.json

An "item" is just a dict: {title, link, source, published, summary}.
"""
import base64
import calendar
import json
import re
import time
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import feedparser

from .config import USER_AGENT, all_feeds, data_dir, today

DECODE_INTERVAL = 1.0      # seconds to wait between requests to Google (a short rate limit)
MAX_DECODE = 150           # most Google links we will try to decode per run
DECODE_BUDGET = 300.0      # stop decoding after this many seconds in total
MAX_CONSECUTIVE_FAILURES = 5   # this many failures in a row = Google is refusing us; stop
WINDOW_HOURS = 48          # how far back to look
TITLE_SIMILARITY = 0.85    # titles this alike (0-1) are treated as the same story


# ---------------------------------------------------------------- fetching

def clean_text(html: str, limit: int = 500) -> str:
    """Strip HTML tags and trim, so summaries are short plain text."""
    text = re.sub(r"<[^>]+>", " ", html or "")
    return re.sub(r"\s+", " ", text).strip()[:limit]


def decode_google_news_url(url: str) -> str | None:
    """Recover the publisher's URL from a Google News article link, if possible.

    Older Google News links embed the real URL in base64; newer ones are
    encrypted and cannot be decoded offline. We do NOT guess or make extra
    web requests: when decoding fails we return None and the caller keeps the
    Google link and shows the publisher name instead.
    """
    parsed = urlparse(url)
    if parsed.netloc != "news.google.com" or "/articles/" not in parsed.path:
        return None
    article_id = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    try:
        raw = base64.urlsafe_b64decode(article_id + "=" * (-len(article_id) % 4))
    except ValueError:
        return None
    if raw.startswith(b"\x08\x13\x22"):
        raw = raw[3:]
    if raw.endswith(b"\xd2\x01\x00"):
        raw = raw[:-3]
    if not raw:
        return None
    length, start = raw[0], 1
    if length >= 0x80:                       # two-byte length
        if len(raw) < 2:
            return None
        length, start = (raw[0] & 0x7F) | (raw[1] << 7), 2
    try:
        candidate = raw[start:start + length].decode("utf-8")
    except UnicodeDecodeError:
        return None
    return candidate if candidate.startswith(("http://", "https://")) else None


def is_google_news(url: str) -> bool:
    return urlparse(url).netloc == "news.google.com"


def decode_with_package(url: str) -> str | None:
    """Ask the googlenewsdecoder package for a Google News link's publisher URL.

    This makes web requests to Google. Returns the publisher URL, or None on
    ANY failure (package missing, network error, Google refusing, odd result),
    so the caller can simply keep the original link.
    """
    try:
        from googlenewsdecoder import gnewsdecoder
        result = gnewsdecoder(url, timeout=10)       # we pace calls ourselves: no `interval`
    except Exception:
        return None
    if not isinstance(result, dict):
        return None
    ok = result.get("success", result.get("status"))   # newer versions say success, older status
    decoded = result.get("decoded_url") if ok else None
    if isinstance(decoded, str) and decoded.startswith(("http://", "https://")) \
            and not is_google_news(decoded):
        return decoded
    return None


def resolve_google_links(items: list[dict], decoder=decode_with_package,
                         interval: float = DECODE_INTERVAL, limit: int = MAX_DECODE,
                         budget: float = DECODE_BUDGET, sleep=time.sleep,
                         clock=time.monotonic) -> tuple[list[dict], dict]:
    """Replace Google News redirect links with the publisher's URL where we can.

    The decoded URL becomes `link` (used for full-text fetching and display) and
    the Google link is kept as `original_link`, so BOTH count as collected for
    verification. A link that cannot be decoded is left exactly as it was.

    Politeness and safety: newest items first; `interval` seconds between
    requests; at most `limit` attempts and `budget` seconds in total; and
    after MAX_CONSECUTIVE_FAILURES failures in a row we stop asking Google.
    Returns (items in their original order, stats).
    """
    pending = sorted((i for i, item in enumerate(items) if is_google_news(item["link"])),
                     key=lambda i: items[i]["published"], reverse=True)
    stats = {"google_links": len(pending), "google_decoded": 0, "google_failed": 0,
             "google_skipped": 0}
    out = list(items)
    started, last_call, streak = clock(), None, 0
    for n, i in enumerate(pending):
        # How long we must pause before this request (rate limit between requests).
        wait = 0.0 if last_call is None else max(0.0, interval - (clock() - last_call))
        out_of_time = (clock() - started) + wait > budget       # judged by when it would START
        if n >= limit or out_of_time or streak >= MAX_CONSECUTIVE_FAILURES:
            stats["google_skipped"] = len(pending) - n
            break
        if wait:
            sleep(wait)
        last_call = clock()
        decoded = decoder(items[i]["link"])
        if decoded:
            out[i] = {**items[i], "link": decoded, "original_link": items[i]["link"]}
            stats["google_decoded"] += 1
            streak = 0
        else:
            stats["google_failed"] += 1
            streak += 1
    return out, stats


def entries_to_items(parsed, source: str, now: datetime) -> list[dict]:
    """Turn a parsed feed into items published within the last WINDOW_HOURS.

    Entries with no title, no link, or no usable date are skipped: if we can't
    show it is recent and linkable, we don't use it.
    """
    cutoff = now - timedelta(hours=WINDOW_HOURS)
    items = []
    for e in parsed.entries:
        stamp = e.get("published_parsed") or e.get("updated_parsed")
        if not (e.get("title") and e.get("link") and stamp):
            continue
        published = datetime.fromtimestamp(calendar.timegm(stamp), tz=timezone.utc)
        if published < cutoff:
            continue
        # Google News marks the real publisher in <source>; other feeds ARE the publisher.
        publisher = (e.get("source") or {}).get("title") or source
        title = clean_text(e["title"], 300)
        if title.endswith(f" - {publisher}"):          # Google News appends it
            title = title[: -len(publisher) - 3]
        link, original = e["link"], None
        resolved = decode_google_news_url(link)
        if resolved:
            link, original = resolved, e["link"]
        item = {
            "title": title,
            "link": link,
            "source": source,
            "publisher": publisher,
            "published": published.isoformat(),
            "summary": clean_text(e.get("summary", "")),
        }
        if original:
            item["original_link"] = original   # still counts as a collected link
        items.append(item)
    return items


def fetch_feed(feed: dict, now: datetime) -> list[dict]:
    """Download one feed. Raises RuntimeError if it is down or empty."""
    parsed = feedparser.parse(feed["url"], agent=USER_AGENT)
    if not parsed.entries:
        reason = parsed.get("bozo_exception") or "feed returned no items"
        raise RuntimeError(str(reason))
    return entries_to_items(parsed, feed["name"], now)


def fetch_all(feeds: list[dict], now: datetime, fetcher=fetch_feed):
    """Fetch every feed. One bad feed never stops the rest.

    Returns (items, failed_sources). `fetcher` can be swapped out in tests.
    """
    items, failed = [], []
    for feed in feeds:
        try:
            items += fetcher(feed, now)
        except Exception as err:  # any failure: record it and move on
            failed.append({"name": feed["name"], "reason": str(err)})
    return items, failed


# ------------------------------------------------------------ deduplicating

def normalize_link(url: str) -> str:
    """Make two links to the same page compare equal.

    Drops tracking params (utm_*), #fragments, trailing slashes, and case.
    """
    p = urlparse(url.strip())
    query = [(k, v) for k, v in parse_qsl(p.query) if not k.startswith("utm_")]
    return urlunparse((p.scheme.lower(), p.netloc.lower(),
                       p.path.rstrip("/"), "", urlencode(query), ""))


def normalize_title(title: str) -> str:
    """Lowercase, drop a trailing ' - Publisher' (Google News style), strip punctuation."""
    title = re.sub(r"\s[-|–—]\s[^-|–—]+$", "", title)
    return re.sub(r"[^a-z0-9 ]", "", title.lower()).strip()


def dedupe(items: list[dict]) -> list[dict]:
    """Merge items covering the same story; the first one seen wins.

    Two items are the same story if their links match once normalized, or
    their titles are very similar. Feeds in sources.yaml are ordered with
    direct publishers first, so they win over Google News copies.
    """
    kept, seen_links, seen_titles = [], set(), []
    for item in items:
        link = normalize_link(item["link"])
        title = normalize_title(item["title"])
        if link in seen_links:
            continue
        if any(SequenceMatcher(None, title, t).ratio() >= TITLE_SIMILARITY
               for t in seen_titles):
            continue
        seen_links.add(link)
        seen_titles.append(title)
        kept.append(item)
    return kept


# ---------------------------------------------------------------- filtering

def filter_by_watchlist(items: list[dict], terms: list[str]) -> list[dict]:
    """Keep items whose title or summary mentions a watchlist term.

    Whole-word, case-insensitive ("AWS" will not match "laws"). Each kept item
    gets a `matched_terms` list so you can see why it was kept.
    """
    patterns = {t: re.compile(rf"(?<!\w){re.escape(t)}(?!\w)", re.IGNORECASE)
                for t in terms}
    kept = []
    for item in items:
        text = f"{item['title']} {item['summary']}"
        hits = [t for t, pat in patterns.items() if pat.search(text)]
        if hits:
            kept.append({**item, "matched_terms": hits})
    return kept


# --------------------------------------------------------------------- main

def collect(feeds, terms, now, fetcher=fetch_feed, resolver=resolve_google_links) -> dict:
    """Run the whole collection pipeline and return the result as a dict.

    Order matters: dedupe and filter first, so we only decode Google links for
    items we will actually use; then dedupe AGAIN, because two copies of one
    story (a publisher's own feed and its Google News copy) now share a URL.
    """
    fetched, failed = fetch_all(feeds, now, fetcher)
    unique = dedupe(fetched)
    kept = filter_by_watchlist(unique, terms)
    kept, google = resolver(kept)
    kept = dedupe(kept)
    return {
        "generated_at": now.isoformat(),
        "window_hours": WINDOW_HOURS,
        "stats": {"scanned": len(fetched), "after_dedup": len(unique),
                  "kept": len(kept), **google},
        "failed_sources": failed,
        "items": kept,
    }


def main(now: datetime | None = None) -> None:
    from .config import watchlist_terms
    now = now or datetime.now(timezone.utc)
    result = collect(all_feeds(), watchlist_terms(), now)
    out = data_dir() / f"{today(now)}_raw.json"
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    s = result["stats"]
    print(f"scanned {s['scanned']}, unique {s['after_dedup']}, kept {s['kept']}, "
          f"{len(result['failed_sources'])} source(s) failed -> {out}")
    print(f"Google News links: decoded {s['google_decoded']} of {s['google_links']} "
          f"({s['google_failed']} failed and kept as Google links, "
          f"{s['google_skipped']} not attempted)")
    for f in result["failed_sources"]:
        print(f"  FAILED {f['name']}: {f['reason']}")


if __name__ == "__main__":
    main()
