"""What kind of thing a row is: one interned constant per answer.

Every row built in this package carries `_kind`, always one of the
constants below.

MEMORY. A row builder may not construct a new string, list or dict per
row (see the budget in tests/test_row_is_a_record.py). A module constant
is provably one object, and `row["_kind"] is K_HISTORY` can be tested.

MEANING. `_kind` tells a consumer which questions a row can answer. A
carved string artifact and a live History record both have a URL and a
timestamp; treating them as the same kind would make a reconstructed
value read like a recorded one. Several values below are not records at
all (see K_DOMAIN and K_INDICATOR), and are named so.

Qt-free and engine-free, so the field catalogue that reads it stays
testable without a QApplication; tests/test_row_is_a_record.py checks
this.
"""

#: A live browsing-history record: ContainerType == "History".
K_HISTORY = "history"

#: A local file opened THROUGH the browser -- IsLocalFile, whatever
#: container it was logged under.
K_FILE_ACCESS = "file_access"

#: An iedownload-container record, decoded from its own blob.
K_DOWNLOAD = "download"

#: A cookie from one of the modern CookieEntryEx_* tables.
K_COOKIE = "cookie"

#: An HSTS pin. It proves a TLS connection, not that a page was viewed --
#: which is precisely why it is its own kind and not folded into history.
K_HSTS = "hsts"

#: A cached TLS certificate from a BlobEntry_* store.
K_CERT = "cert"

#: A row of the Containers registry table -- metadata about a container,
#: not a record inside one.
K_CONTAINER = "container"

#: NOT A RECORD. One row of the Domains view is an aggregate computed
#: across N records; every value on it is a sum, a count or an extremum.
#: A surface that shows one of these must say so before it shows the
#: numbers, or the aggregate reads as a thing that happened once.
K_DOMAIN = "domain"

#: NOT A RECORD, for the same reason: one distinct (kind, value)
#: indicator tallied across every record that carried it.
K_INDICATOR = "indicator"

#: NOT A RECORD. One row of the Timeline is every record that fell in one
#: bucket, counted. Shares K_DOMAIN's failure mode exactly: shown without
#: saying so, a period row reads as one thing that happened -- "2024-06-15,
#: 1,204 records" is a summary of a day, not an event in it.
K_PERIOD = "period"

#: NOT A RECORD. One row of the Location "Places" set is every position
#: fix that falls together at the chosen grouping scale. Same failure
#: mode again, and worse here than anywhere else: shown without saying so,
#: "one place, 14 fixes" reads as a place the device WAS, rather than as
#: fourteen separate claims a device made to a server that happen to round
#: together. Everything that makes a place evidence -- the request URL each
#: fix was read out of, whether that URL was live or carved, the accuracy
#: each one claimed -- lives on the fixes underneath it.
K_PLACE = "place"

#: A whole database row reconstructed out of unallocated space -- carved,
#: with a real ContainerId that resolved to a container type.
K_CARVED_STRUCT = "carved_struct"

#: A bare URL-shaped string pulled out of page slack or a transaction
#: log. It has no ContainerId, no Flags and no columns: it is text that
#: looks like a URL, plus where it was found. Kept distinct from
#: K_CARVED_STRUCT because the two can answer completely different sets
#: of questions, and a consumer that cannot tell them apart will
#: eventually answer one with the other.
K_CARVED_STRING = "carved_string"

#: A b-tree leaf node too short to be a record -- what is left in the
#: table after a row is deleted. It has no columns at all, only the key
#: that named the row: its table and its EntryId (and UrlHash, in the
#: tables keyed on both). See engine/ese_records.py.
K_TOMBSTONE = "tombstone"

#: NOT A PARSED RECORD. One row of a raw ESE table, matched by a
#: cross-table search. It has no EntryId of the kind every other row here
#: carries, no guaranteed container, and NO `_record`: search_all_tables
#: returns raw cells, never a reference back into parser.all_entries (the
#: result dict's keys carry no entry). It therefore cannot be handed to
#: RecordDetailDialog, which renders parsed entries -- see views/search.py
#: on why activating a hit fills the pane below the grid instead.
#:
#: Not an aggregate either: it is ONE row, not a population of records, so
#: "Aggregate over N records" would be as false for it as "Live record" is.
K_TABLE_ROW = "table_row"

#: One container whose EntryId sequence (forensic_engine.analyze_entryid_
#: gaps) has a hole. NOT A RECORD -- it aggregates the LIVE entries this
#: exhibit still holds for that container id; Missing/Recovered describe
#: records that are NOT among them (see views/iocs.py's own docstring).
K_ENTRYID_GAP = "entryid_gap"

#: A period with no recorded activity between two adjacent records
#: (forensic_engine.analyze_time_voids). NEITHER A RECORD NOR AN
#: AGGREGATE OVER ONE -- there is no population of records here to
#: summarise; the whole finding IS the absence of any.
K_TIME_VOID = "time_void"

#: A domain contacted at low-jitter, regular intervals (forensic_engine.
#: detect_beaconing). NOT A RECORD -- it aggregates the live requests to
#: that domain the interval statistics were computed from. This heuristic
#: never sees carved records (detect_beaconing takes no extra_entries),
#: which views/iocs.py states rather than leaving implied.
K_BEACON = "beacon"

#: A hostname analysis_extra.homograph_findings flagged as punycode,
#: non-ASCII or mixed-script. NOT A RECORD -- it aggregates every record
#: (live or carved) whose URL named this host.
K_DECEPTIVE_HOST = "deceptive_host"

#: One hop of a reconstructed redirect chain (analysis_extra.
#: redirect_chains): a URL, and where the redirect INTO it was recorded.
#: NOT A RECORD -- most hops name a URL no live or carved row of this
#: exhibit still holds, and the ones that do are not opened as themselves
#: here (see views/iocs.py's own module docstring for why).
K_REDIRECT_HOP = "redirect_hop"

#: Every declared kind. Iterated by tests and by anything that has to
#: exhaust the set; a kind not in here is not a kind.
ALL = (K_HISTORY, K_FILE_ACCESS, K_DOWNLOAD, K_COOKIE, K_HSTS, K_CERT,
       K_CONTAINER, K_DOMAIN, K_INDICATOR, K_PERIOD, K_PLACE,
       K_CARVED_STRUCT, K_CARVED_STRING, K_TOMBSTONE, K_TABLE_ROW,
       K_ENTRYID_GAP, K_TIME_VOID, K_BEACON, K_DECEPTIVE_HOST,
       K_REDIRECT_HOP)

#: The kinds that are aggregates rather than records. A consumer that
#: renders one of these must state that plainly -- see K_DOMAIN.
AGGREGATES = (K_DOMAIN, K_INDICATOR, K_PERIOD, K_PLACE, K_ENTRYID_GAP,
             K_BEACON, K_DECEPTIVE_HOST)

#: The kinds that came out of a carve rather than out of the live
#: database. record_model.py keys carved styling off the row's Origin,
#: which is unchanged; this is for consumers that have a `_kind` in hand
#: and no Origin to read. K_TOMBSTONE is left out deliberately: a stub is
#: recovered evidence of a deletion (detail_fields treats it as carved for
#: provenance), but nothing was carved -- it is a live b-tree node.
CARVED = (K_CARVED_STRUCT, K_CARVED_STRING)

#: What a row of this kind IS, in one sentence, for the kinds that are
#: neither a record nor a population of records.
#:
#: detail_fields.origin_line describes a record with describe_origin()
#: and an AGGREGATES kind with "Aggregate over N records". Neither is true
#: for a kind in here: the first would assert a live record and the
#: second a population of records, so each kind states what it is.
ORIGIN_SENTENCE = {
    K_TABLE_ROW: ("One row of a raw ESE table in the open database, "
                  "matched by a cross-table search. The Table and Row # "
                  "columns say which."),
    K_TIME_VOID: ("A period with no recorded activity between two "
                  "adjacent records. Not a record, and not an aggregate "
                  "over any -- the machine may have been off, the "
                  "account unused, another browser used, or those "
                  "records removed; this states only that the silence "
                  "exists, not which of those explains it."),
    K_REDIRECT_HOP: ("One hop of a reconstructed redirect chain -- a URL, "
                     "and where the redirect into it was recorded "
                     "(a RedirectUrl column or an HTTP 3xx Location "
                     "header). Most hops name a URL this exhibit's live "
                     "or carved tables no longer hold a row for."),
}


#: What a row of each kind is called in a sentence an examiner reads -- a
#: breadcrumb, never an internal key.
KIND_WORDS = {
    K_HISTORY: "History record",
    K_FILE_ACCESS: "File Access record",
    K_DOWNLOAD: "download record",
    K_COOKIE: "cookie",
    K_HSTS: "HSTS pin",
    K_CERT: "certificate",
    K_CONTAINER: "container",
    K_DOMAIN: "domain",
    K_INDICATOR: "indicator",
    K_PERIOD: "period",
    K_PLACE: "place",
    K_CARVED_STRUCT: "recovered record",
    K_CARVED_STRING: "recovered string",
    K_TOMBSTONE: "deleted-record stub",
    K_TABLE_ROW: "Search hit",
    K_ENTRYID_GAP: "EntryId gap",
    K_TIME_VOID: "time void",
    K_BEACON: "beaconing finding",
    K_DECEPTIVE_HOST: "deceptive host",
    K_REDIRECT_HOP: "redirect hop",
}


def kind_word(kind):
    """KIND_WORDS[kind], or "record" for a kind without one."""
    return KIND_WORDS.get(kind, "record")


def kind_for_entry(entry):
    """Which kind a LIVE engine dict is, decided from the entry itself.

    The single definition of this rule, shared by every consumer
    (detail_fields.row_for_entry, headers_loader.header_rows_from_parser
    and others), so the same record reached two ways renders the same way.
    Qt-free and engine-free: it reads two keys off a plain dict and
    returns one of the constants above.
    """
    entry = entry or {}
    if str(entry.get("ContainerType") or "") == "Downloads":
        return K_DOWNLOAD
    if entry.get("IsLocalFile"):
        return K_FILE_ACCESS
    return K_HISTORY


def kind_for_carved(entry):
    """Which carved kind a recovered dict is.

    The single definition of this rule, shared by the shell loaders. A
    structured carve rebound real columns and so has a ContainerId or a
    Flags value; a string carve is URL-shaped text from page slack or a
    transaction log and has neither, because the record that would have
    carried them is what was destroyed.

    The two answer different questions (see K_CARVED_STRUCT /
    K_CARVED_STRING): a string carve has no Flags column, so it can never
    report "InPrivate: No".
    """
    entry = entry or {}
    if entry.get("ContainerId") is not None or entry.get("Flags") is not None:
        return K_CARVED_STRUCT
    return K_CARVED_STRING
