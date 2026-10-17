"""Excel-grade filtering (sub-project C): "matches pattern" and "does not
match pattern" -- * for any run of characters, ? for exactly one, matched
against the WHOLE value as shown, ignoring case, as Excel's custom filter
does. Every other character is literal (a "." is a dot, not "any")."""
from webcache.widgets.column_spec import Column
from webcache.widgets.record_filter import Condition, operators_for


def test_star_and_question_mark_match_as_in_excel():
    assert Condition("matches pattern", "*.zip").matches("tools/a.ZIP")
    assert not Condition("matches pattern", "*.zip").matches("a.zip.txt")
    assert Condition("matches pattern", "file?.txt").matches("file1.txt")
    assert not Condition("matches pattern", "file?.txt").matches("file10.txt")
    assert not Condition("matches pattern", "a.c").matches("abc")
    assert Condition("matches pattern", "a+b(c)").matches("A+B(C)")


def test_does_not_match_is_the_exact_inverse_and_blank_never_matches():
    for value in ("a.zip", "a.txt", "", None):
        yes = Condition("matches pattern", "*.zip").matches(value)
        no = Condition("does not match pattern", "*.zip").matches(value)
        assert yes != no, value


def test_text_columns_offer_the_pattern_operators():
    ops = operators_for(Column("Url", "Address", kind="url"), [])
    assert "matches pattern" in ops and "does not match pattern" in ops


def test_the_chip_says_it_in_words():
    text = Condition("matches pattern", "*.zip").describe()
    assert "matches pattern" in text and "*.zip" in text
