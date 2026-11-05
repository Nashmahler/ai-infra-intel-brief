"""Full-text fetching: robots.txt, paywalls, fallbacks. No real network: a fake `get`."""
import json

from src.fulltext import (Robots, declares_paywall, fetch_article_text, fetch_top_articles,
                          html_to_text)

PARAGRAPH = "The company announced a new campus that will add several hundred megawatts. " * 4
PAGE = f"""<html><head><title>T</title><script>var tracking = "SCRIPT TEXT";</script></head><body>
<nav><ul><li>MENU ITEM</li></ul></nav><header><p>HEADER TEXT</p></header>
<article><h1>Big campus announced</h1><p>{PARAGRAPH}</p><p>{PARAGRAPH}</p></article>
<footer><p>FOOTER TEXT</p></footer></body></html>"""
URL = "https://pub.com/story"


def router(pages=None, robots="User-agent: *\nAllow: /", robots_status=200):
    """A fake HTTP client. pages: {url: (status, content_type, body)}."""
    pages = pages or {}

    def get(url):
        if url.endswith("/robots.txt"):
            if robots_status == "error":
                raise ConnectionError("robots unreachable")
            return robots_status, "text/plain", robots.encode()
        if url not in pages:
            raise ConnectionError("no route")
        status, ctype, body = pages[url]
        return status, ctype, body.encode() if isinstance(body, str) else body
    return get


def ok_page(html=PAGE):
    return {URL: (200, "text/html; charset=utf-8", html)}


def test_html_to_text_keeps_article_text_and_drops_page_chrome():
    text = html_to_text(PAGE)
    assert "announced a new campus" in text and "Big campus announced" in text
    for junk in ("SCRIPT TEXT", "MENU ITEM", "HEADER TEXT", "FOOTER TEXT"):
        assert junk not in text


def test_successful_fetch_returns_text():
    text, why = fetch_article_text(URL, router(ok_page()))
    assert why is None and "announced a new campus" in text


def test_robots_disallow_means_the_page_is_never_requested():
    requested = []
    inner = router(ok_page(), robots="User-agent: *\nDisallow: /")
    def get(url):
        requested.append(url)
        return inner(url)
    text, why = fetch_article_text(URL, get)
    assert text is None and "robots.txt" in why
    assert URL not in requested


def test_robots_unreadable_server_error_means_do_not_fetch_but_404_means_allowed():
    assert fetch_article_text(URL, router(ok_page(), robots_status="error"))[0] is None
    assert fetch_article_text(URL, router(ok_page(), robots="", robots_status=503))[0] is None
    assert fetch_article_text(URL, router(ok_page(), robots="", robots_status=404))[0] is not None


def test_robots_rules_are_fetched_once_per_site():
    calls = []
    inner = router({**ok_page(), "https://pub.com/other": (200, "text/html", PAGE)})
    def get(url):
        calls.append(url)
        return inner(url)
    robots = Robots(get)
    fetch_article_text(URL, get, robots)
    fetch_article_text("https://pub.com/other", get, robots)
    assert sum(c.endswith("/robots.txt") for c in calls) == 1


def test_paywall_signals_fall_back_with_a_reason():
    for status in (401, 402, 403):
        text, why = fetch_article_text(URL, router({URL: (status, "text/html", "")}))
        assert text is None and f"HTTP {status}" in why
    marked = PAGE.replace("<head>", '<head><script type="application/ld+json">{"isAccessibleForFree": false}</script>')
    assert declares_paywall(marked)
    text, why = fetch_article_text(URL, router(ok_page(marked)))
    assert text is None and "paywalled" in why


def test_stub_pages_and_non_html_fall_back():
    short = "<html><body><p>Subscribe to keep reading.</p></body></html>"
    text, why = fetch_article_text(URL, router(ok_page(short)))
    assert text is None and "too little text" in why
    text, why = fetch_article_text(URL, router({URL: (200, "application/pdf", b"%PDF")}))
    assert text is None and "not an HTML page" in why
    assert fetch_article_text(URL, router({URL: (404, "text/html", "")}))[1] == "HTTP 404"


def test_network_errors_never_raise():
    text, why = fetch_article_text("https://down.example/x", router({}))
    assert text is None and "fetch failed" in why


def test_google_news_redirects_and_odd_schemes_are_not_fetched():
    get = router({})
    assert "Google News" in fetch_article_text("https://news.google.com/rss/articles/abc", get)[1]
    assert fetch_article_text("ftp://pub.com/x", get)[0] is None


def test_fetch_top_articles_collects_text_and_records_why_others_fell_back():
    ranked = [{"title": f"t{i}", "link": link, "source": "S", "publisher": "P", "summary": "s",
               "published": "2026-11-04T00:00:00+00:00", "score": 5 - i, "reason": "r",
               "story": i, "coverage": 1, "story_score": 5 - i, "is_lead": True}
              for i, link in enumerate([URL, "https://news.google.com/rss/articles/abc",
                                        "https://paywalled.example/x"])]
    pages = {**ok_page(), "https://paywalled.example/x": (403, "text/html", "")}
    result = fetch_top_articles(ranked, router(pages))
    assert list(result["articles"]) == [URL]
    assert set(result["unavailable"]) == {ranked[1]["link"], ranked[2]["link"]}
    json.dumps(result)                                       # it must be writable as JSON
