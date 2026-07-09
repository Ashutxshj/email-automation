"""Stage 4 — outreach state, stored in the ONE master workbook.

There is no SQLite database and no queue.xlsx any more. Three columns in
Projects/leads_master.xlsx carry everything:

    Message         the drafted text, written here by --prep
    Reached         you sent it (set by --mark-sent)
    Do Not Contact  they asked you to stop (set by --suppress)

Uniqueness is by SIMILARITY, not by hash. Two bodies differing by one comma have
different hashes, so a hash-based "are these emails unique?" check passes
everything and guarantees nothing. difflib over the Message column is O(n^2),
which is free at n < 500.

The comparison strips shared boilerplate first. The opt-out line and signature
are identical in every draft by design and are a large fraction of a ~90-word
email; leaving them in drags every pair toward 1.0, so two emails making
completely different points score ~0.90 and look like duplicates.
"""

import difflib

import config
import master_registry


def _comparable(body: str) -> str:
    """Body minus the boilerplate every message shares."""
    stripped = str(body or "")
    for boilerplate in (config.EMAIL_OPTOUT, config.DM_OPTOUT, config.SIGNATURE):
        stripped = stripped.replace(boilerplate, " ")
    return " ".join(stripped.split()).lower()


def _identifier(row: dict) -> str:
    email = master_registry.norm_email(row.get("Email Address"))
    if email:
        return email
    return str(row.get("Instagram") or "").strip()


class Ledger:
    """A thin view over the master workbook's three outreach columns."""

    def __init__(self):
        # Bodies drafted in THIS run but not yet written back. Without these,
        # two leads in one batch could both receive the same near-duplicate.
        self._pending: list[tuple[str, str]] = []

    def close(self) -> None:  # kept so callers don't need to care
        pass

    # --- reads ---------------------------------------------------------------

    def _messages(self) -> list[tuple[str, str]]:
        return [(_identifier(r), str(r.get("Message") or ""))
                for r in master_registry.load_rows()
                if str(r.get("Message") or "").strip()]

    def most_similar(self, body: str, exclude: str = "") -> tuple[str, float] | None:
        """(identifier, ratio) of the closest existing message, or None.

        `exclude` skips a lead's own previous Message, so re-running --prep
        doesn't see last run's draft as a duplicate of this run's.
        """
        skip = str(exclude or "").strip().lower()
        target = _comparable(body)
        best: tuple[str, float] | None = None
        for identifier, prior in self._messages() + self._pending:
            if identifier.lower() == skip:
                continue
            ratio = difflib.SequenceMatcher(None, _comparable(prior), target).ratio()
            if best is None or ratio > best[1]:
                best = (identifier, ratio)
        return best

    def stats(self) -> dict:
        rows = master_registry.load_rows()
        reached = [r for r in rows if master_registry.is_true(r.get("Reached"))]
        by_channel: dict[str, int] = {}
        for row in reached:
            channel = (config.CHANNEL_EMAIL
                       if master_registry.norm_email(row.get("Email Address"))
                       else config.CHANNEL_INSTAGRAM)
            by_channel[channel] = by_channel.get(channel, 0) + 1
        return {
            "total": len(rows),
            "reached": len(reached),
            "suppressed": sum(1 for r in rows
                              if master_registry.is_true(r.get("Do Not Contact"))),
            "drafted": sum(1 for r in rows if str(r.get("Message") or "").strip()),
            "by_channel": by_channel,
        }

    # --- writes --------------------------------------------------------------

    def hold_pending(self, identifier: str, body: str) -> None:
        """Reserve a drafted body so later drafts in the same run must differ."""
        self._pending.append((identifier, body))

    def save_draft(self, identifier: str, body: str) -> bool:
        """Write the Message column. --prep owns this; nothing else writes it."""
        return master_registry.set_fields(identifier, Message=body)

    def mark_sent(self, identifier: str) -> bool:
        return master_registry.set_fields(identifier, Reached=True)

    def suppress(self, identifier: str) -> bool:
        """Opt-out is permanent and beats Reached: we never write to them again."""
        return master_registry.set_fields(identifier, **{"Do Not Contact": True})
