"""Step 5: verify the draft brief in code, then publish it (or fail closed).

This is a plain code check, not an AI check:

  1. Every link in the brief must match an article collected in step 2.
     Any item with a missing or unmatched link is removed, and the removal is
     logged.
  2. Every top development's supporting quote must appear, word for word
     (whitespace and quote styles aside), in the text we actually hold: the
     fetched article if we have it, otherwise the RSS title and summary. A
     missing, malformed, or non-matching quote removes the item. A "Confirmed"
     label also needs the quote to come from the full article; if only the RSS
     summary backs it, the label is downgraded to "Reported". Both are logged.
  2b. The business-impact fields are checked too. Direction and Channel must be
     one of the allowed values (otherwise the item is removed). Size must be a
     figure copied word for word from a quote that passes the quote check, or
     from the company profile; anything else (an invented or estimated number, a
     vague amount, a figure whose quote fails) is reset to exactly "unsized",
     and the reset is logged.
  3. If collection failed, the brief is missing, or no top development
     survives, we write a short "no verified brief today" file instead of a
     brief with unsupported claims. (Fail closed.)

Reads  data/<profile>/YYYY-MM-DD_raw.json, ..._fulltext.json and ..._brief.json
Writes briefs/<profile>/YYYY-MM-DD.md            (the published file)
       data/<profile>/YYYY-MM-DD_verification.json (what was removed, and why)
"""
import json
import sys

from .config import briefs_dir, company_name, data_dir, profile_facts_text, today
from .fetch import normalize_link
from .quotes import clean_quote, normalize, quote_problem
from .write import (CHANNELS, CONFIDENCE, DIRECTIONS, UNSIZED, article_index, render_markdown,
                    title_lines)

SECTIONS = ("top", "watchlist", "noise")


def collected_links(items: list[dict]) -> dict[str, str]:
    """Every link we really collected: normalized link -> canonical link.

    Includes the original Google News link when we resolved it to the
    publisher's URL; both count as collected, and both map to the publisher URL.
    """
    allowed = {}
    for i in items:
        allowed[normalize_link(i["link"])] = i["link"]
        if i.get("original_link"):
            allowed[normalize_link(i["original_link"])] = i["link"]
    return allowed


def evidence_index(items: list[dict], fulltext: dict | None) -> dict[str, dict]:
    """The text each collected link can be checked against.

    normalized link -> {"article": fetched full text or "", "summary": title + RSS summary}.
    Both the publisher link and the original Google News link point at the same entry.
    """
    articles = (fulltext or {}).get("articles", {})
    index = {}
    for i in items:
        entry = {"article": articles.get(i["link"], ""),
                 "summary": f"{i['title']} {i.get('summary', '')}"}
        index[normalize_link(i["link"])] = entry
        if i.get("original_link"):
            index[normalize_link(i["original_link"])] = entry
    return index


def check_quote(item: dict, evidence: dict | None) -> tuple[str | None, str | None]:
    """Check a top item's quote. Returns (problem, evidence_source).

    evidence_source is "article" if the quote is in the full text, "summary" if
    only in the RSS title/summary, None if the quote is rejected.
    """
    if evidence is None:
        return "no source text held for this link", None
    quote = item.get("quote") or ""
    if evidence["article"] and quote_problem(quote, evidence["article"]) is None:
        return None, "article"
    problem = quote_problem(quote, evidence["summary"])
    if problem is None:
        return None, "summary"
    return problem, None


def check_impact(item: dict) -> str | None:
    """Direction and Channel must be allowed values and Consider must say something."""
    if item.get("direction") not in DIRECTIONS:
        return f"invalid direction {item.get('direction')!r} (allowed: {', '.join(DIRECTIONS)})"
    if item.get("channel") not in CHANNELS:
        return f"invalid channel {item.get('channel')!r}"
    if not (item.get("consider") or "").strip():
        return "missing consider"
    return None


def resolve_size(item: dict, held: dict, profile_text: str) -> tuple[str, str | None, str | None, str | None]:
    """Decide the Size field. Returns (size, basis, size_evidence_source, why_reset).

    A figure is accepted only if it is copied word for word from
      - the company profile (basis "profile"), or
      - a size_quote that passes the same quote check as every claim, and that
        itself contains the figure (basis "source").
    Everything else becomes exactly "unsized"; `why_reset` says why, or is None
    when the model simply (and correctly) said "unsized".
    """
    size = (item.get("size") or "").strip().rstrip(".").strip()
    if size.lower() in ("", UNSIZED):
        return UNSIZED, None, None, None
    if not any(c.isdigit() for c in size) or len(size) > 60:
        return UNSIZED, None, None, "size is not a stated figure"
    if normalize(size) in normalize(profile_text):
        return size, "profile", None, None
    problem, source = check_quote({"quote": item.get("size_quote") or ""}, held)
    if problem:
        return UNSIZED, None, None, f"figure has no verified quote ({problem})"
    if normalize(size) not in clean_quote(item["size_quote"]):
        return UNSIZED, None, None, "figure does not appear in its quote"
    return size, "source", source, None


def verify_brief(brief: dict, allowed: dict[str, str], evidence: dict[str, dict],
                 profile_text: str | None = None) -> tuple[dict, list[dict]]:
    """Run the link check and the quote check. Returns (clean, log).

    The log has one entry per removal or downgrade: {"action": "removed" |
    "downgraded", "section", "link", "reason", "text"}.

    Surviving items get the canonical collected link, so a harmless variant
    (a trailing slash, a utm tag) is tidied rather than trusted as typed.
    """
    profile_text = profile_facts_text() if profile_text is None else profile_text
    clean, removals = {}, []
    for section in SECTIONS:
        kept = []
        for item in brief.get(section, []):
            link = (item.get("link") or "").strip()
            if not link:
                reason = "missing link"
            elif normalize_link(link) not in allowed:
                reason = "link not in collected set"
            else:
                reason = None
                item = {**item, "link": allowed[normalize_link(link)]}
                if section == "top":
                    if item.get("confidence") not in CONFIDENCE:
                        item["confidence"] = "Reported"   # unknown label -> safest label
                    held = evidence.get(normalize_link(link))
                    reason = check_impact(item)
                    source = None
                    if reason is None:
                        reason, source = check_quote(item, held)
                    if reason is None:
                        item["evidence_source"] = source
                        item["full_text"] = bool(held["article"])   # did we have the whole article?
                        if item["confidence"] == "Confirmed" and source == "summary":
                            item["confidence"] = "Reported"
                            removals.append(log_entry(
                                "downgraded", section, link, item,
                                "Confirmed needs the quote in the full article; "
                                "only the RSS summary backs it"))
                        size, basis, size_source, why = resolve_size(item, held, profile_text)
                        if why:
                            removals.append(log_entry("size_reset", section, link, item, why))
                        item.update(size=size, size_basis=basis, size_evidence_source=size_source)
                        if basis != "source":
                            item["size_quote"] = ""
                if reason is None:
                    kept.append(item)
                    continue
            removals.append(log_entry("removed", section, link, item, reason))
        clean[section] = kept
    return clean, removals


def log_entry(action: str, section: str, link: str, item: dict, reason: str) -> dict:
    """One line of the verification log."""
    text = item.get("what_happened") or item.get("line") or item.get("reason") or ""
    entry = {"action": action, "section": section, "link": link, "reason": reason,
             "text": text[:120]}
    if item.get("quote"):
        entry["quote"] = item["quote"][:160]
    if action == "size_reset":
        entry["size"] = (item.get("size") or "")[:60]
    return entry


def no_brief(day: str, reason: str, stats: dict, failed: list[str], company: str) -> str:
    """The fail-closed file: says plainly that there is no brief, and why."""
    failed_txt = ", ".join(failed) if failed else "none"
    return "\n".join(title_lines(company, day) + [
        "**No verified brief today.**", "",
        f"Reason: {reason}.", "",
        "Nothing is published when it cannot be checked against collected sources.", "",
        "---",
        f"*Articles scanned: {stats.get('scanned', 0)} · kept: {stats.get('kept', 0)} · "
        f"sources that failed to load: {failed_txt}*", ""])


def build_final(day: str, raw: dict | None, brief: dict | None, company: str | None = None,
                fulltext: dict | None = None):
    """Decide what gets published. Returns (markdown, removals, verified)."""
    company = company or company_name()
    raw = raw or {}
    stats = raw.get("stats", {"scanned": 0, "kept": 0})
    failed = [f["name"] for f in raw.get("failed_sources", [])]
    items = raw.get("items", [])

    if not items:
        return no_brief(day, "collection returned no usable articles", stats, failed, company), [], False
    if brief is None:
        return no_brief(day, "no draft brief was produced", stats, failed, company), [], False

    clean, removals = verify_brief(brief, collected_links(items),
                                   evidence_index(items, fulltext))
    if not clean["top"]:
        why = ("every top development was removed by the source and quote checks" if brief.get("top")
               else "the draft contained no top developments")
        return no_brief(day, why, stats, failed, company), removals, False
    return render_markdown(clean, day, article_index(items), stats, failed, company), removals, True


def read_json(path):
    """Load a JSON file, or None if it is missing or unreadable (we fail closed)."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def main() -> int:
    day = (sys.argv[1] if len(sys.argv) > 1
           else today())
    data = data_dir()
    md, removals, verified = build_final(
        day, read_json(data / f"{day}_raw.json"), read_json(data / f"{day}_brief.json"),
        fulltext=read_json(data / f"{day}_fulltext.json"))

    for r in removals:   # the log of what the checks removed or downgraded
        print(f"{r['action'].upper()} [{r['section']}] {r['reason']}: "
              f"{r['link'] or '(none)'} | {r['text']}"
              + (f" | quote: {r['quote']}" if r.get("quote") else ""))
    (data / f"{day}_verification.json").write_text(
        json.dumps({"verified": verified, "removals": removals}, indent=2), encoding="utf-8")

    out = briefs_dir() / f"{day}.md"
    out.write_text(md, encoding="utf-8")
    counts = {a: sum(r["action"] == a for r in removals)
              for a in ("removed", "downgraded", "size_reset")}
    print(f"{'verified brief' if verified else 'NO VERIFIED BRIEF'} -> {out} "
          f"({counts['removed']} item(s) removed, {counts['downgraded']} downgraded, "
          f"{counts['size_reset']} size(s) reset to unsized)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
