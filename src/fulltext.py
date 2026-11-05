"""Fetch the full text of the top-ranked articles, politely.

Reads  data/<profile>/YYYY-MM-DD_scores.json
Writes data/<profile>/YYYY-MM-DD_fulltext.json

The writer must back each "What happened" with a short quote, and verify.py
checks that quote against the text we really have. Full article text is the
best evidence, so for the strongest stories we try to fetch it, with rules:

  - robots.txt is obeyed (unreachable robots.txt counts as "do not fetch").
  - Paywalled or blocked pages (HTTP 401/402/403, or a page that declares
    itself not free, or one with almost no text) are not used.
  - Google News links are redirects to the publisher; we do not scrape them.
  - Anything that fails falls back to the RSS summary, and we record why.
"""
import json
import re
import sys
import urllib.error
import urllib.request
from html.parser import HTMLParser
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from .config import USER_AGENT, data_dir, today

N_FETCH = 10            # how many of the strongest stories to try
TIMEOUT = 10            # seconds per request
MAX_BYTES = 1_000_000   # never read more than this from one page
MIN_CHARS = 500         # less than this is a paywall stub or a JavaScript page
MAX_STORED = 60_000     # characters of text kept per article


# ------------------------------------------------------------------ network

def http_get(url: str) -> tuple[int, str, bytes]:
    """GET a URL. Returns (status, content_type, body). Raises on network errors."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.status, resp.headers.get("Content-Type", ""), resp.read(MAX_BYTES)
    except urllib.error.HTTPError as err:       # a real HTTP answer, e.g. 403
        return err.code, err.headers.get("Content-Type", "") if err.headers else "", b""


class Robots:
    """robots.txt rules per site, fetched once each."""

    def __init__(self, get=http_get):
        self.get, self.sites = get, {}

    def allowed(self, url: str) -> bool:
        p = urlparse(url)
        site = f"{p.scheme}://{p.netloc}"
        if site not in self.sites:
            self.sites[site] = self._load(site)
        rules = self.sites[site]
        return True if rules is True else False if rules is False else rules.can_fetch(USER_AGENT, url)

    def _load(self, site: str):
        try:
            status, _, body = self.get(f"{site}/robots.txt")
        except Exception:
            return False                  # cannot read the rules: do not fetch
        if status == 200:
            rules = RobotFileParser()
            rules.parse(body.decode("utf-8", errors="replace").splitlines())
            return rules
        return True if 400 <= status < 500 else False   # no robots.txt = allowed; server error = not


# --------------------------------------------------------------- HTML -> text

class _TextExtractor(HTMLParser):
    """Collect the text of paragraphs, headings, and list items; skip page chrome."""
    KEEP = {"p", "h1", "h2", "h3", "li", "blockquote"}
    SKIP = {"script", "style", "noscript", "nav", "header", "footer", "aside", "form", "svg"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skip, self.keep = [], 0, 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag in self.KEEP:
            self.keep += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        elif tag in self.KEEP:
            self.keep = max(0, self.keep - 1)
            self.parts.append("\n")

    def handle_data(self, data):
        if self.keep and not self.skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    return re.sub(r"[ \t]+", " ", "".join(parser.parts)).strip()


def declares_paywall(html: str) -> bool:
    """Publishers mark paywalled articles with isAccessibleForFree: false."""
    return bool(re.search(r'isAccessibleForFree"?\s*:\s*"?false', html, re.IGNORECASE))


# -------------------------------------------------------------------- fetch

def fetch_article_text(url: str, get=http_get, robots: Robots | None = None):
    """Return (text, None) on success or (None, reason) if we should not or cannot use it."""
    parts = urlparse(url)
    if parts.scheme not in ("http", "https"):
        return None, "not an http(s) link"
    if parts.netloc.endswith("news.google.com"):
        return None, "Google News redirect (publisher page not fetched)"
    if not (robots or Robots(get)).allowed(url):
        return None, "robots.txt does not allow it (or could not be read)"
    try:
        status, ctype, body = get(url)
    except Exception as err:
        return None, f"fetch failed: {err}"
    if status in (401, 402, 403):
        return None, f"paywalled or blocked (HTTP {status})"
    if status != 200:
        return None, f"HTTP {status}"
    if "html" not in ctype.lower():
        return None, f"not an HTML page ({ctype or 'unknown type'})"
    html = body.decode("utf-8", errors="replace")
    if declares_paywall(html):
        return None, "page declares itself paywalled"
    text = html_to_text(html)
    if len(text) < MIN_CHARS:
        return None, f"too little text ({len(text)} chars; likely a paywall or JavaScript page)"
    return text[:MAX_STORED], None


def fetch_top_articles(ranked: list[dict], get=http_get) -> dict:
    """Try the strongest story leads. Returns {"articles": {link: text}, "unavailable": {link: reason}}."""
    from .write import split_candidates          # same "strongest stories" the writer sees
    robots = Robots(get)
    out = {"articles": {}, "unavailable": {}}
    for item in split_candidates(ranked)[0][:N_FETCH]:
        text, reason = fetch_article_text(item["link"], get, robots)
        if text:
            out["articles"][item["link"]] = text
        else:
            out["unavailable"][item["link"]] = reason
    return out


def main() -> int:
    day = (sys.argv[1] if len(sys.argv) > 1
           else today())
    data = data_dir()
    try:
        ranked = json.loads((data / f"{day}_scores.json").read_text(encoding="utf-8"))["items"]
    except (OSError, ValueError):
        print("No scores file: skipping full-text fetch.")
        return 0
    result = fetch_top_articles(ranked)
    (data / f"{day}_fulltext.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"full text: {len(result['articles'])} article(s) fetched, "
          f"{len(result['unavailable'])} fell back to the RSS summary")
    for link, why in result["unavailable"].items():
        print(f"  summary only: {link[:80]} ({why})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
