"""Step 5: verify the draft brief in code, then publish it (or fail closed).

This is a plain code check, not an AI check:

  1. Every link in the brief must match an article collected in step 2.
     Any item with a missing or unmatched link is removed, and the removal is
     logged.
  2. If collection failed, the brief is missing, or no top development
     survives, we write a short "no verified brief today" file instead of a
     brief with unsupported claims. (Fail closed.)

Reads  data/<profile>/YYYY-MM-DD_raw.json and ..._brief.json
Writes briefs/<profile>/YYYY-MM-DD.md            (the published file)
       data/<profile>/YYYY-MM-DD_verification.json (what was removed, and why)
"""
import json
import sys
from datetime import datetime, timezone

from .config import briefs_dir, company_name, data_dir
from .fetch import normalize_link
from .write import CONFIDENCE, article_index, render_markdown, title_lines

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


def verify_brief(brief: dict, allowed: dict[str, str]) -> tuple[dict, list[dict]]:
    """Drop every item whose link is not in `allowed`. Returns (clean, removals).

    Surviving items get the canonical collected link, so a harmless variant
    (a trailing slash, a utm tag) is tidied rather than trusted as typed.
    """
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
                item = {**item, "link": allowed[normalize_link(link)]}
                if section == "top" and item.get("confidence") not in CONFIDENCE:
                    item["confidence"] = "Reported"   # unknown label -> safest label
                kept.append(item)
                continue
            removals.append({"section": section, "link": link, "reason": reason,
                             "text": (item.get("what_happened") or item.get("line")
                                      or item.get("reason") or "")[:120]})
        clean[section] = kept
    return clean, removals


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


def build_final(day: str, raw: dict | None, brief: dict | None, company: str | None = None):
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

    clean, removals = verify_brief(brief, collected_links(items))
    if not clean["top"]:
        why = ("every top development was removed by the source check" if brief.get("top")
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
           else datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    data = data_dir()
    md, removals, verified = build_final(
        day, read_json(data / f"{day}_raw.json"), read_json(data / f"{day}_brief.json"))

    for r in removals:   # the log of what the check removed
        print(f"REMOVED [{r['section']}] {r['reason']}: {r['link'] or '(none)'} | {r['text']}")
    (data / f"{day}_verification.json").write_text(
        json.dumps({"verified": verified, "removals": removals}, indent=2), encoding="utf-8")

    out = briefs_dir() / f"{day}.md"
    out.write_text(md, encoding="utf-8")
    print(f"{'verified brief' if verified else 'NO VERIFIED BRIEF'} -> {out} "
          f"({len(removals)} item(s) removed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
