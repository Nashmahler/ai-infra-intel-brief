"""Load the config files and expand them into watchlist terms and feed lists.

Three layers of configuration, all plain YAML (no code changes to edit them):

  watchlist.yaml / sources.yaml   shared industry markets, feeds and searches
  profiles/<name>.yaml            everything specific to the target company
  TARGET_PROFILE (env var)        which profile to use; default "crusoe"

Output is kept per profile (data/<profile>/ and briefs/<profile>/), so several
companies never overwrite each other's files.
"""
import os
import re
from pathlib import Path
from urllib.parse import quote_plus

import yaml

ROOT = Path(__file__).resolve().parent.parent
PROFILES_DIR = ROOT / "profiles"
DEFAULT_PROFILE = "crusoe"

# Identify ourselves politely to every site we fetch from.
USER_AGENT = "ai-infra-intel-brief/0.1 (personal research prototype)"

REQUIRED_COMPANY_KEYS = ("name", "description", "customers", "competitors", "business_areas")


class ProfileError(RuntimeError):
    """The selected profile is missing or malformed. The message says how to fix it."""


def load_yaml(name: str) -> dict:
    with open(ROOT / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ----------------------------------------------------------------- profiles

def profile_name() -> str:
    """The selected profile: TARGET_PROFILE if set (and non-empty), else the default."""
    return os.environ.get("TARGET_PROFILE", "").strip() or DEFAULT_PROFILE


def available_profiles() -> list[str]:
    """Names you can put in TARGET_PROFILE (files starting with '_' are templates)."""
    return sorted(p.stem for p in PROFILES_DIR.glob("*.yaml") if not p.stem.startswith("_"))


def load_profile(name: str | None = None) -> dict:
    """Load and validate profiles/<name>.yaml (default: the TARGET_PROFILE setting)."""
    name = name or profile_name()
    # The name becomes a file name, so only allow plain names (no paths, no "..").
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", name):
        raise ProfileError(f"Invalid TARGET_PROFILE {name!r}: use lowercase letters, "
                           f"digits, '-' or '_'. Available: {', '.join(available_profiles())}")
    path = PROFILES_DIR / f"{name}.yaml"
    if not path.exists():
        raise ProfileError(f"No profile {name!r} (looked for {path.name} in profiles/). "
                           f"Available: {', '.join(available_profiles()) or 'none'}")
    profile = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    company = profile.get("company") or {}
    missing = [k for k in REQUIRED_COMPANY_KEYS if not company.get(k)]
    if missing or not profile.get("facts"):
        raise ProfileError(f"Profile {name!r} is missing: "
                           + ", ".join([f"company.{k}" for k in missing]
                                       + ([] if profile.get("facts") else ["facts"])))
    profile.setdefault("watchlist_terms", [])
    profile.setdefault("google_news_terms", [])
    return profile


def data_dir() -> Path:
    """Working files for the selected profile: data/<profile>/ (created if needed)."""
    path = ROOT / "data" / profile_name()
    path.mkdir(parents=True, exist_ok=True)
    return path


def briefs_dir() -> Path:
    """Published briefs for the selected profile: briefs/<profile>/ (created if needed)."""
    path = ROOT / "briefs" / profile_name()
    path.mkdir(parents=True, exist_ok=True)
    return path


def company_name() -> str:
    return load_profile()["company"]["name"]


def profile_facts_text() -> str:
    """The profile's facts as a bulleted block for prompts."""
    return "\n".join(f"- {fact}" for fact in load_profile()["facts"])


# --------------------------------------------------------- terms and feeds

def market_labels() -> list[str]:
    """Names of the shared industry markets (from watchlist.yaml)."""
    return [m["label"] for m in load_yaml("watchlist.yaml")["markets"].values()]


def watchlist_terms() -> list[str]:
    """Shared market terms plus the target company's own terms, as one flat list."""
    wl = load_yaml("watchlist.yaml")
    terms = [t for m in wl["markets"].values() for t in m["terms"]]
    return terms + list(load_profile()["watchlist_terms"])


def all_feeds(include_google: bool = True) -> list[dict]:
    """Return [{'name': ..., 'url': ...}] for every configured feed.

    Google News feeds are generated: one search per term, from the shared
    `google_news_terms` in sources.yaml plus the profile's own. Company
    names/products only; generic words like 'utility' are too noisy.
    """
    src = load_yaml("sources.yaml")
    feeds = list(src["feeds"])
    if include_google:
        seen = set()
        for term in list(src.get("google_news_terms", [])) + load_profile()["google_news_terms"]:
            if term.lower() in seen:      # same search listed twice: fetch once
                continue
            seen.add(term.lower())
            feeds.append({
                "name": f"Google News: {term}",
                "url": src["google_news_template"].format(query=quote_plus(term)),
            })
    return feeds
