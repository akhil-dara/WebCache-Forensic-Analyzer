"""Case persistence: tags, comments, bookmarks, saved searches and case
metadata in a SQLite file kept apart from the evidence.

Records are keyed by a stable identity (container and entry id, or the
carve location), so notes survive a re-parse.
"""

import os
import sqlite3
from datetime import datetime, timezone


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class CaseDb:
    def __init__(self):
        self.conn = None
        self.path = None

    def open(self, path: str):
        self.path = path
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()
        return self

    def _init_schema(self):
        c = self.conn
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS tags (
                record_key TEXT NOT NULL,
                tag TEXT NOT NULL,
                created TEXT NOT NULL,
                PRIMARY KEY (record_key, tag));
            CREATE TABLE IF NOT EXISTS comments (
                record_key TEXT NOT NULL,
                comment TEXT NOT NULL,
                author TEXT,
                created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS bookmarks (
                record_key TEXT PRIMARY KEY,
                url TEXT, note TEXT, created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS saved_searches (
                name TEXT PRIMARY KEY, query TEXT NOT NULL, created TEXT NOT NULL);
            """
        )
        c.commit()

    # ── record identity ──────────────────────────────────────────────
    #
    # A key names one record and no other, so a tag never lands on evidence
    # the examiner did not look at. A carved artifact's key includes its log
    # generation, region and page: the same byte offset recurs across
    # transaction-log generations.
    @staticmethod
    def record_key(entry: dict) -> str:
        if entry.get("RecoverySource"):
            parts = [
                "rec",
                str(entry.get("RecoverySource", "")),
                str(entry.get("Region", "")),
                str(entry.get("LogGeneration", "")),
                str(entry.get("Page", "")),
                str(entry.get("Offset", "")),
            ]
            return ":".join(parts)
        return f"ese:{entry.get('ContainerId','')}:{entry.get('EntryId','')}"

    @staticmethod
    def legacy_record_key(entry: dict) -> str:
        """The key form used by case files written before carved keys
        included the log generation. Reads fall back to it so existing work
        is kept; writes always use record_key. A legacy key can match more
        than one artifact, so its tag shows on each.
        """
        if entry.get("RecoverySource"):
            return f"rec:{entry.get('RecoverySource','')}:{entry.get('Offset','')}"
        return f"ese:{entry.get('ContainerId','')}:{entry.get('EntryId','')}"

    @classmethod
    def record_keys(cls, entry: dict) -> list:
        """Every key this record's work product could be stored under."""
        current = cls.record_key(entry)
        legacy = cls.legacy_record_key(entry)
        return [current] if legacy == current else [current, legacy]

    # ── case metadata ────────────────────────────────────────────────
    def set_meta(self, key: str, value: str):
        self.conn.execute(
            "INSERT INTO meta(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
        self.conn.commit()

    def get_meta(self, key: str, default: str = "") -> str:
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def all_meta(self) -> dict:
        return {r["key"]: r["value"] for r in
                self.conn.execute("SELECT key,value FROM meta").fetchall()}

    # ── tags ─────────────────────────────────────────────────────────
    def add_tag(self, record_key: str, tag: str):
        self.conn.execute(
            "INSERT OR IGNORE INTO tags(record_key,tag,created) VALUES(?,?,?)",
            (record_key, tag, _now()))
        self.conn.commit()

    def remove_tag(self, record_key: str, tag: str):
        self.conn.execute("DELETE FROM tags WHERE record_key=? AND tag=?",
                          (record_key, tag))
        self.conn.commit()

    def tags_for(self, record_key: str) -> list:
        return [r["tag"] for r in self.conn.execute(
            "SELECT tag FROM tags WHERE record_key=? ORDER BY tag", (record_key,))]

    def tags_for_entry(self, entry: dict) -> list:
        """Tags on this record, including any stored under its legacy key."""
        keys = self.record_keys(entry)
        placeholders = ",".join("?" * len(keys))
        return sorted({r["tag"] for r in self.conn.execute(
            f"SELECT tag FROM tags WHERE record_key IN ({placeholders})",
            keys)})

    def comments_for_entry(self, entry: dict) -> list:
        """Comments on this record, including any under its legacy key."""
        keys = self.record_keys(entry)
        placeholders = ",".join("?" * len(keys))
        return [dict(r) for r in self.conn.execute(
            f"SELECT comment,author,created FROM comments "
            f"WHERE record_key IN ({placeholders}) ORDER BY created", keys)]

    def all_tags(self) -> dict:
        """record_key -> [tags]"""
        out = {}
        for r in self.conn.execute("SELECT record_key,tag FROM tags"):
            out.setdefault(r["record_key"], []).append(r["tag"])
        return out

    def tag_counts(self) -> list:
        return [(r["tag"], r["n"]) for r in self.conn.execute(
            "SELECT tag, COUNT(*) n FROM tags GROUP BY tag ORDER BY n DESC")]

    # ── comments ─────────────────────────────────────────────────────
    def add_comment(self, record_key: str, comment: str, author: str = ""):
        self.conn.execute(
            "INSERT INTO comments(record_key,comment,author,created) VALUES(?,?,?,?)",
            (record_key, comment, author, _now()))
        self.conn.commit()

    def comments_for(self, record_key: str) -> list:
        return [dict(r) for r in self.conn.execute(
            "SELECT comment,author,created FROM comments WHERE record_key=? "
            "ORDER BY created", (record_key,))]

    def all_comments(self) -> dict:
        """record_key -> [comments], for every record that carries one,
        whether or not it is also tagged."""
        out = {}
        for r in self.conn.execute(
                "SELECT record_key,comment,author,created FROM comments "
                "ORDER BY created"):
            out.setdefault(r["record_key"], []).append(
                {"comment": r["comment"], "author": r["author"],
                 "created": r["created"]})
        return out

    def comment_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) n FROM comments").fetchone()["n"]

    # ── saved searches ───────────────────────────────────────────────
    def save_search(self, name: str, query: str):
        self.conn.execute(
            "INSERT INTO saved_searches(name,query,created) VALUES(?,?,?) "
            "ON CONFLICT(name) DO UPDATE SET query=excluded.query",
            (name, query, _now()))
        self.conn.commit()

    def saved_searches(self) -> list:
        return [dict(r) for r in self.conn.execute(
            "SELECT name,query FROM saved_searches ORDER BY name")]

    def close(self):
        if self.conn:
            self.conn.close()
            self.conn = None
