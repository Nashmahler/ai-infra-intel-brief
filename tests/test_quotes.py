"""Quote-matching rules, in isolation."""
from src.quotes import MAX_WORDS, MIN_WORDS, clean_quote, normalize, quote_problem

TEXT = "The utility said it will add 300 MW by 2028. “We are moving fast,” a spokesman said."


def test_normalize_unifies_whitespace_quotes_dashes_and_ellipsis():
    assert normalize("a “b”  c\n d — e …") == 'a "b" c d - e ...'


def test_clean_quote_drops_one_pair_of_wrapping_quote_marks():
    assert clean_quote('"it will add 300 MW"') == "it will add 300 MW"
    assert clean_quote("“it will add 300 MW”") == "it will add 300 MW"
    assert clean_quote("workers' union said") == "workers' union said"      # not wrapped: untouched


def test_accepts_an_exact_passage_even_across_curly_quotes():
    assert quote_problem('"We are moving fast," a spokesman said', TEXT) is None
    assert quote_problem("it will add 300 MW by 2028", TEXT) is None


def test_rejects_wrong_case_paraphrase_and_spliced_passages():
    assert quote_problem("IT WILL ADD 300 MW BY 2028", TEXT)
    assert quote_problem("the utility will add 300 megawatts by 2028", TEXT)
    assert quote_problem("will add 300 MW ... moving fast", TEXT)


def test_word_limits():
    assert "too short" in quote_problem("add 300 MW", TEXT)
    assert quote_problem(" ".join(["word"] * MIN_WORDS), "word " * 50) is None
    assert "too long" in quote_problem(" ".join(["word"] * (MAX_WORDS + 1)), "word " * 50)
    assert quote_problem(" ".join(["word"] * MAX_WORDS), "word " * 50) is None   # 24 is under 25


def test_empty_quote_or_empty_text():
    assert quote_problem("", TEXT) == "missing quote"
    assert quote_problem("some four word quote", "") == "quote not found in the source text"
