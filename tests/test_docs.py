"""The README is a 30-second page; the detail lives in docs/. Keep it that way, with working links,
and keep the auto-updated "Latest brief" line working on the real README."""
import re
from pathlib import Path

import pytest

from src.index import END, START, update_readme

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
DOCS = sorted((ROOT / "docs").glob("*.md"))
CHECKED = [README, *DOCS, ROOT / "evals" / "results.md"]


def sections(text):
    """{heading: [lines]} for the ## sections of a markdown file."""
    out, current = {}, None
    for line in text.splitlines():
        if line.startswith("## "):
            current = out.setdefault(line[3:].strip(), [])
        elif current is not None:
            current.append(line)
    return out


def bullets(lines):
    return [l for l in lines if l.startswith("- ")]


def slug(heading):
    """GitHub's anchor for a heading: lowercase, punctuation dropped, spaces to hyphens."""
    text = heading.replace("`", "").strip().lower()
    return re.sub(r"\s", "-", re.sub(r"[^\w\s-]", "", text))


def links(text):
    """Relative link targets in a markdown file, ignoring code blocks and code spans."""
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    text = re.sub(r"`[^`\n]*`", "", text)
    return [t for t in re.findall(r"\[[^\]]*\]\(([^)\s]+)\)", text) if not re.match(r"(https?:|mailto:)", t)]


# ------------------------------------------------------------------ the README

def test_readme_is_a_30_second_page_of_about_40_lines():
    lines = README.read_text().splitlines()
    assert 25 <= len(lines) <= 45, len(lines)


def test_readme_has_the_title_then_the_latest_brief_block_then_the_five_parts_in_order():
    text = README.read_text()
    lines = text.splitlines()
    assert lines[0].startswith("# ") and lines[1] == "" and lines[2] == START and lines[4] == END
    assert lines[3].startswith("**Latest brief") and "<!--profile:" in lines[3]
    one_sentence = lines[6]
    assert one_sentence and not one_sentence.startswith("#") and one_sentence.count(". ") == 0   # a single sentence
    assert list(sections(text)) == ["What it does", "How I know it's trustworthy", "Known limitations", "More detail"]


def test_readme_bullet_counts_match_the_brief():
    s = sections(README.read_text())
    assert 4 <= len(bullets(s["What it does"])) <= 5
    assert 3 <= len(bullets(s["How I know it's trustworthy"])) <= 4
    assert len(bullets(s["Known limitations"])) == 3


def test_the_trust_bullets_carry_real_numbers_that_match_the_eval_results():
    trust = " ".join(sections(README.read_text())["How I know it's trustworthy"])
    assert re.search(r"\b\d{3} (automated )?tests\b", trust)
    assert "75%" in trust and "90%" in trust and "fail" in trust.lower() and "quote" in trust.lower()
    assert "held-out set it had never seen" in trust                   # the held-out result is cited, not just the tuning set
    results = (ROOT / "evals" / "results.md").read_text()
    assert "75%" in results and "90%" in results                       # the same numbers, in the record
    assert "Held-out set" in results and "Not directly comparable to the tuning set" in results


def test_readme_points_at_every_doc_and_the_spec():
    more = " ".join(sections(README.read_text())["More detail"])
    for target in ("docs/architecture.md", "docs/setup.md", "docs/evals.md", "SPEC.md"):
        assert f"]({target})" in more, target


# ------------------------------------------------------------------- the docs

@pytest.mark.parametrize("path", DOCS, ids=lambda p: p.name)
def test_each_doc_has_a_title_and_a_way_back_to_the_readme(path):
    text = path.read_text()
    assert text.startswith("# ") and "](../README.md)" in text


def test_the_three_docs_exist_and_hold_the_relocated_sections():
    names = {p.name: sections(p.read_text()) for p in DOCS}
    assert set(names) == {"architecture.md", "setup.md", "evals.md"}
    assert {"What the brief looks like", "How it works", "How verification works",
            "Known limitations", "What's next"} <= set(names["architecture.md"])
    assert {"Setup", "Adding a new company", "Tests"} <= set(names["setup.md"])
    assert "The eval set" in names["evals.md"]


@pytest.mark.parametrize("path", CHECKED, ids=lambda p: str(p.relative_to(ROOT)))
def test_every_relative_link_and_anchor_resolves(path):
    for target in links(path.read_text()):
        name, _, anchor = target.partition("#")
        dest = (path.parent / name).resolve() if name else path
        assert dest.exists(), f"{path.name}: broken link {target}"
        if anchor and dest.suffix == ".md":
            headings = [slug(l.lstrip("#")) for l in dest.read_text().splitlines() if l.startswith("#")]
            assert anchor in headings, f"{path.name}: no heading for #{anchor} in {dest.name}"


def test_nothing_still_points_at_readme_sections_that_moved():
    for name in ("sources.yaml", "profiles/crusoe.yaml", "SPEC.md"):
        text = (ROOT / name).read_text()
        assert 'see README, "' not in text and "see the README)" not in text, name


# ------------------------------------------- the auto-updated "Latest brief" line

def test_the_latest_brief_updater_is_idempotent_on_the_real_readme():
    text = README.read_text()
    line = next(l for l in text.splitlines() if l.startswith("**Latest brief"))
    assert update_readme(text, "crusoe", line) == text


def test_a_new_latest_brief_only_changes_the_marked_block_of_the_real_readme():
    text = README.read_text()
    new_line = "**Latest brief — Crusoe:** [January 2, 2027](briefs/crusoe/2027-01-02.md) · [all briefs](briefs/crusoe/README.md) <!--profile:crusoe-->"
    updated = update_readme(text, "crusoe", new_line)
    assert new_line in updated and updated != text
    outside = lambda t: re.sub(re.escape(START) + r".*?" + re.escape(END), "", t, flags=re.S)
    assert outside(updated) == outside(text)                          # nothing else moved
    assert updated.splitlines()[:3] == text.splitlines()[:3]          # the block still sits under the title
