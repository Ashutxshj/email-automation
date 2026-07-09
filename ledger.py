"""Stage 4 — the outreach ledger. SQLite, not a spreadsheet.

An .xlsx is a bad source of truth for this: a crash between "sent the email" and
"saved the workbook" loses the write, and a lost write means the next run
double-sends to a live prospect. SQLite in WAL mode commits atomically. The xlsx
is generated FROM this, for reading.

This is the only place that knows who has actually been contacted. The scrapers'
`reported_businesses.xlsx` / `contacted_businesses.xlsx` mean something else
entirely — "already included in a report emailed to the operator" — and a
business can appear there having never been contacted.

Uniqueness is by SIMILARITY, not by hash. Two bodies differing by one comma have
different hashes, so a hash-based "are these emails unique?" check passes
everything and guarantees nothing. difflib on the rendered body is O(n^2) across
the corpus, which is free at n < 500.
"""

import difflib
import sqlite3
from datetime import datetime, timezone

import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sent (
    id         INTEGER PRIMARY KEY,
    channel    TEXT NOT NULL,
    identifier TEXT NOT NULL,
    business   TEXT NOT NULL DEFAULT '',
    domain     TEXT NOT NULL DEFAULT '',
    subject    TEXT NOT NULL DEFAULT '',
    body       TEXT NOT NULL,
    sent_at    TEXT NOT NULL,
    UNIQUE(channel, identifier)
);
CREATE TABLE IF NOT EXISTS suppressed (
    channel    TEXT NOT NULL,
    identifier TEXT NOT NULL,
    reason     TEXT NOT NULL DEFAULT '',
    added_at   TEXT NOT NULL,
    PRIMARY KEY (channel, identifier)
);
-- Drafts awaiting a human. Rebuilt from scratch on every --prep, so `sent` is
-- the only durable record. Kept in the DB (not just drafts.md) so --mark-sent
-- can recover the exact body that was pasted, without you retyping it.
CREATE TABLE IF NOT EXISTS draft (
    channel    TEXT NOT NULL,
    identifier TEXT NOT NULL,
    business   TEXT NOT NULL DEFAULT '',
    domain     TEXT NOT NULL DEFAULT '',
    subject    TEXT NOT NULL DEFAULT '',
    body       TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (channel, identifier)
);
"""


def _norm(identifier: str) -> str:
    return (identifier or "").strip().lower()


def _comparable(body: str) -> str:
    """Body minus the boilerplate every message shares.

    The opt-out line and signature are identical in every draft by design, and
    they are a large fraction of a ~90-word email. Leaving them in the comparison
    drags every pair toward 1.0, so two emails making entirely different points
    about entirely different businesses score ~0.90 and look like duplicates.
    Strip them, and the ratio measures what we actually care about: whether these
    two messages SAY the same thing.
    """
    stripped = body
    for boilerplate in (config.EMAIL_OPTOUT, config.DM_OPTOUT, config.SIGNATURE):
        stripped = stripped.replace(boilerplate, " ")
    return " ".join(stripped.split()).lower()


class Ledger:
    def __init__(self, path: str = config.LEDGER_DB):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(_SCHEMA)
        self.conn.commit()
        # Bodies drafted in THIS run but not yet sent. Without these, two leads
        # in one batch could both receive the same near-duplicate message.
        self._pending: list[tuple[str, str]] = []

    def close(self) -> None:
        self.conn.close()

    # --- reads ---------------------------------------------------------------

    def already_sent(self, channel: str, identifier: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM sent WHERE channel=? AND identifier=?",
            (channel, _norm(identifier))).fetchone()
        return row is not None

    def is_suppressed(self, channel: str, identifier: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM suppressed WHERE channel=? AND identifier=?",
            (channel, _norm(identifier))).fetchone()
        return row is not None

    def domain_contacted(self, domain: str) -> str | None:
        """Never put two messages into the same company. Returns who we hit."""
        if not domain:
            return None
        row = self.conn.execute(
            "SELECT identifier FROM sent WHERE domain=?", (domain.lower(),)).fetchone()
        return row["identifier"] if row else None

    def _corpus(self) -> list[tuple[str, str]]:
        rows = self.conn.execute("SELECT identifier, body FROM sent").fetchall()
        return [(r["identifier"], r["body"]) for r in rows] + self._pending

    def most_similar(self, body: str) -> tuple[str, float] | None:
        """(identifier, ratio) of the closest prior message, or None if none exist."""
        target = _comparable(body)
        best: tuple[str, float] | None = None
        for identifier, prior in self._corpus():
            ratio = difflib.SequenceMatcher(None, _comparable(prior), target).ratio()
            if best is None or ratio > best[1]:
                best = (identifier, ratio)
        return best

    def stats(self) -> dict:
        sent = self.conn.execute("SELECT COUNT(*) c FROM sent").fetchone()["c"]
        supp = self.conn.execute("SELECT COUNT(*) c FROM suppressed").fetchone()["c"]
        by_channel = {
            r["channel"]: r["c"] for r in self.conn.execute(
                "SELECT channel, COUNT(*) c FROM sent GROUP BY channel")
        }
        return {"sent": sent, "suppressed": supp, "by_channel": by_channel}

    # --- writes --------------------------------------------------------------

    def hold_pending(self, identifier: str, body: str) -> None:
        """Reserve a drafted body so later drafts in the same run must differ."""
        self._pending.append((identifier, body))

    def clear_drafts(self) -> None:
        """--prep rebuilds the draft set. Sent history is never touched."""
        self.conn.execute("DELETE FROM draft")
        self.conn.commit()

    def save_draft(self, channel: str, identifier: str, subject: str, body: str,
                   business: str = "", domain: str = "") -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO draft (channel, identifier, business, domain,"
            " subject, body, created_at) VALUES (?,?,?,?,?,?,?)",
            (channel, _norm(identifier), business, domain.lower(), subject, body,
             datetime.now(timezone.utc).isoformat(timespec="seconds")))
        self.conn.commit()

    def get_draft(self, identifier: str) -> sqlite3.Row | None:
        """Look a draft up by identifier alone — the human types an address, not
        a channel, and an address can only belong to one channel anyway."""
        return self.conn.execute(
            "SELECT * FROM draft WHERE identifier=?", (_norm(identifier),)).fetchone()

    def mark_sent(self, channel: str, identifier: str, body: str,
                  business: str = "", domain: str = "", subject: str = "") -> bool:
        """Record a message the human actually sent. False if already recorded."""
        try:
            self.conn.execute(
                "INSERT INTO sent (channel, identifier, business, domain, subject,"
                " body, sent_at) VALUES (?,?,?,?,?,?,?)",
                (channel, _norm(identifier), business, domain.lower(), subject, body,
                 datetime.now(timezone.utc).isoformat(timespec="seconds")))
            self.conn.execute("DELETE FROM draft WHERE channel=? AND identifier=?",
                              (channel, _norm(identifier)))
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def suppress(self, channel: str, identifier: str, reason: str = "") -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO suppressed (channel, identifier, reason, added_at)"
            " VALUES (?,?,?,?)",
            (channel, _norm(identifier), reason,
             datetime.now(timezone.utc).isoformat(timespec="seconds")))
        self.conn.commit()
