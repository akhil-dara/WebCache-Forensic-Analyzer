"""
Recovery Engine — the capability no polished GUI ships.

Two recovery sources, both read-only:

1. ESE transaction logs (V01.log, V01#####.log) — WebCacheV01.dat flushes
   mainly on clean shutdown, so on a crashed/seized/long-running system the
   newest history lives in the logs, not the .dat. Records deleted from the
   database (including InPrivate, in a window) also survive here.

2. Unallocated space inside the .dat itself — ESE only flags deleted-record
   space as reusable; bytes persist until the page is rewritten. Page slack
   (bytes not covered by any live node) and empty/deallocated pages hold
   deleted records, often complete with URL + FILETIMEs.

Every recovered artifact carries provenance (source file, byte offset,
region kind) and a confidence grade — recovery is probabilistic and must be
presented as such in reports.

Empirically validated against a real dirty-state sample (2026-02):
log carving recovered 76 URLs absent from the live DB; page-slack carving
recovered 403, including entire deleted MSHist daily containers.
"""

import os
import re
import struct
from datetime import datetime, timedelta, timezone
from typing import Optional

# One formatter, shared with the live path, so a carved timestamp is shown
# to the same precision as a live one.
from .ese_parser import log_prefix, stamp_str

FILETIME_EPOCH = datetime(1601, 1, 1, tzinfo=timezone.utc)

#: The RecoverySource ("Method") each carving technique writes.
STRUCTURED_METHOD = "Structured record reconstruction"
UNALLOCATED_METHOD = "DB unallocated space"
LOG_METHOD = "Transaction log"
METHOD_LABELS = (STRUCTURED_METHOD, UNALLOCATED_METHOD, LOG_METHOD)

# FILETIME plausibility window used when scanning context bytes.
# Lower bound 2010-01-01; upper bound = analysis time + 90 days, so that
# far-future *expiry* FILETIMEs sitting near a URL are not mistaken for
# visit-time context hints.
FT_MIN = 129_067_776_000_000_000
FT_MAX = int((datetime.now(timezone.utc) + timedelta(days=90)
              - FILETIME_EPOCH).total_seconds() * 10_000_000)

# UTF-16LE printable run (>= 6 chars) — WebCache URL strings are UTF-16LE
_PAT_UTF16 = re.compile(rb"(?:[\x20-\x7e]\x00){6,}")
# ASCII printable run (>= 8 chars) — fallback for raw HTTP header remnants
_PAT_ASCII = re.compile(rb"[\x20-\x7e]{8,}")

# What counts as a forensically interesting carved string
_PAT_INTERESTING = re.compile(
    r"(Visited:|https?://|ftp://|file:///|ms-appx|:20\d{6}\d*:)", re.I)


def filetime_to_dt(ft: Optional[int]) -> Optional[datetime]:
    if not ft or ft <= 0 or ft > 2650467743990000000:
        return None
    try:
        return FILETIME_EPOCH + timedelta(microseconds=ft // 10)
    except (OverflowError, ValueError):
        return None


def _ese_logtime(b: bytes) -> Optional[datetime]:
    """ESE LOGTIME: [sec min hour day month year-1900 ...] (8 bytes)."""
    if len(b) < 8:
        return None
    s, m, h, d, mo, y = b[0], b[1], b[2], b[3], b[4], b[5]
    if not (1 <= mo <= 12 and 1 <= d <= 31 and h < 24 and m < 60 and s < 60):
        return None
    try:
        return datetime(1900 + y, mo, d, h, m, s)
    except ValueError:
        return None


def _nearest_filetime(data: bytes, pos: int, window: int = 256) -> Optional[int]:
    """Scan up to `window` bytes before `pos` for the closest plausible FILETIME."""
    lo = max(0, pos - window)
    ctx = data[lo:pos]
    for i in range(len(ctx) - 8, -1, -1):
        v = struct.unpack_from("<Q", ctx, i)[0]
        if FT_MIN <= v <= FT_MAX:
            return v
    return None


def _carve_strings(data: bytes, base_offset: int, live_urls: set,
                   source: str, region: str, seen: set) -> list:
    """Carve URL-like strings from a byte region; returns recovered-artifact dicts."""
    out = []
    for pat, enc in ((_PAT_UTF16, "utf-16-le"), (_PAT_ASCII, "ascii")):
        for m in pat.finditer(data):
            try:
                text = m.group().decode(enc).strip("\x00").strip()
            except UnicodeDecodeError:
                continue
            if not _PAT_INTERESTING.search(text):
                continue
            if enc == "ascii" and text.lower().startswith(("http/", "accept", "content-",
                                                           "cache-", "user-agent")):
                continue  # HTTP header noise, not a URL artifact
            key = text
            if key in live_urls or key in seen:
                continue
            seen.add(key)
            ft = _nearest_filetime(data, m.start())
            out.append({
                "Url": text,
                "Encoding": enc,
                "Source": source,
                "Region": region,
                "Offset": base_offset + m.start(),
                "NearbyFiletime_raw": ft,
                "NearbyFiletime": filetime_to_dt(ft),
                "InLiveDb": False,
            })
    return out


# History URLs are stored with a container date-range prefix and the account
# that visited them: ":YYYYMMDDYYYYMMDD: user@<url>" or "Visited: user@<url>".
# A partial carve can clip either, so both are stripped before comparing
# strings — otherwise two carves of the same URL look like different findings.
# ":YYYYMMDDYYYYMMDD:" — the History container's coverage window, prepended to
# every URL filed under it. Two dates run together, so it is a range and not a
# point in time. The opening colon is optional because a carve that starts
# mid-number leaves "0920260216: ...".
_RANGE_PREFIX = re.compile(r"^\s*:?\d{6,16}:\s*")
_VISITED_PREFIX = re.compile(r"^\s*Visited:\s*", re.IGNORECASE)

# The first scheme-like token: "https:", "file:", "ms-screenclip:", "about:".
# Anchoring on this is what makes the account prefix removable without knowing
# anything about the account name.
_SCHEME = re.compile(r"[a-zA-Z][a-zA-Z0-9+.\-]{0,31}:")

_HISTORY_RANGE = re.compile(r":?(\d{8})(\d{8}):")


def decode_history_range(text: str):
    """The date window a History URL was filed under, as (start, end) strings.

    Returns (None, None) when the string carries no range. This is the
    container's coverage period (every record filed under it was visited
    inside that window), not the visit time of this particular record.
    """
    if not text:
        return None, None
    m = _HISTORY_RANGE.search(str(text)[:40])
    if not m:
        return None, None
    out = []
    for raw in m.groups():
        year, month, day = raw[:4], raw[4:6], raw[6:8]
        if not ("1990" <= year <= "2999" and "01" <= month <= "12"
                and "01" <= day <= "31"):
            return None, None
        out.append(f"{year}-{month}-{day}")
    return out[0], out[1]


def strip_account_prefix(text: str) -> str:
    """Remove a leading "<account>@" from a stored URL.

    Only the account is removed, never userinfo inside the URL itself: the @
    must fall before the scheme. A username may contain anything at all —
    spaces, dots, unicode, even its own @ — because nothing here depends on
    what the name looks like, only on where the URL begins.
    """
    if not text or "@" not in text:
        return text
    scheme = _SCHEME.search(text)
    if not scheme:
        # No scheme at all (":Host: This PC", a bare filename): nothing
        # here is an account prefix, so it is left as stored.
        return text
    cut = text.rfind("@", 0, scheme.start())
    return text[cut + 1:] if cut != -1 else text


def normalize_carved(text: str) -> str:
    """The comparable core of a carved string, container and account prefixes
    removed, so two readings of one URL compare equal."""
    if not text:
        return ""
    core = str(text).strip().strip("\x00")
    core = _RANGE_PREFIX.sub("", core, count=1)
    core = _VISITED_PREFIX.sub("", core, count=1)
    return strip_account_prefix(core).strip()


def _carve_identity(text: str) -> str:
    """Case-folded normalised form used only for fragment comparison."""
    return normalize_carved(text).lower()


def _normalise_carved(record, containers_meta=None, container_types=None):
    """Derive a carved record's remaining fields, in place.

    Imported here rather than at module scope: carving has to work when the
    parser cannot open the database at all, so it must not depend on the
    parser being importable to start.
    """
    try:
        from .ese_parser import normalise_record
    except Exception:
        return record
    try:
        return normalise_record(record, containers_meta, container_types)
    except Exception:
        return record


def subsume_fragments(artifacts: list) -> list:
    """Fold partial carves into the fullest version of the same string.

    An artifact is a fragment when its normalised text is contained in another
    artifact's normalised text. The longest form wins and inherits the others:
    FragmentCount, FragmentOffsets and FragmentTexts keep every discarded
    reading available, so nothing becomes unverifiable — it just stops being
    counted as a separate discovery.
    """
    if not artifacts:
        return []

    # Longest first, so the fullest reading of a string is always the keeper.
    identified = [(_carve_identity(a.get("Url", "")), a) for a in artifacts]
    ordered = sorted(identified,
                     key=lambda pair: (len(pair[0]), -(pair[1].get("Offset") or 0)),
                     reverse=True)

    kept = []
    kept_ids = []
    for ident, art in ordered:
        # A carve with no URL-ish content left after stripping prefixes is a
        # scrap of an account name, not an artifact.
        if len(ident) < 8:
            continue
        owner = None
        for i, existing in enumerate(kept_ids):
            if ident in existing:
                owner = i
                break
        if owner is None:
            fresh = dict(art)
            fresh["UrlNormalized"] = normalize_carved(art.get("Url", ""))
            start, end = decode_history_range(art.get("Url", ""))
            if start:
                fresh["HistoryRangeStart"] = start
                fresh["HistoryRangeEnd"] = end
                fresh["HistoryRange"] = f"{start} \u2192 {end}"
            fresh["FragmentCount"] = 0
            fresh["FragmentOffsets"] = []
            fresh["FragmentTexts"] = []
            kept.append(fresh)
            kept_ids.append(ident)
            continue
        target = kept[owner]
        target["FragmentCount"] += 1
        target["FragmentOffsets"].append(art.get("Offset"))
        target["FragmentTexts"].append(art.get("Url", ""))
        # A fragment seen in a second region is corroboration worth keeping.
        if art.get("Region") and art.get("Region") not in (
                target.get("AlsoSeenIn") or ""):
            also = target.get("AlsoSeenIn") or ""
            if art.get("Region") != target.get("Region"):
                target["AlsoSeenIn"] = (also + ", " if also else "") + art["Region"]
    return kept


class LogFileInfo:
    """Parsed ESE transaction-log header facts (offsets validated empirically)."""

    def __init__(self, path: str):
        self.path = path
        self.name = os.path.basename(path)
        self.size = os.path.getsize(path)
        with open(path, "rb") as f:
            hdr = f.read(0x800)
        self.checksum = struct.unpack_from("<I", hdr, 0)[0]
        # int32 at +4 is the log generation number (V010023C.log <-> 0x23C)
        self.generation = struct.unpack_from("<I", hdr, 4)[0]
        self.create_time = _ese_logtime(hdr[16:24])
        self.prev_gen_time = _ese_logtime(hdr[24:32])

    def as_dict(self) -> dict:
        return {
            "File": self.name,
            "SizeBytes": self.size,
            "Generation": self.generation,
            "GenerationHex": f"0x{self.generation:X}",
            "CreateTime": self.create_time.isoformat(sep=" ") if self.create_time else "",
            "PrevGenTime": self.prev_gen_time.isoformat(sep=" ") if self.prev_gen_time else "",
        }


def parse_checkpoint(chk_path: str) -> dict:
    """Parse V01.chk: the last-flushed log generation lives at offset 16 (int32)."""
    out = {"File": os.path.basename(chk_path), "CheckpointGeneration": None,
           "CheckpointGenerationHex": "", "Note": ""}
    try:
        with open(chk_path, "rb") as f:
            data = f.read(64)
        gen = struct.unpack_from("<I", data, 16)[0]
        out["CheckpointGeneration"] = gen
        out["CheckpointGenerationHex"] = f"0x{gen:X}"
        out["Note"] = ("Log generations >= this value may contain records "
                       "never flushed to the database file.")
    except (OSError, struct.error) as e:
        out["Note"] = f"Checkpoint unreadable: {e}"
    return out


class RecoveryEngine:
    """Carves deleted/unflushed records from transaction logs and DB free space.

    All inputs are opened read-only; nothing under the evidence directory is
    ever written to.
    """

    def __init__(self):
        self.log_infos = []          # [LogFileInfo.as_dict()]
        self.checkpoint = {}         # parse_checkpoint() result
        self.log_artifacts = []      # carved from logs
        self.page_artifacts = []     # carved from .dat slack/empty pages
        self.page_stats = {}         # page classification counts
        self.structured_records = []  # whole deleted records, rebound to columns
        # Container table, so a carved EntryId can be named rather than left
        # blank. Set by the caller; absent means the fields stay empty.
        self._containers_meta = []
        self._container_types = {}
        self.decision_log = []       # transparent processing notes

    # ── Transaction logs ──────────────────────────────────────────────

    def find_log_files(self, db_path: str, allowed_names=None) -> list:
        """Locate V01*.log siblings of the database file.

        allowed_names, when given, is the set of file names the examiner
        chose to read at open (the files hashed): a log not in it is never
        read. None keeps every sibling, as an open without a choice does."""
        d = os.path.dirname(os.path.abspath(db_path))
        prefix = log_prefix(db_path).lower()
        logs = []
        for fn in sorted(os.listdir(d)):
            fl = fn.lower()
            if fl.endswith(".log") and fl.startswith(prefix):
                if allowed_names is None or fn in allowed_names:
                    logs.append(os.path.join(d, fn))
        return logs

    def _note_unchosen(self, db_path, allowed_names):
        """Name, in the decision log, every sibling the examiner left out."""
        if allowed_names is None:
            return
        d = os.path.dirname(os.path.abspath(db_path))
        prefix = log_prefix(db_path).lower()
        skipped = []
        for fn in sorted(os.listdir(d)):
            fl = fn.lower()
            if (fl.startswith(prefix) and fl.endswith((".log", ".chk"))
                    and fn not in allowed_names):
                skipped.append(fn)
        if skipped:
            self.decision_log.append(
                "Not chosen at open, so not read: %s." % ", ".join(skipped))

    def carve_transaction_logs(self, db_path: str, live_urls: set,
                               progress_callback=None, allowed_names=None) -> list:
        """Carve every chosen sibling transaction log (every one when
        allowed_names is None). Returns recovered artifacts."""
        self.log_artifacts = []
        self.log_infos = []
        seen = set()
        self._note_unchosen(db_path, allowed_names)

        chk_name = "%s.chk" % log_prefix(db_path)
        chk = os.path.join(os.path.dirname(os.path.abspath(db_path)), chk_name)
        if os.path.exists(chk) and (allowed_names is None
                                    or chk_name in allowed_names):
            self.checkpoint = parse_checkpoint(chk)
            self.decision_log.append(
                f"Checkpoint {self.checkpoint['File']}: last flushed generation "
                f"{self.checkpoint['CheckpointGenerationHex']}")

        logs = self.find_log_files(db_path, allowed_names)
        if not logs:
            # Logs that exist but were left out are a choice, not missing
            # from the collection, and are reported as such.
            if self.find_log_files(db_path):
                self.decision_log.append(
                    "No %s*.log transaction log was read: those next to "
                    "the database were not chosen at open."
                    % log_prefix(db_path))
            else:
                self.decision_log.append(
                    "No %s*.log transaction logs found next to the database."
                    % log_prefix(db_path))
            return []

        ckgen = self.checkpoint.get("CheckpointGeneration")
        for i, path in enumerate(logs):
            try:
                info = LogFileInfo(path)
                d = info.as_dict()
                if ckgen is not None:
                    d["MayHoldUnflushed"] = info.generation >= ckgen
                self.log_infos.append(d)

                with open(path, "rb") as f:
                    data = f.read()
                found = _carve_strings(data, 0, live_urls,
                                       source=info.name,
                                       region="transaction-log", seen=seen)
                for a in found:
                    a["LogGeneration"] = f"0x{info.generation:X}"
                    a["LogCreateTime"] = (info.create_time.isoformat(sep=" ")
                                          if info.create_time else "")
                    a["Confidence"] = "medium" if a["NearbyFiletime"] else "low"
                self.log_artifacts.extend(found)
                self.decision_log.append(
                    f"{info.name} (gen 0x{info.generation:X}): "
                    f"{len(found)} recovered strings not in live DB")
            except (OSError, struct.error) as e:
                self.decision_log.append(f"{os.path.basename(path)}: SKIPPED — {e}")
            if progress_callback:
                progress_callback(i + 1, len(logs))

        return self.log_artifacts

    # ── Unallocated space in the .dat ─────────────────────────────────

    def carve_database_slack(self, db, db_path: str, live_urls: set,
                             progress_callback=None) -> list:
        """Carve page slack and empty pages of an open dissect.esedb EseDB.

        Slack = bytes of a page not covered by the 80-byte header, the tag
        array, or any live tag's data. Empty-flagged pages are carved whole.
        """
        self.page_artifacts = []
        seen = set()
        page_size = db.page_size
        total_pages = os.path.getsize(db_path) // page_size - 2
        stats = {"total": total_pages, "empty": 0, "leaf": 0, "branch": 0,
                 "space_tree": 0, "long_value": 0, "unreadable": 0,
                 "slack_bytes": 0}

        for pnum in range(1, total_pages + 1):
            try:
                page = db.page(pnum)
                buf = bytes(page.buf)
            except Exception:
                stats["unreadable"] += 1
                continue

            if page.is_empty:
                stats["empty"] += 1
                regions = [(0, len(buf), "empty-page")]
            else:
                if page.is_space_tree:
                    stats["space_tree"] += 1
                elif page.is_leaf:
                    stats["leaf"] += 1
                elif page.is_branch:
                    stats["branch"] += 1
                if page.is_long_value:
                    stats["long_value"] += 1

                hdr_size = 40 if page.is_small_page else 80
                covered = [(0, hdr_size)]
                try:
                    ntags = page.header.itagMicFree
                except AttributeError:
                    ntags = 0
                covered.append((len(buf) - ntags * 4, len(buf)))
                try:
                    for tag in page.tags():
                        covered.append((hdr_size + tag.offset,
                                        hdr_size + tag.offset + tag.size))
                except Exception:
                    # tag walk failed — treat whole body as carveable
                    covered = [(0, hdr_size), (len(buf) - ntags * 4, len(buf))]
                covered.sort()
                regions = []
                pos = 0
                for s, e in covered:
                    if s > pos:
                        regions.append((pos, s, "page-slack"))
                    pos = max(pos, e)
                if pos < len(buf):
                    regions.append((pos, len(buf), "page-slack"))

            for s, e, kind in regions:
                if e - s < 16:
                    continue
                stats["slack_bytes"] += e - s
                found = _carve_strings(buf[s:e], pnum * page_size + s, live_urls,
                                       source=os.path.basename(db_path),
                                       region=kind, seen=seen)
                for a in found:
                    a["Page"] = pnum
                    a["Confidence"] = ("high" if kind == "empty-page" and a["NearbyFiletime"]
                                       else "medium" if a["NearbyFiletime"] else "low")
                self.page_artifacts.extend(found)

            if progress_callback and pnum % 100 == 0:
                progress_callback(pnum, total_pages)

        self.page_stats = stats
        self.decision_log.append(
            f"Scanned {total_pages} pages ({stats['empty']} empty, {stats['leaf']} leaf, "
            f"{stats['branch']} branch); carved {stats['slack_bytes']:,} slack bytes; "
            f"{len(self.page_artifacts)} deleted-record candidates recovered")
        return self.page_artifacts

    # ── Structured record reconstruction ──────────────────────────────

    def carve_structured_records(self, db, db_path, progress_callback=None) -> list:
        """Recover whole deleted records, not just URL strings.

        Where the string carvers above prove that a URL was once present, this
        recovers the record around it: EntryId, container, every timestamp,
        visit count, and the trailing ResponseHeaders property store that holds
        the true visit count and local-clock last-visit time.
        """
        from . import struct_carver
        from . import sps_decoder

        self.structured_records = []
        try:
            raw_records = struct_carver.carve_records(
                db_path, db=db, progress_callback=progress_callback)
        except Exception as e:
            self.decision_log.append(f"Structured carve unavailable: {e}")
            return []

        container_names = {}
        try:
            for meta in (getattr(self, "_container_names", None) or {}):
                container_names[meta] = self._container_names[meta]
        except Exception:
            pass

        for r in raw_records:
            if r.get("_grade") == "LOW":
                continue
            url = r.get("Url") or ""
            rec = {
                "Url": url,
                "EntryId": r.get("EntryId"),
                "ContainerId": r.get("ContainerId"),
                "ContainerName": container_names.get(r.get("ContainerId"), ""),
                "AccessCount": r.get("AccessCount"),
                "Flags": r.get("Flags"),
                "FileSize": r.get("FileSize"),
                # Every column struct_carver.FIXED_COLUMNS recovers from a
                # deleted record is kept: they were read by the carve that
                # produced `r`, and a re-scan is the most expensive read
                # this application performs.
                #
                # Filename is handled below.
                "CacheId": r.get("CacheId"),
                "UrlHash": r.get("UrlHash"),
                "SecureDirectory": r.get("SecureDirectory"),
                "Type": r.get("Type"),
                "SyncCount": r.get("SyncCount"),
                "ExemptionDelta": r.get("ExemptionDelta"),
                "Confidence": r.get("_grade", "").lower(),
                "Offset": r.get("_offset"),
                "Page": r.get("_page"),
                "RecordEndMode": r.get("_mode"),
                "Source": os.path.basename(db_path),
                "Region": "deleted-record",
                "RecoverySource": STRUCTURED_METHOD,
                "HasResponseHeaders": bool(r.get("ResponseHeaders")),
                "ResponseHeaders_raw": r.get("ResponseHeaders"),
                "InLiveDb": False,
            }

            # The cached file's own name, as the deleted record stored it.
            # normalise_record derives a Filename only from a file: URL, so
            # for an http(s) record this is the only source.
            #
            # Set only when the carve recovered one, never as "":
            # normalise_record sets its derived Filename with setdefault(),
            # which a present-but-empty key would block.
            if r.get("Filename"):
                rec["Filename"] = r["Filename"]

            for col in ("CreationTime", "ModifiedTime", "AccessedTime",
                        "ExpiryTime", "SyncTime", "PostCheckTime"):
                val = r.get(col)
                rec[col + "_raw"] = val if isinstance(val, int) else 0
                dt = filetime_to_dt(val) if isinstance(val, int) else None
                rec[col] = stamp_str(dt, "UTC")

            # The headline capability: the property store survives with the
            # record, so a deleted visit still yields its true visit count and
            # local-clock last-visit time.
            if r.get("_sps") and r.get("ResponseHeaders"):
                try:
                    fx = sps_decoder.extract_history_forensics(r["ResponseHeaders"])
                    rec["SPS_VisitCount"] = fx.get("visit_count")
                    if fx.get("last_visit_local"):
                        rec["SPS_LastVisitLocal"] = stamp_str(
                            fx["last_visit_local"], "LOCAL")
                        rec["SPS_LastVisitLocal_raw"] = fx.get("last_visit_local_raw")
                    rec["SPS_PageTitle"] = fx.get("page_title") or ""
                except Exception:
                    pass

            ft_ctx = rec.get("AccessedTime_raw") or rec.get("ModifiedTime_raw") or 0
            rec["NearbyFiletime_raw"] = ft_ctx
            rec["NearbyFiletime"] = filetime_to_dt(ft_ctx) if ft_ctx else None
            _normalise_carved(rec, self._containers_meta, self._container_types)
            self.structured_records.append(rec)

        with_sps = sum(1 for r in self.structured_records if r.get("SPS_VisitCount") is not None)
        self.decision_log.append(
            f"Structured reconstruction: {len(self.structured_records)} deleted records "
            f"rebound to their columns ({with_sps} with a recovered property store "
            f"giving true visit count and local-clock last visit)")
        return self.structured_records

    def validate_structured_carve(self, db_path) -> dict:
        """Measured accuracy of the structured carve against live records."""
        try:
            from . import struct_carver
            return dict(struct_carver.validate(db_path))
        except Exception as e:
            return {"error": str(e)}

    # ── Combined ──────────────────────────────────────────────────────

    def set_container_metadata(self, containers_meta, container_types=None):
        """Give carving the container table and type map, so a carved record
        can be named and classified the way a live one is."""
        self._containers_meta = list(containers_meta or [])
        self._container_types = dict(container_types or {})

    def all_artifacts(self) -> list:
        """All recovered artifacts, page + log, newest evidence first.

        Fragments of the same string are folded together here rather than at
        carve time, because the same URL is routinely found once in a
        transaction log and again in database slack — and those two readings
        should corroborate one artifact, not inflate the count to two.
        """
        arts = []
        for a in self.page_artifacts:
            b = dict(a)
            b["RecoverySource"] = UNALLOCATED_METHOD
            arts.append(b)
        for a in self.log_artifacts:
            b = dict(a)
            b["RecoverySource"] = LOG_METHOD
            arts.append(b)
        arts = subsume_fragments(arts)
        # Every carved record gets the derived fields a live one has, from
        # the same functions, so a carved "Visited: user@file:///C:/..." is
        # recognised as a local file access like a live one.
        for a in arts:
            _normalise_carved(a, self._containers_meta, self._container_types)
        arts.sort(key=lambda x: (x["NearbyFiletime_raw"] or 0), reverse=True)
        return arts

    def summary(self) -> dict:
        return {
            "log_files": self.log_infos,
            "checkpoint": self.checkpoint,
            "log_recovered": len(self.log_artifacts),
            "page_recovered": len(self.page_artifacts),
            "total_recovered": len(self.log_artifacts) + len(self.page_artifacts),
            "page_stats": self.page_stats,
            "decision_log": list(self.decision_log),
        }
