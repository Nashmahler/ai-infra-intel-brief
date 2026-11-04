"""Config tests: the YAML files load and say what we intend."""
from urllib.parse import unquote_plus

from src.config import all_feeds, crusoe_profile_text, watchlist_terms


def test_google_news_searches_are_generated_and_url_encoded():
    feeds = {f["name"]: f["url"] for f in all_feeds()}
    for term in ("Crusoe Energy", "Texas data center policy", "data center ballot measure"):
        url = feeds[f"Google News: {term}"]
        assert url.startswith("https://news.google.com/rss/search?q=")
        assert unquote_plus(url.split("q=")[1].split("&")[0]) == term


def test_every_feed_has_a_name_and_https_url():
    feeds = all_feeds()
    assert len(feeds) == len({f["name"] for f in feeds})          # names are unique
    assert all(f["url"].startswith("https://") for f in feeds)


def test_ambiguous_watchlist_terms_stay_tightened():
    terms = watchlist_terms()
    assert not {"Lambda", "Spark", "utility"} & set(terms)
    assert {"Lambda Labs", "Crusoe Spark", "Crusoe"} <= set(terms)


def test_profile_loads_key_facts():
    text = crusoe_profile_text()
    assert "1.2 GW Abilene" in text and "Brighton" in text and "IPO" in text
