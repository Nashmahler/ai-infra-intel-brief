"""Load the two config files and expand them into a flat list of feeds."""
import os
from pathlib import Path
from urllib.parse import quote_plus

import yaml

ROOT = Path(__file__).resolve().parent.parent

# SEC asks automated clients to identify themselves; other sites just like it.
USER_AGENT = "crusoe-intel-brief/0.1 (personal research prototype)"


class MissingConfig(RuntimeError):
    """A feed needs an environment variable that is not set."""


def agent_for(feed: dict) -> str:
    """User-Agent to send for this feed.

    SEC EDGAR feeds need a descriptive agent with contact info; it comes from
    the SEC_USER_AGENT environment variable so no email lives in the repo.
    """
    env = feed.get("agent_env")
    if not env:
        return USER_AGENT
    agent = os.environ.get(env, "").strip()
    if not agent:
        raise MissingConfig(f"{env} is not set")
    return agent


def load_yaml(name: str) -> dict:
    with open(ROOT / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


def watchlist_terms() -> list[str]:
    """Every term from watchlist.yaml as one flat list."""
    wl = load_yaml("watchlist.yaml")
    terms = [t for m in wl["markets"].values() for t in m["terms"]]
    terms += wl["crusoe"]["terms"]
    return terms


def all_feeds(include_google: bool = True) -> list[dict]:
    """Return [{'name': ..., 'url': ...}] for every configured feed.

    Google News feeds are generated from `google_news_terms` in sources.yaml
    (company/product names only; generic words like 'utility' are too noisy).
    """
    src = load_yaml("sources.yaml")
    feeds = list(src["feeds"])
    feeds += [{**f, "agent_env": "SEC_USER_AGENT"} for f in src["edgar"]]
    if include_google:
        for term in src.get("google_news_terms", []):
            feeds.append({
                "name": f"Google News: {term}",
                "url": src["google_news_template"].format(query=quote_plus(term)),
            })
    return feeds
