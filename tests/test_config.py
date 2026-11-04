"""Config and profile tests: the YAML files load and say what we intend."""
from pathlib import Path
from urllib.parse import unquote_plus

import pytest
import yaml

import src.config as config
from src.config import (ProfileError, all_feeds, available_profiles, company_name,
                        load_profile, profile_facts_text, watchlist_terms)

ROOT = Path(__file__).resolve().parent.parent

ACME = {
    "company": {"name": "Acme Power", "description": "a developer of test fixtures",
                "customers": ["Customer A"], "competitors": ["Rival A"],
                "business_areas": ["generation", "retail"]},
    "facts": ["Acme has one fact."],
    "watchlist_terms": ["Acme Power", "Jane Doe"],
    "google_news_terms": ["Acme Power", "Nvidia GPU"],     # second one duplicates a shared search
}


@pytest.fixture
def acme(tmp_path, monkeypatch):
    """A second profile in a temp folder, selected through TARGET_PROFILE."""
    (tmp_path / "acme.yaml").write_text(yaml.safe_dump(ACME))
    monkeypatch.setattr(config, "PROFILES_DIR", tmp_path)
    monkeypatch.setenv("TARGET_PROFILE", "acme")
    return tmp_path


# ---- default (Crusoe) profile

def test_crusoe_is_the_default_when_target_profile_is_unset_or_empty(monkeypatch):
    monkeypatch.delenv("TARGET_PROFILE", raising=False)
    assert company_name() == "Crusoe"
    monkeypatch.setenv("TARGET_PROFILE", "  ")
    assert company_name() == "Crusoe"


def test_crusoe_profile_loads_key_facts_and_searches():
    p = load_profile("crusoe")
    assert "1.2 GW Abilene" in profile_facts_text() and "Brighton" in profile_facts_text()
    assert "IPO" in profile_facts_text()
    assert {"Crusoe", "Crusoe Energy", "Abilene data center", "Stargate"} == set(p["google_news_terms"])
    assert {"Crusoe", "Crusoe Spark", "Chase Lochmiller"} <= set(p["watchlist_terms"])


def test_crusoe_searches_come_from_the_profile_not_the_shared_sources():
    shared = yaml.safe_load((ROOT / "sources.yaml").read_text())["google_news_terms"]
    assert not {"Crusoe", "Crusoe Energy", "Abilene data center", "Stargate"} & set(shared)


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


# ---- a second profile

def test_target_profile_switches_company_terms_and_searches(acme):
    assert company_name() == "Acme Power"
    terms = watchlist_terms()
    assert {"Acme Power", "Jane Doe", "CoreWeave", "Nvidia"} <= set(terms)   # own + shared
    assert "Crusoe" not in terms
    names = [f["name"] for f in all_feeds()]
    assert "Google News: Acme Power" in names and "Google News: CoreWeave" in names
    assert not any("Crusoe" in n or "Stargate" in n for n in names)
    assert len(names) == len({n.lower() for n in names})      # duplicate search fetched once


def test_unknown_profile_error_lists_what_is_available(monkeypatch):
    monkeypatch.setenv("TARGET_PROFILE", "nope")
    with pytest.raises(ProfileError, match="crusoe"):
        load_profile()


@pytest.mark.parametrize("bad", ["../secrets", "a/b", "_template", "Crusoe", ""])
def test_profile_names_cannot_escape_the_profiles_folder_or_pick_the_template(bad):
    with pytest.raises(ProfileError):
        load_profile(bad or "..")


def test_incomplete_profile_says_what_is_missing(acme):
    broken = {**ACME, "company": {"name": "Acme Power"}}
    (acme / "acme.yaml").write_text(yaml.safe_dump(broken))
    with pytest.raises(ProfileError, match="company.description"):
        load_profile()


def test_template_is_valid_but_not_selectable():
    assert "_template" not in available_profiles() and "crusoe" in available_profiles()
    t = yaml.safe_load((ROOT / "profiles" / "_template.yaml").read_text())
    assert all(t["company"].get(k) for k in config.REQUIRED_COMPANY_KEYS) and t["facts"]


def test_no_company_name_is_hardcoded_in_the_code():
    """Only the default profile NAME (config.py) may mention it; prompts and
    rendering must take the company from the profile."""
    for path in (ROOT / "src").glob("*.py"):
        if path.name == "config.py":
            continue
        assert "crusoe" not in path.read_text().lower(), path.name
