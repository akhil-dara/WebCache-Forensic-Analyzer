"""Opening evidence: the file chosen, the files that belong to it, and the
one question.

The examiner picks one file, the database. Beside it Windows keeps that
database's transaction logs and checkpoint (evidence_scope() finds them by
name, reading nothing): they are part of the same database, and they can
hold records the database file itself no longer does, which is why
recovery reads them. The dialog names the folder once and lists each file
by name with WHAT IT IS, ticked, so the examiner sees why it is there and
can leave any of them out. The database itself is always read.

The choice binds. Only ticked files are hashed (EvidenceSet.hashes), the
parser takes its hashes from that set rather than re-reading the folder,
and recovery reads only the logs and checkpoint whose names are in it (see
RecoveryEngine.carve_transaction_logs) -- an unticked file is never read,
and the recovery log names it as not chosen.

A row is not selectable: a click anywhere on it toggles its box, so a
click never leaves a selection tint that means nothing. Right-click copies
the path; the tool never opens a path from the evidence.

Then the one question: whether to recover deleted records as well. The box
is ticked by default and the answer is never remembered.

Cancel (the button, Escape, the close control -- all through reject())
asks the worker to stop; a result racing in afterwards is discarded,
never applied. The worker is never parented to this dialog, so a caller
may destroy the dialog the moment it is rejected (see consent.py).
"""
import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QColor, QGuiApplication
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog,
                               QDialogButtonBox, QFrame, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem, QProgressBar,
                               QPushButton, QScrollArea, QSizePolicy,
                               QVBoxLayout, QWidget)

from ..engine.ese_parser import evidence_scope, log_prefix
from ..widgets import copyable
from . import glyphs, theme
from .consent import _RUNNING_WORKERS, HashWorker

#: The one question, word for word.
RECOVER_LABEL = ("Also recover deleted records (carve the transaction logs "
                 "and free pages)")

#: What opening does. A statement, not a request for authority.
OPEN_TEXT = (
    "The transaction logs and checkpoint beside the database are part of "
    "it, and can hold records the database file no longer does. Each "
    "ticked file is read in full and hashed (SHA-256) so the evidence set "
    "can be verified later. Nothing is written to the evidence folder.")

#: Said when no transaction log sits beside the database: what the
#: examiner loses, and what to collect instead.
NO_LOGS_NOTE = (
    "No transaction log is beside this database. Records Windows had not "
    "yet written into the database file exist only in its logs (V01.log "
    "and V01*.log), so they are not read.")

#: Said under the list while every file is ticked, and when some are not.
ALL_CHOSEN_NOTE = ("Untick a file to leave it out: it is then neither read "
                   "nor hashed.")
SOME_LEFT_OUT_NOTE = ("Unticked files are not read or hashed, and recovery "
                      "will not see records held only in them.")

_DATABASE_EXTENSIONS = (".dat",)


def role_of(path, db_path):
    """What one file in the scope IS, in the examiner's words."""
    name = os.path.basename(path)
    if os.path.normcase(os.path.abspath(path)) == os.path.normcase(
            os.path.abspath(db_path)):
        return "The database you chose — always read"
    fl = name.lower()
    if fl == "%s.log" % log_prefix(db_path).lower():
        return "Transaction log, current — recovery reads it"
    if fl.endswith(".log") and "tmp" in fl:
        return "Transaction log, temporary — recovery reads it"
    if fl.endswith(".log"):
        return "Transaction log, earlier generation — recovery reads it"
    if fl.endswith(".chk"):
        return "Checkpoint — tells recovery which logs hold unsaved changes"
    if fl.endswith(".jrs"):
        return "Reserved log space — hashed only, not parsed"
    if fl.endswith(".jfm"):
        return "Flush map — hashed only, not parsed"
    return "Read alongside the database"


def _format_size(num_bytes):
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return ("%d %s" % (size, unit)) if unit == "B" else ("%.1f %s" % (size, unit))
        size /= 1024
    return "%.1f GB" % size


def _size_of(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


class _FileRow(QFrame):
    """One file: its tick box, its name, what it is, its size. A click
    anywhere on the row toggles the box (the database's box is fixed on).
    Painted over a QListWidgetItem whose own text stays the full path,
    which Copy path and the tests read."""

    def __init__(self, path, db_path=None, parent=None):
        super().__init__(parent)
        self.setObjectName("scopeRow")
        self.path = path
        is_db = (db_path is not None and role_of(path, db_path)
                 .startswith("The database")) or (
            db_path is None and os.path.splitext(path)[1].lower()
            in _DATABASE_EXTENSIONS)
        self.box = QCheckBox()
        self.box.setChecked(True)
        self.box.setEnabled(not is_db)
        icon = QLabel()
        icon.setProperty(copyable.DECORATIVE, True)
        icon.setPixmap(glyphs.pixmap(
            "database" if is_db else "file",
            theme.color("primary" if is_db else "muted"), 14))
        self.name_label = QLabel(os.path.basename(path))
        self.name_label.setProperty(copyable.DECORATIVE, True)
        copyable.plain(self.name_label)
        self.name_label.setToolTip(copyable.literal_tooltip(path))
        self.name_label.setStyleSheet(
            "font-family: 'Cascadia Mono', Consolas, monospace; "
            "font-size: 12px; background: transparent;")
        self.role_label = QLabel(role_of(path, db_path or path))
        self.role_label.setProperty(copyable.DECORATIVE, True)
        copyable.plain(self.role_label)
        self.role_label.setStyleSheet(
            "font-size: 11px; background: transparent; color: %s;"
            % theme.color("muted").name())
        self.size_label = QLabel(_format_size(_size_of(path)))
        self.size_label.setProperty(copyable.DECORATIVE, True)
        copyable.plain(self.size_label)
        self.size_label.setStyleSheet(
            "font-family: 'Cascadia Mono', Consolas, monospace; "
            "font-size: 10.5px; background: transparent; color: %s;"
            % theme.color("muted").name())

        text = QVBoxLayout()
        text.setSpacing(1)
        text.addWidget(self.name_label)
        text.addWidget(self.role_label)
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 6, 12, 6)
        row.setSpacing(10)
        row.addWidget(self.box)
        row.addWidget(icon)
        row.addLayout(text, 1)
        row.addWidget(self.size_label)

        copy_action = QAction("Copy path", self)
        copy_action.triggered.connect(
            lambda: QGuiApplication.clipboard().setText(self.path))
        self.addAction(copy_action)
        self.setContextMenuPolicy(Qt.ActionsContextMenu)
        if self.box.isEnabled():
            self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.box.isEnabled():
            self.box.toggle()
            event.accept()
            return
        super().mousePressEvent(event)


class OpenEvidenceDialog(QDialog):
    hashingFinished = Signal()
    hashingProgress = Signal(int, int)

    def __init__(self, db_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Open evidence")
        self.db_path = db_path
        self.evidence_set = None
        self._worker = None
        self._cancelled = False

        # Stats, never opens -- discovering the problem reads nothing.
        if os.path.isdir(db_path):
            self.candidates = []
            self._problem = ("This evidence is not readable: %s is a "
                             "directory, not a file" % db_path)
        elif not os.path.isfile(db_path):
            self.candidates = []
            self._problem = ("This evidence is not readable: %s does not "
                             "exist" % db_path)
        else:
            self.candidates = evidence_scope(db_path)
            self._problem = ""

        self.list = QListWidget()
        self.list.setObjectName("scopeList")
        self.list.setFrameShape(QFrame.NoFrame)
        # Rows are toggled, never selected: no tint that means nothing.
        self.list.setSelectionMode(QAbstractItemView.NoSelection)
        self.list.setFocusPolicy(Qt.NoFocus)
        # A path is never cut with an ellipsis.
        self.list.setTextElideMode(Qt.ElideNone)
        self.rows = []
        for p in self.candidates:
            item = QListWidgetItem(p)
            item.setForeground(QColor(0, 0, 0, 0))
            item.setFlags(Qt.ItemIsEnabled)
            self.list.addItem(item)
            row = _FileRow(p, db_path)
            row.box.toggled.connect(self._scope_changed)
            item.setSizeHint(row.sizeHint())
            self.list.setItemWidget(item, row)
            self.rows.append(row)
        copy_action = QAction("Copy path", self.list)
        copy_action.triggered.connect(self._copy_selected_path)
        self.list.addAction(copy_action)
        self.list.setContextMenuPolicy(Qt.ActionsContextMenu)

        # One scroller: the list is exactly as tall as its rows and never
        # scrolls itself; the area around it shows up to eight rows and
        # scrolls past that, so no scrollbar appears beside a list that
        # fits.
        self.list.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        frame = 2 * self.list.frameWidth()
        heights = [self.list.sizeHintForRow(i) for i in range(self.list.count())]
        spacing = 2 * self.list.spacing() * len(heights)
        self.list.setFixedHeight(sum(heights) + spacing + frame + 8)
        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(0, 0, 0, 0)
        inner_layout.addWidget(self.list)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidget(inner)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        shown = heights[:8]
        self.scroll_area.setFixedHeight(
            sum(shown) + 2 * self.list.spacing() * len(shown) + frame + 8)
        self.scroll_area.setFrameShape(QFrame.NoFrame)

        self.recover_box = QCheckBox(RECOVER_LABEL)
        self.recover_box.setChecked(True)
        self.recover_box.setEnabled(not self._problem)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self._progress_label = copyable.selectable(QLabel())
        self._progress_label.setVisible(False)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.ok_button = buttons.button(QDialogButtonBox.Ok)
        self.ok_button.setText("Open")
        theme.mark_accent(self.ok_button)
        self.ok_button.setEnabled(not self._problem)

        name = copyable.selectable(QLabel(os.path.basename(db_path) or db_path))
        name.setStyleSheet("font-size: 14px; font-weight: 600;")
        self.folder_label = copyable.selectable(QLabel(
            "in " + os.path.dirname(os.path.abspath(db_path))))
        self.folder_label.setWordWrap(True)
        self.folder_label.setStyleSheet(
            "font-family: 'Cascadia Mono', Consolas, monospace; "
            "font-size: 11px; color: %s;" % theme.color("muted").name())
        intro = copyable.selectable(QLabel(self.intro_text()))
        intro.setWordWrap(True)
        intro.setStyleSheet("color: %s;" % theme.color("muted").name())

        self.summary_label = copyable.selectable(QLabel(""))
        self.summary_label.setStyleSheet("font-weight: 600;")
        self.all_button = QPushButton("Select all")
        self.none_button = QPushButton("Database only")
        self.all_button.clicked.connect(lambda: self._set_all(True))
        self.none_button.clicked.connect(lambda: self._set_all(False))
        for b in (self.all_button, self.none_button):
            b.setEnabled(not self._problem and len(self.rows) > 1)
        picks = QHBoxLayout()
        picks.addWidget(self.summary_label, 1)
        picks.addWidget(self.all_button)
        picks.addWidget(self.none_button)

        # The most consequential gap in a collection, stated before the
        # evidence is opened rather than discovered in the parse log.
        self.no_logs_label = copyable.selectable(QLabel(NO_LOGS_NOTE))
        self.no_logs_label.setWordWrap(True)
        self.no_logs_label.setStyleSheet("color: %s;"
                                         % theme.color("warn").name())
        self.no_logs_label.setHidden(bool(self._problem) or any(
            str(p).lower().endswith(".log") for p in self.candidates))
        self.scope_note = copyable.selectable(QLabel(ALL_CHOSEN_NOTE))
        self.scope_note.setWordWrap(True)
        self.scope_note.setStyleSheet("font-size: 11px; color: %s;"
                                      % theme.color("muted2").name())
        note = copyable.selectable(QLabel(
            "These paths belong to the examined machine and are never "
            "opened here. Right-click a file to copy its path."))
        note.setWordWrap(True)
        note.setStyleSheet("font-size: 11px; color: %s;"
                           % theme.color("muted2").name())

        footer = QHBoxLayout()
        progress_col = QVBoxLayout()
        progress_col.addWidget(self._progress_label)
        progress_col.addWidget(self.progress)
        footer.addLayout(progress_col, 1)
        footer.addWidget(buttons)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(10)
        title = QVBoxLayout()
        title.setSpacing(2)
        title.addWidget(name)
        title.addWidget(self.folder_label)
        root.addLayout(title)
        root.addWidget(intro)
        root.addLayout(picks)
        root.addWidget(self.scroll_area)
        root.addWidget(self.no_logs_label)
        root.addWidget(self.scope_note)
        root.addWidget(note)
        # OUTSIDE scroll_area: the one question must never scroll away.
        root.addWidget(self.recover_box)
        root.addLayout(footer)
        self.setMinimumWidth(620)

        buttons.accepted.connect(self._start_hashing)
        buttons.rejected.connect(self.reject)
        self._scope_changed()

    # --- the answer ---------------------------------------------------------

    @property
    def files(self):
        """The files that will be read and hashed: the ticked ones, in
        scope order. The database is always among them."""
        return [row.path for row in self.rows if row.box.isChecked()]

    @property
    def recover_deleted(self):
        return self.recover_box.isChecked()

    def intro_text(self):
        return self._problem or OPEN_TEXT

    def path_actions(self):
        return self.list.actions()

    def _set_all(self, on):
        for row in self.rows:
            if row.box.isEnabled():
                row.box.setChecked(on)

    def _scope_changed(self, _checked=None):
        chosen = self.files
        size = sum(_size_of(p) for p in chosen)
        self.summary_label.setText(
            "%d of %d files · %s (%s B) will be read and hashed"
            % (len(chosen), len(self.rows), _format_size(size),
               format(size, ",")) if self.rows else "")
        self.scope_note.setText(SOME_LEFT_OUT_NOTE
                                if len(chosen) < len(self.rows)
                                else ALL_CHOSEN_NOTE)

    # --- cancel / hash ------------------------------------------------------

    def reject(self):
        self._cancelled = True
        if self._worker is not None and self._worker.isRunning():
            self._worker.requestInterruption()
        super().reject()

    def _copy_selected_path(self):
        item = self.list.currentItem()
        if item:
            QGuiApplication.clipboard().setText(item.text())

    def _start_hashing(self):
        if self._problem:
            return
        self._hashing_files = self.files
        self.ok_button.setEnabled(False)
        self.recover_box.setEnabled(False)
        for widget in [self.all_button, self.none_button] + [r.box for r in self.rows]:
            widget.setEnabled(False)
        self.progress.setVisible(True)
        self._progress_label.setVisible(True)
        self.progress.setRange(0, len(self._hashing_files) or 1)
        worker = HashWorker(self._hashing_files)
        self._worker = worker
        _RUNNING_WORKERS.add(worker)
        worker.progress.connect(self._on_progress)
        worker.bytesProgress.connect(self._on_bytes)
        worker.done.connect(self._hashed)
        worker.failed.connect(self._hash_failed)
        worker.finished.connect(lambda: _RUNNING_WORKERS.discard(worker))
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _on_progress(self, current, total):
        if self._cancelled:
            return
        self.progress.setRange(0, total or 1)
        self.progress.setValue(current)
        files = getattr(self, "_hashing_files", self.files)
        name = (os.path.basename(files[current])
                if current < len(files) else "")
        self._progress_label.setText(
            "Hashing %d of %d%s" % (current, total,
                                    (" — %s" % name) if name else ""))
        self.hashingProgress.emit(current, total)

    def _on_bytes(self, done, total):
        """"Hashing… 12 MB of 136 MB", beside the
        disabled Open button, for as long as hashing runs."""
        if self._cancelled:
            return
        mb = float(1 << 20)
        self._progress_label.setText(
            "Hashing… %s MB of %s MB" % (
                format(int(done / mb), ","), format(int(round(total / mb)), ",")))

    def _hash_failed(self, reason):
        """Say why, and give the dialog back: nothing was opened."""
        if self._cancelled:
            return
        self.progress.setVisible(False)
        self._progress_label.setText(reason)
        self._progress_label.setWordWrap(True)
        self._progress_label.setStyleSheet(
            "color: %s;" % theme.color("warn").name())
        self._progress_label.setVisible(True)
        self.ok_button.setEnabled(True)
        self.recover_box.setEnabled(True)
        for widget in ([self.all_button, self.none_button]
                       + [r.box for r in self.rows]):
            widget.setEnabled(True)

    def _hashed(self, evidence):
        if self._cancelled:
            return
        self.evidence_set = evidence
        self.progress.setVisible(False)
        self._progress_label.setVisible(False)
        self.hashingFinished.emit()
        self.accept()
