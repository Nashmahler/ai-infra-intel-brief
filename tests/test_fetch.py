"""Tests for fetch, dedupe, and filter. No network: uses a saved sample feed."""
from datetime import datetime, timezone
from pathlib import Path

import feedparser

from src.fetch import (collect, dedupe, entries_to_items, fetch_all,
                       filter_by_watchlist)

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
    assert result["stats"] == {"scanned": 2, "after_dedup": 2, "kept": 1}
    assert result["failed_sources"][0]["name"] == "down"
