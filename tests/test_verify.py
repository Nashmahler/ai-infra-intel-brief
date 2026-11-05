"""Verification tests: the source check (including a deliberately fake link), the
quote check (including a fabricated quote), and fail-closed behaviour."""
from src.verify import build_final, collected_links, evidence_index, verify_brief

DAY = "2026-11-04"
REAL = "https://pub.com/real-story"
SUMMARY = "CoreWeave signed a multi-year power deal in Texas, the company said in a statement."
ITEMS = [{"title": "CoreWeave power deal", "link": REAL, "source": "S", "publisher": "Pub",
          "published": "2026-11-04T00:00:00+00:00", "summary": SUMMARY},
         {"title": "Google one", "link": "https://pub.com/resolved", "source": "G",
          "publisher": "Pub", "published": "2026-11-04T00:00:00+00:00",
          "summary": "Oracle expanded the Abilene campus this week.",
          "original_link": "https://news.google.com/rss/articles/abc"}]
RAW = {"stats": {"scanned": 10, "kept": 2}, "failed_sources": [{"name": "Feed A", "reason": "x"}],
       "items": ITEMS}
GOOD_QUOTE = "signed a multi-year power deal in Texas"
ARTICLE = ("Paragraph one. The agreement covers 200 megawatts of new capacity, the company "
           "said. Local officials welcomed the project. " * 3)
FULLTEXT = {"articles": {REAL: ARTICLE}}


def top(link, quote=GOOD_QUOTE, confidence="Reported"):
    return {"what_happened": "W", "quote": quote, "why_it_matters": "Y", "area": "power",
            "confidence": confidence, "link": link}


def brief(top_links, watch_links=(), noise_links=(), **kw):
    return {"top": [top(l, **kw) for l in top_links],
            "watchlist": [{"market": "Chips & hardware", "line": "L", "link": l} for l in watch_links],
            "noise": [{"reason": "R", "link": l} for l in noise_links]}


def run(b, fulltext=None):
    return verify_brief(b, collected_links(ITEMS), evidence_index(ITEMS, fulltext))


# ---------------------------------------------------------------- link check

def test_fake_link_is_removed_and_logged():
    clean, log = run(brief([REAL, "https://fake.example/made-up"]))
    assert [t["link"] for t in clean["top"]] == [REAL]
    assert log[0]["link"] == "https://fake.example/made-up"
    assert log[0]["action"] == "removed" and log[0]["reason"] == "link not in collected set"


def test_missing_link_is_removed_in_every_section():
    clean, log = run(brief([REAL], watch_links=[""], noise_links=[""]))
    assert clean["watchlist"] == [] and clean["noise"] == []
    assert {r["section"] for r in log} == {"watchlist", "noise"}


def test_near_miss_link_is_not_trusted():
    clean, log = run(brief([REAL + "-2"]))
    assert clean["top"] == [] and len(log) == 1


def test_harmless_variants_are_tidied_to_the_collected_link():
    clean, log = run(brief([REAL + "/?utm_source=x"]))
    assert clean["top"][0]["link"] == REAL and log == []


def test_original_google_link_counts_as_collected_and_maps_to_publisher_url():
    clean, _ = run(brief(["https://news.google.com/rss/articles/abc"],
                         quote="expanded the Abilene campus this week"))
    assert clean["top"][0]["link"] == "https://pub.com/resolved"


def test_unknown_confidence_label_falls_back_to_reported():
    b = brief([REAL]); b["top"][0]["confidence"] = "Definitely"
    assert run(b)[0]["top"][0]["confidence"] == "Reported"


# --------------------------------------------------------------- quote check

def test_fabricated_quote_is_removed_and_logged_with_the_quote():
    fake = "CoreWeave will build a 5 gigawatt campus in Ohio"
    clean, log = run(brief([REAL], quote=fake))
    assert clean["top"] == []
    assert log[0]["action"] == "removed" and log[0]["reason"] == "quote not found in the source text"
    assert log[0]["quote"] == fake


def test_real_link_with_a_fabricated_quote_does_not_borrow_credit_from_the_link():
    """The link is genuine, but the quote isn't in its text: still removed."""
    clean, log = run(brief([REAL, REAL + "/x"], quote="a quote the article never contained"))
    assert clean["top"] == [] and len(log) == 2


def test_quote_matching_ignores_whitespace_curly_quotes_and_dash_styles():
    # The article uses curly quotes, a non-breaking hyphen, an em dash, a double space and a newline...
    text_items = [{**ITEMS[0], "summary": "He said it\u2019s a \u201cmulti\u2011year\u201d plan \u2014 and  fast.\n"}]
    # ...the quote uses straight quotes, a plain hyphen, a spaced hyphen and single spaces.
    b = brief([REAL], quote='it\'s a "multi-year" plan - and fast.')
    clean, _ = verify_brief(b, collected_links(text_items), evidence_index(text_items, None))
    assert len(clean["top"]) == 1


def test_quote_is_case_sensitive_and_must_be_one_unbroken_passage():
    assert run(brief([REAL], quote="SIGNED A MULTI-YEAR POWER DEAL IN TEXAS"))[0]["top"] == []
    spliced = "CoreWeave signed ... the company said in a statement"
    assert run(brief([REAL], quote=spliced))[0]["top"] == []


def test_missing_short_and_long_quotes_are_removed():
    for quote, why in [("", "missing quote"), ("power deal", "too short"),
                       (" ".join(["word"] * 25), "too long")]:
        clean, log = run(brief([REAL], quote=quote))
        assert clean["top"] == [] and why in log[0]["reason"], why


def test_quote_in_the_summary_is_accepted_and_tagged_summary():
    clean, _ = run(brief([REAL]))
    assert clean["top"][0]["evidence_source"] == "summary"


def test_quote_found_only_in_the_full_article_is_tagged_article():
    clean, log = run(brief([REAL], quote="The agreement covers 200 megawatts of new capacity"), FULLTEXT)
    assert clean["top"][0]["evidence_source"] == "article" and log == []


def test_confirmed_with_only_summary_evidence_is_downgraded_to_reported_and_logged():
    clean, log = run(brief([REAL], confidence="Confirmed"))
    assert clean["top"][0]["confidence"] == "Reported"
    assert [(r["action"], r["section"]) for r in log] == [("downgraded", "top")]


def test_confirmed_stays_confirmed_when_the_full_article_backs_it():
    clean, log = run(brief([REAL], quote="The agreement covers 200 megawatts of new capacity",
                           confidence="Confirmed"), FULLTEXT)
    assert clean["top"][0]["confidence"] == "Confirmed" and log == []


def test_watchlist_and_noise_items_need_no_quote():
    clean, log = run(brief([REAL], watch_links=[REAL + "/a"] and ["https://pub.com/resolved"],
                           noise_links=[]))
    assert len(clean["watchlist"]) == 1 and log == []


# ------------------------------------------------------------- build_final

def test_good_brief_is_published_with_footer_and_evidence_line():
    md, log, ok = build_final(DAY, RAW, brief([REAL]))
    assert ok and log == []
    assert md.startswith("# AI Infrastructure Intelligence Brief — prepared for Crusoe")
    assert f'<sub>**Evidence:** "{GOOD_QUOTE}" (RSS summary)</sub>' in md
    assert "Articles scanned: 10 · kept: 2 · sources that failed to load: Feed A" in md


def test_evidence_line_says_article_text_when_full_text_was_used():
    md, _, ok = build_final(DAY, RAW, brief([REAL], quote="The agreement covers 200 megawatts of new capacity"),
                            fulltext=FULLTEXT)
    assert ok and "(article text)</sub>" in md


def test_fails_closed_when_the_check_removes_every_top_item():
    md, log, ok = build_final(DAY, RAW, brief(["https://fake.example/1"], watch_links=[REAL]))
    assert not ok and "No verified brief today" in md and len(log) == 1
    assert "What happened" not in md
    assert "prepared for Crusoe" in md and "*November 4, 2026*" in md


def test_fails_closed_when_every_quote_is_fabricated():
    md, log, ok = build_final(DAY, RAW, brief([REAL], quote="This sentence is entirely invented here"))
    assert not ok and "No verified brief today" in md
    assert "source and quote checks" in md and log[0]["reason"] == "quote not found in the source text"


def test_fails_closed_when_feeds_returned_nothing():
    empty = {"stats": {"scanned": 0, "kept": 0},
             "failed_sources": [{"name": "Feed A", "reason": "down"}], "items": []}
    md, _, ok = build_final(DAY, empty, brief([REAL]))
    assert not ok and "No verified brief today" in md and "Feed A" in md


def test_fails_closed_when_raw_data_or_draft_is_missing():
    assert not build_final(DAY, None, brief([REAL]))[2]
    md, _, ok = build_final(DAY, RAW, None)
    assert not ok and "no draft brief was produced" in md


def test_main_writes_the_brief_under_the_profile_folder(tmp_path, monkeypatch):
    """With no data at all, verify fails closed and writes briefs/<profile>/<day>.md."""
    import src.config as config
    import src.verify as verify
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.delenv("TARGET_PROFILE", raising=False)
    monkeypatch.setattr("sys.argv", ["verify", DAY])
    assert verify.main() == 0
    out = tmp_path / "briefs" / "crusoe" / f"{DAY}.md"
    assert out.exists() and "No verified brief today" in out.read_text()
    assert (tmp_path / "data" / "crusoe" / f"{DAY}_verification.json").exists()
    assert not (tmp_path / "briefs" / f"{DAY}.md").exists()
