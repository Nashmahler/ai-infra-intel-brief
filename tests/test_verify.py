"""Verification tests: the source check, including a deliberately fake link,
and the fail-closed behaviour for empty or failed collection."""
from src.verify import build_final, collected_links, verify_brief

DAY = "2026-11-04"
REAL = "https://pub.com/real-story"
ITEMS = [{"title": "Real story", "link": REAL, "source": "S", "publisher": "Pub",
          "published": "2026-11-04T00:00:00+00:00", "summary": "x"},
         {"title": "Google one", "link": "https://pub.com/resolved", "source": "G",
          "publisher": "Pub", "published": "2026-11-04T00:00:00+00:00", "summary": "x",
          "original_link": "https://news.google.com/rss/articles/abc"}]
RAW = {"stats": {"scanned": 10, "kept": 2}, "failed_sources": [{"name": "Feed A", "reason": "x"}],
       "items": ITEMS}


def top(link):
    return {"what_happened": "W", "why_it_matters": "Y", "area": "power",
            "confidence": "Reported", "link": link}


def brief(top_links, watch_links=(), noise_links=()):
    return {"top": [top(l) for l in top_links],
            "watchlist": [{"market": "Chips & hardware", "line": "L", "link": l} for l in watch_links],
            "noise": [{"reason": "R", "link": l} for l in noise_links]}


def test_fake_link_is_removed_and_logged():
    clean, removals = verify_brief(brief([REAL, "https://fake.example/made-up"]),
                                   collected_links(ITEMS))
    assert [t["link"] for t in clean["top"]] == [REAL]
    assert removals[0]["link"] == "https://fake.example/made-up"
    assert removals[0]["reason"] == "link not in collected set"


def test_missing_link_is_removed_in_every_section():
    b = brief([REAL], watch_links=[""], noise_links=[""])
    clean, removals = verify_brief(b, collected_links(ITEMS))
    assert clean["watchlist"] == [] and clean["noise"] == []
    assert {r["section"] for r in removals} == {"watchlist", "noise"}


def test_near_miss_link_is_not_trusted():
    clean, removals = verify_brief(brief([REAL + "-2"]), collected_links(ITEMS))
    assert clean["top"] == [] and len(removals) == 1


def test_harmless_variants_are_tidied_to_the_collected_link():
    clean, removals = verify_brief(brief([REAL + "/?utm_source=x"]), collected_links(ITEMS))
    assert clean["top"][0]["link"] == REAL and removals == []


def test_original_google_link_counts_as_collected_and_maps_to_publisher_url():
    clean, _ = verify_brief(brief(["https://news.google.com/rss/articles/abc"]),
                            collected_links(ITEMS))
    assert clean["top"][0]["link"] == "https://pub.com/resolved"


def test_unknown_confidence_label_falls_back_to_reported():
    b = brief([REAL]); b["top"][0]["confidence"] = "Definitely"
    clean, _ = verify_brief(b, collected_links(ITEMS))
    assert clean["top"][0]["confidence"] == "Reported"


def test_good_brief_is_published_with_footer():
    md, removals, ok = build_final(DAY, RAW, brief([REAL]))
    assert ok and removals == []
    assert md.startswith("# AI Infrastructure Intelligence Brief — prepared for Crusoe")
    assert "Articles scanned: 10 · kept: 2 · sources that failed to load: Feed A" in md


def test_fails_closed_when_the_check_removes_every_top_item():
    md, removals, ok = build_final(DAY, RAW, brief(["https://fake.example/1"],
                                                   watch_links=[REAL]))
    assert not ok and "No verified brief today" in md and len(removals) == 1
    assert "What happened" not in md
    assert "prepared for Crusoe" in md and "*November 4, 2026*" in md


def test_fails_closed_when_feeds_returned_nothing():
    empty = {"stats": {"scanned": 0, "kept": 0},
             "failed_sources": [{"name": "Feed A", "reason": "down"}], "items": []}
    md, _, ok = build_final(DAY, empty, brief([REAL]))
    assert not ok and "No verified brief today" in md and "Feed A" in md


def test_fails_closed_when_raw_data_or_draft_is_missing():
    assert not build_final(DAY, None, brief([REAL]))[2]
    md, _, ok = build_final(DAY, RAW, None)
    assert not ok and "no draft brief was produced" in md
