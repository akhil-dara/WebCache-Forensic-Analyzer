"""Five states a missing value can be in, five different sentences.

The record detail dialog renders every field a record carries, and most
records carry fields with no value. "No value" is not one fact -- it is
at least four, and they are not interchangeable:

  (empty)             the column exists on this record and holds nothing.
                      That is what the database STORES.
  Not determinable    the evidence cannot answer this. A string carved out
                      of page slack has no Flags column, so whether the
                      visit was InPrivate is unknowable, not absent.
  (not recovered)     a carve did not reach this column. The value may
                      have existed; these bytes do not carry it.
  (not applicable)    this field does not exist for this kind of record.
  (not supplied)      the request itself never carried this value. Location
                      is what needed it: an accuracy radius the requesting
                      application never put in the URL is not "empty" (the
                      database stores no column for it), not undeterminable
                      (it is perfectly determinable that none was sent), not
                      "not recovered" (nothing was carved) and not "not
                      applicable" (the field is exactly right for this kind
                      of row). Its absence is a fact about the REQUEST.

A blank cell says all five at once, which is to say it says nothing, and
an examiner reading a blank has no way to tell "the database stored
nothing here" from "our carve missed it". This module is the vocabulary;
detail_fields.py is what applies it.

ABSENCE_NOT_DETERMINABLE already existed (aliased to
CONTAINER_NOT_DETERMINABLE, one spelling, deliberately) -- these tests
pin the other three and the reason text beside it.
"""
import pytest

from webcache import provenance


def test_the_five_absence_tokens_exist_and_are_distinct():
    """Five states, five tokens. Two that render identically would be one
    state wearing two names, which is the failure this vocabulary exists
    to prevent."""
    tokens = (provenance.ABSENCE_EMPTY,
              provenance.ABSENCE_NOT_DETERMINABLE,
              provenance.ABSENCE_NOT_RECOVERED,
              provenance.ABSENCE_NOT_APPLICABLE,
              provenance.ABSENCE_NOT_SUPPLIED)
    assert len(set(tokens)) == 5, tokens
    assert set(tokens) == set(provenance.ABSENCE_TOKENS)
    for t in tokens:
        assert isinstance(t, str) and t.strip(), repr(t)


def test_not_determinable_keeps_the_one_spelling_it_already_had():
    """A second wording for the identical fact would need a second styling
    rule in record_model.py and would let two cells that mean the same
    thing look different on screen. This is an alias, not a new constant.
    """
    assert (provenance.ABSENCE_NOT_DETERMINABLE
            is provenance.CONTAINER_NOT_DETERMINABLE)


def test_every_token_carries_a_reason_and_no_reason_is_empty():
    for token in provenance.ABSENCE_TOKENS:
        reason = provenance.absence_reason(token)
        assert reason, token
        # A sentence, not a label: this is what a tooltip shows an
        # examiner who does not already know the difference.
        assert len(reason) > 30, (token, reason)


def test_the_five_reasons_are_five_different_sentences():
    reasons = [provenance.absence_reason(t) for t in provenance.ABSENCE_TOKENS]
    assert len(set(reasons)) == 5, reasons


def test_the_empty_reason_says_the_database_stored_nothing_not_that_reading_failed():
    """The distinction the whole vocabulary turns on. "(empty)" is a fact
    about the evidence, not a fact about this tool."""
    reason = provenance.absence_reason(provenance.ABSENCE_EMPTY)
    assert "not a failure to read" in reason.lower()


def test_the_not_recovered_reason_does_not_claim_the_value_never_existed():
    """A carve that missed a column proves nothing about whether the
    column held a value. Saying it did not would be an assertion the
    evidence does not support."""
    reason = provenance.absence_reason(provenance.ABSENCE_NOT_RECOVERED)
    assert "may have existed" in reason.lower()


def test_absence_reason_of_an_ordinary_value_is_empty():
    """A real value is not an absence and must not acquire an explanation
    of why it is missing."""
    for value in ("https://example.test/", "", 0, None, False):
        assert provenance.absence_reason(value) == ""


def test_is_absence_recognises_the_tokens_and_nothing_else():
    for token in provenance.ABSENCE_TOKENS:
        assert provenance.is_absence(token) is True, token
    # 0, False and "" are REAL VALUES, never absence markers -- the exact
    # bug class describe_origin's `if offset is not None` already avoids.
    for value in (0, False, "", None, "Live record", 0.0):
        assert provenance.is_absence(value) is False, repr(value)


@pytest.mark.parametrize("token", ["(empty)", "(not recovered)",
                                   "(not applicable)", "(not supplied)"])
def test_the_bracketed_tokens_read_as_annotations_not_as_data(token):
    """Parenthesised on purpose: an examiner pasting a cell into a report
    must be able to see at a glance that "(empty)" is this tool talking,
    not a value the database held. "Not determinable" is the one
    exception and it is a full sentence fragment for the same reason."""
    assert token in provenance.ABSENCE_TOKENS
    assert token.startswith("(") and token.endswith(")")


def test_not_supplied_says_the_absence_is_a_fact_about_the_request():
    """The distinction that earns this token its place. An accuracy radius
    the requesting application never put in the URL is not a gap in the
    parse -- nothing failed, nothing was destroyed, and the field is
    exactly the right one for the row. What happened is that the request
    did not carry it, and that is itself evidence."""
    reason = provenance.absence_reason(provenance.ABSENCE_NOT_SUPPLIED)
    assert "did not include" in reason.lower()
    assert "not a gap in the parse" in reason.lower()


def test_not_supplied_is_not_the_same_token_as_not_applicable():
    """"Not applicable" says the field does not exist for this kind of
    row. "Not supplied" says it does, and the request left it out. A
    Location Accuracy cell reading "(not applicable)" would claim a
    position fix has no accuracy to report, which is false."""
    assert (provenance.ABSENCE_NOT_SUPPLIED
            is not provenance.ABSENCE_NOT_APPLICABLE)
    assert (provenance.ABSENCE_NOT_SUPPLIED
            != provenance.ABSENCE_NOT_APPLICABLE)
    assert provenance.is_absence(provenance.ABSENCE_NOT_SUPPLIED) is True
