"""An export's sidecar states how text was matched, so the selection can be
reproduced from the file. A condition "contains tax docs" kept rows whose
stored address reads "Tax%20docs": a reviewer searching the CSV for the
condition's own words would find nothing and doubt the export."""
from webcache.shell import export_formats as F

RULE = "decoded spelling"


def _sidecar(tmp_path, **scope):
    base = {"is_subset": True, "rows_in_file": 1, "rows_in_view": 1,
            "rows_in_record_set": 2}
    base.update(scope)
    path = str(tmp_path / "view.csv")
    open(path, "w").close()
    with open(F.write_view_provenance(path, {}, base, 0), encoding="utf-8-sig") as fh:
        return fh.read()


def test_a_text_condition_states_the_matching_rule(tmp_path):
    text = _sidecar(tmp_path, conditions={"Address": 'contains "tax docs"'})
    assert RULE in text
    assert "values as stored" in text


def test_a_search_text_states_it_too(tmp_path):
    assert RULE in _sidecar(tmp_path, text_filter="tax docs")


def test_a_value_filter_alone_does_not(tmp_path):
    assert RULE not in _sidecar(tmp_path, values={"InPrivate": ["No"]})


def test_no_filter_says_nothing_about_matching(tmp_path):
    assert RULE not in _sidecar(tmp_path, is_subset=False)
