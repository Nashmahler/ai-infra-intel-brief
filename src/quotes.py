"""Quote checking, shared by the daily verification and the weekly synthesis.

A supporting quote proves a claim is anchored in real text: the quote must
appear, word for word, in the text we actually have. We forgive only
differences that carry no meaning: whitespace, curly vs straight quotes, and
dash styles. Everything else (case, wording, order) must match exactly.
"""
import re
import unicodedata

MIN_WORDS = 4     # a 1-3 word "quote" would match almost anything
MAX_WORDS = 24    # "under 25 words"

_QUOTE_MAP = str.maketrans({
    "\N{LEFT SINGLE QUOTATION MARK}": "'", "\N{RIGHT SINGLE QUOTATION MARK}": "'",
    "\N{SINGLE LOW-9 QUOTATION MARK}": "'", "\N{SINGLE HIGH-REVERSED-9 QUOTATION MARK}": "'",
    "\N{LEFT DOUBLE QUOTATION MARK}": '"', "\N{RIGHT DOUBLE QUOTATION MARK}": '"',
    "\N{DOUBLE LOW-9 QUOTATION MARK}": '"',
    "\N{LEFT-POINTING DOUBLE ANGLE QUOTATION MARK}": '"',
    "\N{RIGHT-POINTING DOUBLE ANGLE QUOTATION MARK}": '"',
    "\N{HYPHEN}": "-", "\N{NON-BREAKING HYPHEN}": "-", "\N{EN DASH}": "-",
    "\N{EM DASH}": "-", "\N{MINUS SIGN}": "-",
})


def normalize(text: str) -> str:
    """Make two renderings of the same words compare equal.

    NFKC also turns non-breaking spaces and the ellipsis character into plain
    spaces and '...'; then we unify quote and dash styles and collapse
    whitespace.
    """
    text = unicodedata.normalize("NFKC", text or "").translate(_QUOTE_MAP)
    return re.sub(r"\s+", " ", text).strip()


def clean_quote(quote: str) -> str:
    """Normalize a model-written quote and drop one pair of wrapping quote marks."""
    q = normalize(quote)
    if len(q) >= 2 and q[0] == q[-1] and q[0] in "\"'":
        q = q[1:-1].strip()
    return q


def quote_problem(quote: str, text: str) -> str | None:
    """Return why `quote` is not acceptable evidence in `text`, or None if it is."""
    q = clean_quote(quote)
    words = len(q.split())
    if not q:
        return "missing quote"
    if words < MIN_WORDS:
        return f"quote too short ({words} words; need at least {MIN_WORDS})"
    if words > MAX_WORDS:
        return f"quote too long ({words} words; must be under 25)"
    if q not in normalize(text):
        return "quote not found in the source text"
    return None
