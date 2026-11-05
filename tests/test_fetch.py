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
    assert result["stats"]["google_links"] == 0              # nothing to decode here
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


# ----------------------------------------------- Google News link decoding

def g_item(n, published="2026-11-04T12:00:00+00:00", link=None, title=None):
    return {"title": title or f"Story {n}", "link": link or f"https://news.google.com/rss/articles/ID{n}?oc=5",
            "source": "Google News: X", "publisher": f"Pub{n}", "published": published, "summary": "s"}


class FakeClock:
    """Time that only moves when asked, so rate-limit tests need no real waiting."""
    def __init__(self):
        self.now, self.slept = 0.0, []
    def __call__(self):
        return self.now
    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


def resolve(items, decoder, **kw):
    from src.fetch import resolve_google_links
    clock = FakeClock()
    out, stats = resolve_google_links(items, decoder, sleep=clock.sleep, clock=clock, **kw)
    return out, stats, clock


def test_decoded_link_becomes_the_link_and_the_google_link_is_kept():
    out, stats, _ = resolve([g_item(1)], lambda url: "https://pub1.com/story")
    assert out[0]["link"] == "https://pub1.com/story"
    assert out[0]["original_link"] == "https://news.google.com/rss/articles/ID1?oc=5"
    assert stats["google_decoded"] == 1 and stats["google_failed"] == 0


def test_a_link_that_cannot_be_decoded_is_left_exactly_as_it_was():
    item = g_item(1)
    out, stats, _ = resolve([item], lambda url: None)
    assert out == [item] and "original_link" not in out[0]
    assert stats["google_failed"] == 1


def test_only_google_links_are_ever_sent_to_the_decoder():
    seen = []
    items = [g_item(1), {**g_item(2), "link": "https://pub2.com/direct"}]
    resolve(items, lambda url: seen.append(url) or "https://pub1.com/story")
    assert seen == ["https://news.google.com/rss/articles/ID1?oc=5"]


def test_requests_are_spaced_by_the_interval_and_the_original_order_is_kept():
    items = [g_item(i, published=f"2026-11-04T0{i}:00:00+00:00") for i in (1, 2, 3)]
    calls = []
    out, _, clock = resolve(items, lambda url: calls.append(url) or url.replace("news.google.com/rss/articles/", "pub.com/"),
                            interval=1.0)
    assert [c.split("/")[-1][:3] for c in calls] == ["ID3", "ID2", "ID1"]    # newest first
    assert clock.slept == [1.0, 1.0]                                          # between calls, not before the first
    assert [i["title"] for i in out] == ["Story 1", "Story 2", "Story 3"]    # order unchanged


def test_attempt_limit_and_time_budget_stop_decoding():
    items = [g_item(i) for i in range(10)]
    _, stats, _ = resolve(items, lambda url: "https://pub.com/x", limit=4)
    assert stats["google_decoded"] == 4 and stats["google_skipped"] == 6
    _, stats, _ = resolve(items, lambda url: "https://pub.com/x", interval=10.0, budget=25.0)
    assert stats["google_decoded"] == 3 and stats["google_skipped"] == 7      # 0s, 10s, 20s, then 30s > 25s


def test_five_failures_in_a_row_means_google_is_refusing_so_we_stop():
    calls = []
    _, stats, _ = resolve([g_item(i) for i in range(12)], lambda url: calls.append(url) and None)
    assert len(calls) == 5 and stats["google_failed"] == 5 and stats["google_skipped"] == 7


def test_a_success_resets_the_failure_streak():
    answers = iter([None] * 4 + ["https://pub.com/ok"] + [None] * 4)
    _, stats, _ = resolve([g_item(i) for i in range(9)], lambda url: next(answers))
    assert stats["google_decoded"] == 1 and stats["google_failed"] == 8 and stats["google_skipped"] == 0


def _fake_package(monkeypatch, behaviour):
    import sys
    import types
    module = types.ModuleType("googlenewsdecoder")
    module.gnewsdecoder = behaviour
    monkeypatch.setitem(sys.modules, "googlenewsdecoder", module)


def test_package_results_are_read_defensively(monkeypatch):
    from src.fetch import decode_with_package
    url = "https://news.google.com/rss/articles/ID1"
    _fake_package(monkeypatch, lambda u, **kw: {"success": True, "decoded_url": "https://pub.com/a"})
    assert decode_with_package(url) == "https://pub.com/a"
    _fake_package(monkeypatch, lambda u, **kw: {"status": True, "decoded_url": "https://pub.com/a"})
    assert decode_with_package(url) == "https://pub.com/a"                     # older package versions
    for bad in ({"success": False, "message": "blocked"}, {"success": True, "decoded_url": "ftp://x"},
                {"success": True, "decoded_url": "https://news.google.com/again"}, {}, None, "oops"):
        _fake_package(monkeypatch, lambda u, bad=bad, **kw: bad)
        assert decode_with_package(url) is None


def test_package_errors_never_escape(monkeypatch):
    from src.fetch import decode_with_package

    def boom(u, **kw):
        raise ConnectionError("network down")
    _fake_package(monkeypatch, boom)
    assert decode_with_package("https://news.google.com/rss/articles/ID1") is None


def test_collect_decodes_after_filtering_and_dedupes_again_by_publisher_url():
    """The publisher's own feed and its Google News copy are one story once decoded."""
    direct = {"title": "CoreWeave signs power deal", "link": "https://pub.com/story", "source": "DCD",
              "publisher": "DCD", "published": "2026-11-04T10:00:00+00:00", "summary": "CoreWeave deal."}
    google = g_item(1, title="CoreWeave expands in Texas")                       # different title, same article
    off_topic = g_item(2, title="Local bakery wins award")
    decoded_for = []

    def decoder(url):
        decoded_for.append(url)
        return "https://pub.com/story"

    from src.fetch import resolve_google_links
    result = collect([{"name": "f", "url": ""}], ["CoreWeave"], NOW,
                     lambda feed, now: [direct, {**google, "summary": "CoreWeave Texas"}, off_topic],
                     resolver=lambda items: resolve_google_links(items, decoder, sleep=lambda s: None))
    assert len(decoded_for) == 1                                                 # the bakery item was filtered out first
    assert [i["link"] for i in result["items"]] == ["https://pub.com/story"]     # merged into one
    assert result["stats"]["google_decoded"] == 1 and result["stats"]["kept"] == 1
