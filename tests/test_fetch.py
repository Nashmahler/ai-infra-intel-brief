"""Tests for fetch, dedupe, and filter. No network: uses a saved sample feed."""
from datetime import datetime, timezone
from pathlib import Path

import feedparser

import base64

from src.fetch import (collect, decode_google_news_url, dedupe, entries_to_items,
                       fetch_all, filter_by_watchlist)

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
SAMPLE = Path(__file__).parent / "samples" / "sample_feed.xml"


def item(title, link, summary=""):
    return {"title": title, "link": link, "source": "t",
            "published": NOW.isoformat(), "summary": summary}


def sample_items():
    return entries_to_items(feedparser.parse(SAMPLE.read_text()), "Sample", NOW)


def test_recent_window_drops_old_and_undated_items():
    titles = [i["title"] for i in sample_items()]
    assert "Ancient Nvidia news" not in titles          # older than 48h
    assert "No date on this CoreWeave item" not in titles  # no date
    assert len(titles) == 2


def test_html_stripped_from_summary():
    assert "<p>" not in sample_items()[0]["summary"]


def test_dedupe_same_link_ignoring_tracking_params():
    out = dedupe([item("A story", "https://x.com/a/"),
                  item("Different words entirely", "https://X.com/a?utm_source=rss")])
    assert len(out) == 1


def test_dedupe_similar_titles_across_publishers():
    out = dedupe([item("Nvidia delays Rubin GPU launch", "https://a.com/1"),
                  item("Nvidia delays Rubin GPU launch - Reuters", "https://b.com/2"),
                  item("Utility files interconnection request", "https://c.com/3")])
    assert [i["link"] for i in out] == ["https://a.com/1", "https://c.com/3"]


def test_filter_keeps_only_watchlist_matches_and_records_terms():
    out = filter_by_watchlist(sample_items(), ["CoreWeave", "Nvidia"])
    assert len(out) == 1 and out[0]["matched_terms"] == ["CoreWeave"]


def test_filter_matches_whole_words_only():
    assert filter_by_watchlist([item("New laws passed", "https://a.com")], ["AWS"]) == []


def test_failed_and_empty_feeds_do_not_stop_the_run():
    def fetcher(feed, now):
        if feed["name"] == "down":
            raise RuntimeError("connection refused")
        if feed["name"] == "empty":
            raise RuntimeError("feed returned no items")
        return [item("CoreWeave news", "https://ok.com/1")]

    feeds = [{"name": n, "url": ""} for n in ("down", "empty", "good")]
    items, failed = fetch_all(feeds, NOW, fetcher)
    assert len(items) == 1
    assert [f["name"] for f in failed] == ["down", "empty"]


def test_collect_reports_stats_and_failures():
    def fetcher(feed, now):
        if feed["name"] == "down":
            raise RuntimeError("boom")
        return [item("CoreWeave news", "https://ok.com/1"),
                item("Bakery news", "https://ok.com/2")]

    result = collect([{"name": "down", "url": ""}, {"name": "good", "url": ""}],
                     ["CoreWeave"], NOW, fetcher)
    assert {k: result["stats"][k] for k in ("scanned", "after_dedup", "kept")} == \
        {"scanned": 2, "after_dedup": 2, "kept": 1}
    assert result["failed_sources"][0]["name"] == "down"


def gnews_link(url: str) -> str:
    """Build an old-style Google News link that embeds `url` (as Google once did)."""
    payload = b"\x08\x13\x22" + bytes([len(url)]) + url.encode() + b"\xd2\x01\x00"
    return "https://news.google.com/rss/articles/" + base64.urlsafe_b64encode(payload).decode().rstrip("=")


def test_google_news_link_resolves_to_publisher_url_when_decodable():
    assert decode_google_news_url(gnews_link("https://pub.com/story")) == "https://pub.com/story"


def test_undecodable_google_link_is_left_alone_not_guessed():
    assert decode_google_news_url("https://news.google.com/rss/articles/CBMiAU_yqLencrypted") is None
    assert decode_google_news_url("https://example.com/a") is None


def test_google_item_keeps_original_link_and_shows_publisher():
    real, google = "https://pub.com/story", gnews_link("https://pub.com/story")
    xml = f"""<?xml version="1.0"?><rss version="2.0"><channel><title>g</title>
    <item><title>CoreWeave wins deal - Reuters</title><link>{google}</link>
    <pubDate>Tue, 03 Nov 2026 12:00:00 GMT</pubDate>
    <source url="https://reuters.com">Reuters</source></item></channel></rss>"""
    [it] = entries_to_items(feedparser.parse(xml), "Google News: CoreWeave", NOW)
    assert it["link"] == real and it["original_link"] == google
    assert it["publisher"] == "Reuters" and it["title"] == "CoreWeave wins deal"


def test_fetch_feed_raises_on_empty_feed(monkeypatch):
    """A feed that parses but has no items must count as a failure."""
    import pytest

    import src.fetch as fetch
    monkeypatch.setattr(fetch.feedparser, "parse",
                        lambda *a, **k: feedparser.parse("<rss version='2.0'><channel/></rss>"))
    with pytest.raises(RuntimeError):
        fetch.fetch_feed({"name": "Empty", "url": "https://x"}, NOW)
