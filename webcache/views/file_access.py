"""File Access: local files opened through the browser stack, and the
downloads the iedownload container recorded, as two segments.

At open the rows are live records. Recovered records are normalised by the
engine like live ones, so after Evidence > Recover deleted records the
recovered file-access and download records are merged into both segments
and the count line gives the live and recovered split.

Paths use the "path" column kind: never styled as links, copied, never
opened.
"""
from ..widgets.column_spec import Column
from .record_chips import (copies_hidden_note, hide_copies_chip,
                           one_row_per_visit_chip, twins_hidden_note)
from .records_view import RecordSet, RecordsView

#: File-access records: local files opened through the browser stack,
#: selected by IsLocalFile rather than by container type.
FILE_ACCESS_COLUMNS = [
    # Graded per row: an MSHist row's UTC is derived from the local time
    # its container stores, and its cell says so.
    Column("ModifiedTime", "Modified (UTC)", 165, kind="time",
          field="ModifiedTime", basis_key="ModifiedTimeBasis"),
    Column("AccessedLocal", "Last visit (LOCAL)", 165, kind="time_local",
          field="AccessedLocal",
          note=("Last visit (LOCAL) is SPS id 24 (the property store's "
                "last visit, on the machine's LOCAL clock) when the record "
                "has one, else an MSHist record's stored ModifiedTime, "
                "which that container keeps on the LOCAL clock. It is the "
                "visit's local time -- not Modified (UTC) shifted to "
                "local.")),
    Column("VisitCount", "Opens (property store)", 90, kind="num",
           field="SPS_VisitCount"),
    Column("CleanUrl", "Local file path (as stored)", 380, kind="path",
          field="CleanUrl"),
    # The stored file: URL decoded, beside the stored value.
    Column("LocalPath", "Local file path (decoded)", 380, kind="path",
          field="LocalPath"),
    # Read from the decoded path, so drives and document types can be
    # filtered directly.
    Column("Drive", "Drive", 90, kind="text", field="Drive"),
    Column("FileType", "File type", 90, kind="text", field="FileType"),
    # The other record of the same visit (an MSHist record and its
    # History twin).
    Column("SameVisit", "Same visit as", 220, kind="text"),
    # Repeated carves of one record; blank on a live row and on a unique
    # carve.
    Column("Copies", "Copies", 100, kind="text"),
    # Touches of the cache entry, never opens.
    Column("CacheTouches", "Cache touches", 80, kind="num",
           field="AccessCount"),
    Column("Origin", "Source record", 170, kind="flag", field="Origin"),
    Column("FileSize", "Size", 100, kind="size", field="FileSize"),
    Column("ContainerId", "Container ID", 110, kind="num", field="ContainerId"),
    Column("ContainerName", "Container name", 150, kind="text",
          field="ContainerName"),
    Column("EntryId", "EntryId", 90, kind="num", field="EntryId"),
    Column("AccessedTime", "Accessed (UTC)", 165, kind="time",
          field="AccessedTime"),
    Column("CreationTime", "Created (UTC)", 165, kind="time",
          field="CreationTime"),
    # Where a recovered row came from; optional, blank on a live row.
    Column("Offset", "Offset", 100, kind="offset", field="Offset",
           optional=True),
    Column("Page", "Page", 70, kind="num", field="Page", optional=True),
    Column("Method", "Method", 190, kind="text", field="Method",
           optional=True),
]

#: Downloads: the iedownload container, decoded from the ResponseHeaders
#: blob (evidence_loader.downloads_rows_from_parser).
DOWNLOAD_COLUMNS = [
    Column("DownloadTime", "Downloaded (UTC)", 165, kind="time",
          field="DownloadTime"),
    Column("DownloadPath", "Saved to", 380, kind="path", field="DownloadPath"),
    Column("DownloadSize", "Size", 100, kind="size", field="DownloadSize"),
    Column("DownloadSourceUrl", "Source URL", 380, kind="url",
          field="DownloadSourceUrl"),
    # How much of each download record the decoder recovered (high,
    # medium, low, none, by how many of path, source URL, size and GUID
    # it found). No field: this is not the carve confidence that
    # evidence_model's "Confidence" entry describes, so no basis badge.
    Column("DownloadConfidence", "Confidence", 100, kind="flag"),
]


def _file_access_subtitle(count):
    return ("%s file-access record%s. Opens and the local-clock last-"
           "visit time are decoded from the property store where present."
           % (format(count, ","), "" if count == 1 else "s"))


#: What an empty Downloads list can mean: the database records only the
#: downloads of Internet Explorer's and legacy Edge's download manager.
DOWNLOADS_SCOPE = ("Only downloads made through Internet Explorer's or legacy "
                   "Edge's own download manager are recorded in this "
                   "database; downloads by other browsers, including the "
                   "current Edge, are not.")


def _downloads_subtitle(count):
    if not count:
        return "No download records. " + DOWNLOADS_SCOPE
    return ("%s download%s. Saved path, size and source URL are decoded "
           "from the iedownload record." % (format(count, ","),
                                            "" if count == 1 else "s"))


class FileAccessView(RecordsView):
    def __init__(self, parent=None):
        super().__init__(
            record_sets=[
                RecordSet(
                    "file_access", "File access", FILE_ACCESS_COLUMNS,
                    subtitle=_file_access_subtitle,
                    empty_text=("No file-access records in this exhibit — "
                                "no local file opened through the browser "
                                "was found in the live database."),
                    default_sort=("ModifiedTime", True)),
                RecordSet(
                    "downloads", "Downloads", DOWNLOAD_COLUMNS,
                    subtitle=_downloads_subtitle,
                    empty_text=("No records in Downloads. "
                                + DOWNLOADS_SCOPE + " A downloaded file "
                                "that was later opened appears under File "
                                "access."),
                    default_sort=("DownloadTime", True)),
            ],
            header_icon="folder", header_title="File Access",
            # A file opened through the browser is logged in History and
            # again in an MSHist copy; this chip shows one row per visit.
            quick_filters=[hide_copies_chip(), one_row_per_visit_chip()],
            parent=parent)

    def _update_count(self):
        super()._update_count()
        model = self.table.model()
        if model is None:
            return
        if self.chip_hide_copies.isChecked():
            self.count_label.setText(
                self.count_label.text() + copies_hidden_note(model))
        if self.chip_one_row_per_visit.isChecked():
            self.count_label.setText(
                self.count_label.text() + twins_hidden_note(model))
