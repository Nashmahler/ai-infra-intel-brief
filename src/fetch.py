"""Step 2: fetch recent items, deduplicate them, filter by watchlist, save JSON.

Pipeline (each stage is its own small function so it can be tested alone):

    fetch_all()  ->  dedupe()  ->  filter_by_watchlist()  ->  data/YYYY-MM-DD_raw.json

An "item" is just a dict: {title, link, source, published, summary}.
"""
import calendar
import json
import re
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import feedparser

from .config import ROOT, agent_for, all_feeds

WINDOW_HOURS = 48          # how far back to look
TITLE_SIMILARITY = 0.85    # titles this alike (0-1) are treated as the same story


# ---------------------------------------------------------------- fetching

def clean_text(html: str, limit: int = 500) -> str:
    """Strip HTML tags and trim, so summaries are short plain text."""
    text = re.sub(r"<[^>]+>", " ", html or "")
    return re.sub(r"\s+", " ", text).strip()[:limit]


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
        items.append({
            "title": clean_text(e["title"], 300),
            "link": e["link"],
            "source": source,
            "published": published.isoformat(),
            "summary": clean_text(e.get("summary", "")),
        })
    return items


def fetch_feed(feed: dict, now: datetime) -> list[dict]:
    """Download one feed. Raises RuntimeError if it is down or empty."""
    parsed = feedparser.parse(feed["url"], agent=agent_for(feed))
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

def collect(feeds, terms, now, fetcher=fetch_feed) -> dict:
    """Run the whole collection pipeline and return the result as a dict."""
    fetched, failed = fetch_all(feeds, now, fetcher)
    unique = dedupe(fetched)
    kept = filter_by_watchlist(unique, terms)
    return {
        "generated_at": now.isoformat(),
        "window_hours": WINDOW_HOURS,
        "stats": {"scanned": len(fetched), "after_dedup": len(unique),
                  "kept": len(kept)},
        "failed_sources": failed,
        "items": kept,
    }


def main() -> None:
    from .config import watchlist_terms
    now = datetime.now(timezone.utc)
    result = collect(all_feeds(), watchlist_terms(), now)
    out = ROOT / "data" / f"{now:%Y-%m-%d}_raw.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    s = result["stats"]
    print(f"scanned {s['scanned']}, unique {s['after_dedup']}, kept {s['kept']}, "
          f"{len(result['failed_sources'])} source(s) failed -> {out}")
    for f in result["failed_sources"]:
        print(f"  FAILED {f['name']}: {f['reason']}")


if __name__ == "__main__":
    main()
