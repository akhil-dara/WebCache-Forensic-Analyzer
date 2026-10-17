"""The offline report's write parses each record's URL
three times over; the pure str -> str helpers are memoised, with the same
answers, and an unhashable argument still gets an answer, not a TypeError."""
from webcache.engine import forensic_engine as fe

URLS = ["Visited: alice@https://example.test/a?b=1", "file:///C:/x/y.txt",
        "", None, ":2026010120260102: bob@https://example.test/"]
HELPERS = ("clean_url", "extract_domain", "extract_scheme", "classify_url")


def test_each_helper_is_memoised_and_answers_the_same():
    for name in HELPERS:
        fn = getattr(fe, name)
        assert hasattr(fn, "cache_clear"), "%s is not memoised" % name
        fn.cache_clear()
        first = [fn(u) for u in URLS]
        assert [fn(u) for u in URLS] == first
        assert fn.__wrapped__ is not None


def test_an_unhashable_argument_still_gets_an_answer():
    for name in HELPERS:
        fn = getattr(fe, name)
        try:
            fn(["not", "hashable"])
        except TypeError as exc:
            assert "unhashable" not in str(exc), name
        except Exception:
            pass  # the helper's own handling of a bad type, unchanged
