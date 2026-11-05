"""Google News decoding of the top-ranked stories. No network: a fake decoder and a fake clock."""
import json
import sys
import types

import pytest

import src.config as config
import src.decode as decode
from src.decode import (DECODE_TOP_N, DecodeError, decode_ranked, decode_with_package,
                        resolve_google_links)
from src.verify import collected_links

DAY = "2026-11-04"


def g_item(n, published="2026-11-04T12:00:00+00:00", **kw):
    return {"title": f"Story {n}", "link": f"https://news.google.com/rss/articles/ID{n}?oc=5",
            "source": "Google News: X", "publisher": f"Pub{n}", "published": published,
            "summary": "s", "score": 3, "story": n, **kw}


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
    clock, logs = FakeClock(), []
    out, stats = resolve_google_links(items, decoder, sleep=clock.sleep, clock=clock, log=logs.append, **kw)
    return out, stats, clock, logs


def ok(url):
    return url.replace("news.google.com/rss/articles/", "pub.com/").split("?")[0]


def fail(reason):
    def decoder(url):
        raise DecodeError(reason)
    return decoder


# ---------------------------------------------------------------- the basics

def test_top_n_is_sixty():
    assert DECODE_TOP_N == 60


def test_decoded_link_becomes_the_link_and_the_google_link_is_kept():
    out, stats, _, logs = resolve([g_item(1)], ok)
    assert out[0]["link"] == "https://pub.com/ID1"
    assert out[0]["original_link"] == "https://news.google.com/rss/articles/ID1?oc=5"
    assert stats["decoded"] == 1 and stats["failed"] == 0 and logs == []     # all good: no warnings


def test_a_link_that_cannot_be_decoded_is_left_exactly_as_it_was():
    item = g_item(1)
    out, stats, _, _ = resolve([item], fail("Google refused: blocked"))
    assert out == [item] and "original_link" not in out[0]
    assert stats["failed"] == 1 and stats["reasons"] == {"Google refused: blocked": 1}


def test_a_decoder_that_returns_nothing_counts_as_a_failure():
    out, stats, _, _ = resolve([g_item(1)], lambda url: None)
    assert out[0]["link"].startswith("https://news.google.com") and stats["reasons"] == {"no result": 1}


def test_only_google_links_are_ever_sent_to_the_decoder():
    seen = []
    resolve([g_item(1), {**g_item(2), "link": "https://pub2.com/direct"}], lambda u: seen.append(u) or ok(u))
    assert seen == ["https://news.google.com/rss/articles/ID1?oc=5"]


def test_links_are_decoded_in_the_order_given_best_ranked_first_not_newest_first():
    items = [g_item(1, published="2026-11-04T01:00:00+00:00"),       # best ranked but oldest
             g_item(2, published="2026-11-04T09:00:00+00:00"),
             g_item(3, published="2026-11-04T05:00:00+00:00")]
    calls = []
    out, _, clock, _ = resolve(items, lambda u: calls.append(u.split("/")[-1][:3]) or ok(u), interval=1.0)
    assert calls == ["ID1", "ID2", "ID3"]
    assert clock.slept == [1.0, 1.0]                                  # between calls, not before the first
    assert [i["title"] for i in out] == ["Story 1", "Story 2", "Story 3"]


# ------------------------------------------------------- budget and breaker

def test_the_time_budget_stops_decoding_before_a_request_would_start_too_late():
    items = [g_item(i) for i in range(10)]
    _, stats, _, logs = resolve(items, ok, interval=10.0, budget=25.0)
    assert stats["decoded"] == 3 and stats["skipped"] == 7             # starts at 0s, 10s, 20s; 30s is too late
    assert stats["stopped_because"] == "time budget used" and "stopped (time budget used)" in logs[-1]


def test_five_failures_in_a_row_means_google_is_refusing_so_we_stop():
    calls = []

    def decoder(url):
        calls.append(url)
        raise DecodeError("Google refused: 429")
    _, stats, _, _ = resolve([g_item(i) for i in range(12)], decoder)
    assert len(calls) == 5 and stats["failed"] == 5 and stats["skipped"] == 7
    assert stats["stopped_because"] == "5 failures in a row"


def test_a_success_resets_the_failure_streak():
    answers = iter([DecodeError("x")] * 4 + ["https://pub.com/ok"] + [DecodeError("x")] * 4)

    def decoder(url):
        a = next(answers)
        if isinstance(a, Exception):
            raise a
        return a
    _, stats, _, _ = resolve([g_item(i) for i in range(9)], decoder)
    assert stats["decoded"] == 1 and stats["failed"] == 8 and stats["skipped"] == 0


# ---------------------------------------------------------- logging failures

def test_it_logs_the_moment_decoding_starts_failing_with_how_far_it_got():
    answers = iter(["https://pub.com/a", "https://pub.com/b", DecodeError("Google refused: 429")])

    def decoder(url):
        a = next(answers)
        if isinstance(a, Exception):
            raise a
        return a
    _, _, _, logs = resolve([g_item(i) for i in range(3)], decoder)
    assert logs == ["::warning::Google News decoding started failing after 2 successful link(s): "
                    "Google refused: 429"]


def test_it_logs_when_the_very_first_request_fails():
    _, _, _, logs = resolve([g_item(1)], fail("googlenewsdecoder is not installed"))
    assert logs == ["::warning::Google News decoding started failing on the first request: "
                    "googlenewsdecoder is not installed"]


def test_it_logs_once_when_it_starts_failing_and_again_when_it_gives_up_with_the_last_reason():
    reasons = iter(["Google refused: 429"] * 4 + ["Google refused: 503"])

    def decoder(url):
        raise DecodeError(next(reasons))
    _, stats, _, logs = resolve([g_item(i) for i in range(8)], decoder)
    assert len(logs) == 2 and "started failing on the first request: Google refused: 429" in logs[0]
    assert "stopped (5 failures in a row)" in logs[1] and "3 link(s) stay as Google links" in logs[1]
    assert "Last reason: Google refused: 503" in logs[1]
    assert stats["reasons"] == {"Google refused: 429": 4, "Google refused: 503": 1}


def test_an_unexpected_error_from_a_custom_decoder_is_logged_not_raised():
    def boom(url):
        raise ConnectionError("network down")
    out, stats, _, logs = resolve([g_item(1)], boom)
    assert stats["reasons"] == {"network down": 1} and "network down" in logs[0]


# ------------------------------------------------------------ the package

def _fake_package(monkeypatch, behaviour):
    module = types.ModuleType("googlenewsdecoder")
    module.gnewsdecoder = behaviour
    monkeypatch.setitem(sys.modules, "googlenewsdecoder", module)


def test_package_results_are_read_defensively(monkeypatch):
    url = "https://news.google.com/rss/articles/ID1"
    _fake_package(monkeypatch, lambda u, **kw: {"success": True, "decoded_url": "https://pub.com/a"})
    assert decode_with_package(url) == "https://pub.com/a"
    _fake_package(monkeypatch, lambda u, **kw: {"status": True, "decoded_url": "https://pub.com/a"})
    assert decode_with_package(url) == "https://pub.com/a"             # older package versions
    for bad, reason in [({"success": False, "message": "blocked"}, "Google refused: blocked"),
                        ({"success": True, "decoded_url": "ftp://x"}, "not a publisher link"),
                        ({"success": True, "decoded_url": "https://news.google.com/again"}, "not a publisher link"),
                        ({}, "Google refused: no message"), (None, "unexpected result"), ("oops", "unexpected result")]:
        _fake_package(monkeypatch, lambda u, bad=bad, **kw: bad)
        with pytest.raises(DecodeError, match=reason):
            decode_with_package(url)


def test_package_errors_and_a_missing_package_become_decode_errors(monkeypatch):
    def boom(u, **kw):
        raise ConnectionError("network down")
    _fake_package(monkeypatch, boom)
    with pytest.raises(DecodeError, match="decoder raised ConnectionError: network down"):
        decode_with_package("https://news.google.com/rss/articles/ID1")
    monkeypatch.setitem(sys.modules, "googlenewsdecoder", None)           # makes the import fail
    with pytest.raises(DecodeError, match="not installed"):
        decode_with_package("https://news.google.com/rss/articles/ID1")


# --------------------------------------------- only the top 60 ranked items

def ranked_files(n_google, extra=None):
    items = [g_item(i) for i in range(n_google)] + (extra or [])
    return {"items": [dict(i) for i in items], "generated_at": "x"}, {"day": DAY, "items": [dict(i) for i in items]}


def test_only_the_top_sixty_ranked_items_are_decoded():
    raw, scores = ranked_files(70)
    seen = []
    new_raw, new_scores, stats = decode_ranked(raw, scores, lambda u: seen.append(u) or ok(u),
                                               sleep=lambda s: None)
    assert len(seen) == 60 and stats["considered"] == 60 and stats["decoded"] == 60
    decoded_titles = {i["title"] for i in new_scores["items"] if "original_link" in i}
    assert decoded_titles == {f"Story {i}" for i in range(60)}                # ranks 0..59 only
    assert all(i["link"].startswith("https://news.google.com") for i in new_scores["items"][60:])


def test_raw_and_scores_are_updated_together_so_both_urls_stay_in_the_collected_set():
    raw, scores = ranked_files(3)
    new_raw, new_scores, _ = decode_ranked(raw, scores, ok, sleep=lambda s: None)
    assert [i["link"] for i in new_raw["items"]] == [i["link"] for i in new_scores["items"]]
    allowed = collected_links(new_raw["items"])                               # what verification checks against
    for n in range(3):
        assert allowed["https://pub.com/ID%d" % n] == f"https://pub.com/ID{n}"
        assert "https://news.google.com/rss/articles/ID%d?oc=5" % n in allowed
        assert allowed["https://news.google.com/rss/articles/ID%d?oc=5" % n] == f"https://pub.com/ID{n}"


def test_a_decoded_duplicate_of_a_better_ranked_article_is_dropped_from_the_ranking_only():
    direct = {"title": "Direct copy", "link": "https://pub.com/ID1", "source": "DCD", "publisher": "DCD",
              "published": "2026-11-04T10:00:00+00:00", "summary": "s", "score": 5, "story": 99}
    raw, scores = ranked_files(0, [direct, g_item(1)])                         # direct is ranked first
    new_raw, new_scores, stats = decode_ranked(raw, scores, ok, sleep=lambda s: None)
    assert [i["title"] for i in new_scores["items"]] == ["Direct copy"]
    assert stats["merged_duplicates"] == 1 and len(new_raw["items"]) == 2      # raw keeps both


def test_failures_leave_links_untouched_and_are_reported_in_the_stats():
    raw, scores = ranked_files(4)
    new_raw, new_scores, stats = decode_ranked(raw, scores, fail("Google refused: 429"), sleep=lambda s: None)
    assert new_raw == raw and new_scores == scores
    assert stats["failed"] == 4 and stats["decoded"] == 0 and stats["reasons"] == {"Google refused: 429": 4}


# ---------------------------------------------------------------- the step

@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.delenv("TARGET_PROFILE", raising=False)
    monkeypatch.setattr("sys.argv", ["decode", DAY])
    return tmp_path


def test_main_updates_both_files_writes_a_log_and_reports_failures(repo, monkeypatch, capsys):
    raw, scores = ranked_files(3)
    data = config.data_dir()
    (data / f"{DAY}_raw.json").write_text(json.dumps(raw))
    (data / f"{DAY}_scores.json").write_text(json.dumps(scores))
    answers = iter(["https://pub.com/a", DecodeError("Google refused: 429"), "https://pub.com/c"])

    def fake(url):
        a = next(answers)
        if isinstance(a, Exception):
            raise a
        return a
    monkeypatch.setattr(decode, "decode_with_package", fake)
    monkeypatch.setattr(decode.time, "sleep", lambda s: None)
    assert decode.main() == 0
    out = capsys.readouterr().out
    assert "decoded 2 of 3 (1 failed and kept as Google links" in out
    assert "::warning::Google News decoding started failing after 1 successful link(s)" in out
    assert "failed x1: Google refused: 429" in out
    saved_raw = json.loads((data / f"{DAY}_raw.json").read_text())
    saved_scores = json.loads((data / f"{DAY}_scores.json").read_text())
    assert [i["link"] for i in saved_raw["items"]] == [i["link"] for i in saved_scores["items"]]
    assert saved_scores["items"][0]["link"] == "https://pub.com/a"
    assert saved_scores["items"][1]["link"].startswith("https://news.google.com")
    log = json.loads((data / f"{DAY}_decode.json").read_text())
    assert log["decoded"] == 2 and log["failed"] == 1 and log["reasons"] == {"Google refused: 429": 1}


def test_main_skips_cleanly_when_there_are_no_files(repo, capsys):
    assert decode.main() == 0 and "skipping Google News decoding" in capsys.readouterr().out
