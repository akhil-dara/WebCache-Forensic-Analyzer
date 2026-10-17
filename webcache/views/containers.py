"""Containers: every container the Containers table registers.

WinINet partitions the cache into containers (History, Content, Cookies,
iedownload and others), each with its own Container_<id> table. This view
shows their metadata: size, partition, cache directory, last access and
last scavenge.

Records is "Not determinable", not 0, for a registered container whose
table no longer exists. The cache directory is a path on the examined
machine and is copied, never opened. Clicking a container's name opens its
table in Table Browser.
"""
from ..widgets.column_spec import Column
from .records_view import RecordSet, RecordsView


def _containers_subtitle(count):
    return ("%s container%s. Metadata as the Containers table itself "
           "records it, including a container whose own Container_<id> "
           "table is no longer present."
           % (format(count, ","), "" if count == 1 else "s"))


class ContainersView(RecordsView):
    COUNT_NOUN = "containers"  # rows are containers, not records

    def __init__(self, parent=None):
        columns = [
            Column("Id", "ID", 60, kind="num", field="ContainerId"),
            Column("Name", "Name", 200, kind="text", field="ContainerName",
                  on_click=lambda row: self.drillRequested.emit("browser", row)),
            Column("Type", "Type", 120, kind="text", field="ContainerType"),
            Column("Records", "Records", 90, kind="num"),
            Column("Size", "Size", 90, kind="size"),
            Column("Partition", "Partition", 300, kind="text"),
            Column("Directory", "Cache directory", 320, kind="path"),
            Column("LastAccess", "Last access (UTC)", 165, kind="time",
                  field="AccessedTime"),
            Column("LastScavenge", "Last scavenge (UTC)", 165, kind="time"),
        ]
        super().__init__(
            record_sets=[RecordSet(
                "containers", "Containers", columns,
                subtitle=_containers_subtitle,
                empty_text=("No containers in this exhibit — the "
                            "Containers table itself held no entries "
                            "when the database was parsed."))],
            header_icon="database", header_title="Containers",
            parent=parent)
