"""What a dropped thing MEANS, decided before anything is opened.

The first-run card has promised "Drag it here" since it was written, and
nothing anywhere in the application accepted a drop -- no setAcceptDrops,
no dropEvent, no rule for what a dropped item even is. This file is the
rule half: given the paths a drag carries, which single exhibit (if any)
is the examiner asking for, and when there is none, what is the honest
reason.

The rule is deliberately separable from the window that uses it, because
the desktop hands over cases the window cannot sensibly decide inline: a
folder (Windows lets you drag one, and a WebCache folder holding a
WebCacheV01.dat is a plausible thing to drag), five files at once, a
screenshot, a dragged URL that is not a file at all.

Two properties matter more than any individual case:

- A refusal never names a path. A verdict either has a path to open and no
  reason, or a reason and no path -- there is no third state for a caller
  to misread as "open this, but".
- Deciding opens nothing. Selection is by NAME here exactly as it is in
  evidence_scope(): a stat and a directory listing, never a read. The
  consent gate is what authorises reading, and it has not been reached
  yet at the point this code runs.
"""
import builtins
import os

import pytest
from PySide6.QtCore import QMimeData, QUrl

from webcache.shell import drop_target


def _mime_for(paths):
    """The mime data a real file drag carries: file:// URLs."""
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(p) for p in paths])
    return mime


@pytest.fixture
def exhibit(tmp_path):
    """A WebCache folder as it exists on an examined machine: the database
    plus the transaction logs evidence_scope() already counts as part of
    the same evidence set."""
    folder = tmp_path / "WebCache"
    folder.mkdir()
    db = folder / "WebCacheV01.dat"
    db.write_bytes(b"\x00" * 64)
    (folder / "V01.log").write_bytes(b"\x00" * 16)
    (folder / "V01.chk").write_bytes(b"\x00" * 16)
    return db


# --- the two properties every verdict has to keep -------------------------

def test_a_verdict_with_a_path_carries_no_reason(exhibit):
    verdict = drop_target.classify([str(exhibit)])

    assert verdict.path
    assert verdict.reason == "", (
        "a verdict that names a path to open must not also carry a "
        "refusal -- a caller cannot act on both")


def test_every_refusal_leaves_the_path_empty(tmp_path, exhibit):
    junk = tmp_path / "screenshot.png"
    junk.write_bytes(b"\x89PNG")
    empty = tmp_path / "Downloads"
    empty.mkdir()
    second = tmp_path / "second.dat"
    second.write_bytes(b"\x00")

    refused = [
        drop_target.classify([]),
        drop_target.classify([str(junk)]),
        drop_target.classify([str(empty)]),
        drop_target.classify([str(exhibit), str(second)]),
        drop_target.classify([str(exhibit), str(junk)]),
    ]

    for verdict in refused:
        assert verdict.path == "", (
            "a refused drop must name nothing to open: %r" % (verdict,))
        assert verdict.reason, "a refusal that says nothing is not a refusal"


def test_classifying_a_drop_reads_no_file(monkeypatch, exhibit, tmp_path):
    """Selection by name, never by content -- the same discipline
    evidence_scope() keeps, for the same reason: the consent gate has not
    been reached yet, so nothing here is authorised to read a byte."""
    real_open = builtins.open

    def _no_reads(path, *args, **kwargs):
        if str(path).startswith(str(tmp_path)):
            raise AssertionError("classify() opened %s" % (path,))
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", _no_reads)

    assert drop_target.classify([str(exhibit)]).path
    assert drop_target.classify([str(exhibit.parent)]).path
    assert drop_target.classify([str(tmp_path)]).reason


# --- one file -------------------------------------------------------------

def test_a_dropped_database_is_the_exhibit_to_open(exhibit):
    verdict = drop_target.classify([str(exhibit)])

    assert verdict.path == str(exhibit)


def test_an_exhibit_copy_under_another_name_is_still_a_database(tmp_path):
    """Selection is by extension, not by the literal WebCacheV01.dat name:
    a working copy of an exhibit is routinely renamed for the case, and
    the Open Database button's own "All files" filter already accepts
    one."""
    renamed = tmp_path / "case-2026-08-14.dat"
    renamed.write_bytes(b"\x00")

    assert drop_target.classify([str(renamed)]).path == str(renamed)


def test_a_screenshot_is_refused_and_the_reason_names_it(tmp_path):
    """Refused HERE rather than handed to the parser to fail obscurely --
    "not a database" is a fact about the drop, and the examiner should be
    told it in those words, not shown a parse error."""
    junk = tmp_path / "screenshot.png"
    junk.write_bytes(b"\x89PNG")

    verdict = drop_target.classify([str(junk)])

    assert verdict.path == ""
    assert "screenshot.png" in verdict.reason


def test_a_text_file_is_refused_too(tmp_path):
    notes = tmp_path / "case-notes.txt"
    notes.write_text("notes", encoding="utf-8")

    assert drop_target.classify([str(notes)]).path == ""


# --- a folder -------------------------------------------------------------

def test_a_dropped_webcache_folder_resolves_to_the_database_inside_it(exhibit):
    """The plausible desktop drop: Windows lets a folder be dragged, and
    the folder an examiner has in front of them is the WebCache folder
    itself."""
    verdict = drop_target.classify([str(exhibit.parent)])

    assert verdict.path == str(exhibit)


def test_the_database_inside_a_folder_is_found_whatever_its_case(tmp_path):
    folder = tmp_path / "webcache"
    folder.mkdir()
    db = folder / "webcachev01.DAT"
    db.write_bytes(b"\x00")

    assert drop_target.classify([str(folder)]).path == str(db)


def test_a_folder_with_no_database_is_refused_by_name(tmp_path):
    folder = tmp_path / "Downloads"
    folder.mkdir()
    (folder / "screenshot.png").write_bytes(b"\x89PNG")

    verdict = drop_target.classify([str(folder)])

    assert verdict.path == ""
    assert "Downloads" in verdict.reason


def test_a_folder_is_resolved_one_level_only(tmp_path):
    """Deliberately NOT a recursive walk. A dropped folder can be
    anything -- a whole disk image mount, a user profile -- and walking it
    would be unbounded work at drag time and, worse, could pick one
    WebCacheV01.dat out of several without the examiner ever naming it.
    Direct children only, and the refusal says so."""
    outer = tmp_path / "case"
    inner = outer / "profile" / "WebCache"
    inner.mkdir(parents=True)
    (inner / "WebCacheV01.dat").write_bytes(b"\x00")

    assert drop_target.classify([str(outer)]).path == ""


# --- several at once ------------------------------------------------------

def test_five_databases_at_once_open_none_of_them(tmp_path):
    """The failure this rule exists to prevent is not "nothing happens" --
    it is silently opening the first of five and letting the examiner
    believe they opened a different one."""
    dropped = []
    for n in range(5):
        folder = tmp_path / ("case%d" % n)
        folder.mkdir()
        db = folder / "WebCacheV01.dat"
        db.write_bytes(b"\x00")
        dropped.append(str(db))

    verdict = drop_target.classify(dropped)

    assert verdict.path == ""
    assert "5" in verdict.reason, (
        "the examiner has to be told how many were dropped, or the "
        "refusal reads as a malfunction")


def test_a_database_dropped_with_its_own_logs_is_one_exhibit(exhibit):
    """Select-all inside a WebCache folder is one exhibit, not four: the
    logs are already inside evidence_scope(), so consent would have listed
    them anyway."""
    folder = exhibit.parent
    dropped = [str(exhibit), str(folder / "V01.log"), str(folder / "V01.chk")]

    assert drop_target.classify(dropped).path == str(exhibit)


def test_a_database_dropped_with_an_unrelated_file_is_refused(exhibit, tmp_path):
    """Not the same as the logs above: a file that is NOT in this
    exhibit's scope means the examiner selected something this drop cannot
    account for, and guessing which half they meant is exactly the silent
    wrong answer."""
    stray = tmp_path / "screenshot.png"
    stray.write_bytes(b"\x89PNG")

    verdict = drop_target.classify([str(exhibit), str(stray)])

    assert verdict.path == ""
    assert "WebCacheV01.dat" in verdict.reason


def test_the_same_database_dropped_twice_is_still_one_exhibit(exhibit):
    """A folder and the database inside it name the SAME exhibit -- that
    is one choice, not an ambiguous two."""
    dropped = [str(exhibit.parent), str(exhibit)]

    assert drop_target.classify(dropped).path == str(exhibit)


def test_several_items_none_of_them_a_database_is_refused(tmp_path):
    junk = []
    for name in ("a.png", "b.txt", "c.zip"):
        p = tmp_path / name
        p.write_bytes(b"x")
        junk.append(str(p))

    verdict = drop_target.classify(junk)

    assert verdict.path == ""
    assert verdict.reason


# --- what a drag actually carries ----------------------------------------

def test_local_paths_reads_the_file_urls_a_real_drag_carries(exhibit):
    paths = drop_target.local_paths(_mime_for([str(exhibit)]))

    assert paths == [str(exhibit)]


def test_local_paths_normalises_the_separators_qurl_hands_back(tmp_path):
    """QUrl.toLocalFile() returns forward slashes even on Windows, so an
    un-normalised path would never compare equal to one QFileDialog
    produced -- and the evidence-scope membership check below depends on
    those comparisons."""
    db = tmp_path / "WebCacheV01.dat"
    db.write_bytes(b"\x00")

    (path,) = drop_target.local_paths(_mime_for([str(db)]))

    assert path == os.path.normpath(str(db))
    assert os.path.isfile(path)


def test_dragged_text_carries_no_paths_at_all():
    """Dragging a selection out of another application is not a file
    drop. It must read as "nothing was dropped", never as a path."""
    mime = QMimeData()
    mime.setText("C:\\Users\\subject\\WebCache\\WebCacheV01.dat")

    assert drop_target.local_paths(mime) == []


def test_a_dragged_web_url_carries_no_paths():
    mime = QMimeData()
    mime.setUrls([QUrl("https://example.invalid/WebCacheV01.dat")])

    assert drop_target.local_paths(mime) == []


def test_an_empty_drag_is_refused_rather_than_opened():
    assert drop_target.classify([]).path == ""
    assert drop_target.classify([]).reason
