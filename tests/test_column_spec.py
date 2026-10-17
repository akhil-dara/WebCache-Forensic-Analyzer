import pytest

from webcache.widgets.column_spec import KINDS, Column


def test_label_defaults_to_key():
    assert Column("CleanUrl").label == "CleanUrl"
    assert Column("CleanUrl", "Address").label == "Address"


#: Explicit numeric expectations for every kind. Computed expectations would be
#: tautological (deriving from the same tuple the implementation uses). Written
#: by hand to catch silent drops or additions to the numeric set, and to force
#: deliberate decisions when KINDS gains members.
_NUMERIC_BY_KIND = {
    "text": False,
    "url": False,
    "num": True,
    "time": False,
    "time_local": False,
    "flag": False,
    "size": True,
    "domain": False,
    "count": True,
    "carved": False,
    "only_carved": False,
    "types": False,
    "path": False,
    # A SHARE, not a quantity. "bar" stays out of the numeric set on
    # purpose: numeric=True would thousands-separate a 0..1 fraction and
    # right-align a cell that carries no text at all -- see
    # widgets/bar_delegate.py, which paints the value and clears the text.
    "bar": False,
    # A byte position -- numeric for sort and filter exactly like "num",
    # just displayed as hex (see column_spec.KINDS's own "offset" comment
    # and record_model._format's kind="offset" branch).
    "offset": True,
}


@pytest.mark.parametrize("kind,expected_numeric", _NUMERIC_BY_KIND.items())
def test_numeric_by_kind(kind, expected_numeric):
    """Every kind has an explicit, pinned numeric expectation.

    Widened from the original ui_grid.py:78 (kind == "num" only) to include
    "count" and "size" as numeric quantities that must sort and align as
    numbers. This test pins that deliberate choice, and forces an edit to
    _NUMERIC_BY_KIND when KINDS gains a member.
    """
    assert Column("X", kind=kind).numeric is expected_numeric


def test_numeric_table_covers_all_kinds():
    """Ensure the numeric table wasn't left behind when KINDS changed.

    If this fails, _NUMERIC_BY_KIND needs an entry for every new kind.
    """
    assert set(_NUMERIC_BY_KIND.keys()) == set(KINDS)


def test_on_click_is_carried():
    """Every drill-through in the application is this callback.

    An earlier design draft dropped it, which would have turned every summary
    grid back into a dead end -- a bug already fixed once in this codebase.
    """
    seen = []
    c = Column("Domain", on_click=seen.append)
    assert c.is_link is True
    c.on_click({"Domain": "msn.com"})
    assert seen == [{"Domain": "msn.com"}]


def test_column_without_on_click_is_not_a_link():
    assert Column("Domain").is_link is False


def test_on_click_copies_defaults_to_false():
    """Every EXISTING on_click in this application drills
    somewhere ("follows" the value) -- Domain to Domains, a container
    name to its table. A column that never says otherwise must keep
    reading as one of those, so record_model's tooltip hint stays
    unchanged for all of them."""
    assert Column("Domain", on_click=lambda row: None).on_click_copies is False


def test_on_click_copies_can_be_declared():
    """Location's MapsUrl/OsmUrl columns COPY on activation rather than
    opening anything (this project's "Copy, never Open" rule) -- a column
    has to be able to say that plainly, so record_model's tooltip can
    stop promising a follow it will never do."""
    c = Column("MapsUrl", on_click=lambda row: None, on_click_copies=True)
    assert c.is_link is True
    assert c.on_click_copies is True


def test_field_drives_the_basis_badge():
    assert Column("AccessedUtc", field="AccessedUtc").show_badge is True
    assert Column("AccessedUtc").show_badge is False


# --- is_link_for: a link column whose target does not exist for every row -

def test_is_link_for_defaults_to_is_link_for_every_row():
    """Every on_click declared before Timeline's pane pointed at
    something that exists for every row -- a Domain always has a Domains
    view, a container name always names a real container. link_enabled
    is opt-in, and a column that never declares one must keep reading as
    a link on every row, exactly as is_link always has."""
    c = Column("Domain", on_click=lambda row: None)
    assert c.is_link_for({}) is True
    assert c.is_link_for({"Domain": None}) is True


def test_is_link_for_is_false_with_no_on_click_regardless_of_link_enabled():
    c = Column("Domain", link_enabled=lambda row: True)
    assert c.is_link is False
    assert c.is_link_for({}) is False


def test_link_enabled_disables_the_link_per_row():
    """A carved row can have ContainerName "" and ContainerId None -- a
    bare string carve reconstructs no columns at all. link_enabled lets
    a column say, per row, that this particular cell has no target: no
    pointing-hand cursor, no "follow this value" tooltip, and
    activate_cell must not call on_click for it."""
    c = Column("ContainerName", on_click=lambda row: None,
              link_enabled=lambda row: row.get("ContainerId") is not None)
    assert c.is_link_for({"ContainerId": 3}) is True
    assert c.is_link_for({"ContainerId": None}) is False
    assert c.is_link_for({}) is False


def test_unknown_kind_is_rejected():
    with pytest.raises(ValueError, match="unknown column kind"):
        Column("X", kind="wobble")


@pytest.mark.parametrize("kind", KINDS)
def test_every_declared_kind_is_constructible(kind):
    assert Column("X", kind=kind).kind == kind
