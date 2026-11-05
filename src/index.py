"""Keep the briefs easy to find after every run.

Writes briefs/<profile>/README.md, an index of every brief newest first, and
updates the "Latest brief" line at the top of the main README.

The main README line sits between two marker comments, with one line per
profile, so a run for one company never erases another company's link:

    <!-- latest-brief:start -->
    **Latest brief — Acme:** [November 4, 2026](briefs/acme/2026-11-04.md) · [all briefs](briefs/acme/README.md) <!--profile:acme-->
    <!-- latest-brief:end -->
"""
import re
import sys
from datetime import date

from .config import ROOT, briefs_dir, company_name, profile_name

BRIEF_FILE = re.compile(r"(\d{4}-\d{2}-\d{2})\.md")
START, END = "<!-- latest-brief:start -->", "<!-- latest-brief:end -->"


def pretty(day: str) -> str:
    d = date.fromisoformat(day)
    return f"{d:%B} {d.day}, {d:%Y}"


def list_briefs(folder) -> list[dict]:
    """Every brief in the folder, newest first: {day, verified, weekly}."""
    briefs = []
    for path in folder.iterdir():
        m = BRIEF_FILE.fullmatch(path.name)
        if m:
            text = path.read_text(encoding="utf-8")
            briefs.append({"day": m[1], "verified": "No verified brief today" not in text,
                           "weekly": "## This week's themes" in text})
    return sorted(briefs, key=lambda b: b["day"], reverse=True)


def render_index(company: str, briefs: list[dict]) -> str:
    """The folder's README: a plain list, newest first."""
    lines = [f"# Briefs prepared for {company}", "",
             f"{len(briefs)} brief{'s' if len(briefs) != 1 else ''}, newest first. "
             "A day marked *no verified brief* is where the checks could not support a brief, "
             "so none was published.", ""]
    for b in briefs:
        note = ("" if b["verified"] else " — *no verified brief*") + (" · weekly themes" if b["weekly"] else "")
        lines.append(f"- [{pretty(b['day'])}]({b['day']}.md){note}")
    return "\n".join(lines) + "\n"


def latest_line(profile: str, company: str, briefs: list[dict]) -> str | None:
    """The README line for this profile: the newest *verified* brief."""
    verified = [b for b in briefs if b["verified"]]
    if not verified:
        return None
    line = (f"**Latest brief — {company}:** [{pretty(verified[0]['day'])}]"
            f"(briefs/{profile}/{verified[0]['day']}.md) · "
            f"[all briefs](briefs/{profile}/README.md)")
    if briefs[0] is not verified[0]:
        line += f" (no verified brief on {pretty(briefs[0]['day'])})"
    return f"{line} <!--profile:{profile}-->"


def update_readme(text: str, profile: str, line: str) -> str:
    """Put `line` in the marked block under the title, keeping other profiles' lines."""
    others = []
    if START in text and END in text:
        block = text[text.index(START) + len(START):text.index(END)]
        others = [l.strip().removeprefix("- ") for l in block.splitlines()
                  if l.strip() and f"<!--profile:{profile}-->" not in l]
        text = text[:text.index(START)].rstrip("\n") + "\n" + text[text.index(END) + len(END):].lstrip("\n")
    lines = sorted(others + [line], key=lambda l: re.search(r"<!--profile:(.*?)-->", l).group(1))
    body = lines[0] if len(lines) == 1 else "\n".join(f"- {l}" for l in lines)
    block = f"{START}\n{body}\n{END}"
    first, _, rest = text.partition("\n")                  # the "# Title" line stays on top
    return f"{first}\n\n{block}\n\n{rest.lstrip(chr(10))}"


def main() -> int:
    folder, profile = briefs_dir(), profile_name()
    briefs = list_briefs(folder)
    if not briefs:
        print("No briefs yet: nothing to index.")
        return 0
    company = company_name()
    (folder / "README.md").write_text(render_index(company, briefs), encoding="utf-8")
    line = latest_line(profile, company, briefs)
    if line:
        readme = ROOT / "README.md"
        readme.write_text(update_readme(readme.read_text(encoding="utf-8"), profile, line),
                          encoding="utf-8")
    print(f"indexed {len(briefs)} brief(s); latest verified: "
          f"{next((b['day'] for b in briefs if b['verified']), 'none')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
