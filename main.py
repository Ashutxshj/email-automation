"""Draft-prep tool. Prepares cold outreach for a human to read and paste.

    python main.py --prep                # Gemini-draft Message + Channel + drafts.md
    python main.py --prep --limit 10     # only draft the 10 best-ordered leads
    python main.py --prep --redraft      # regenerate rows that already have a Message
    python main.py --prep --no-llm       # offline template drafts (no Gemini)
    python main.py --prep --mock-llm     # fake Gemini: test the pipeline, no quota
    python main.py --mark-sent <ident>   # Reached = TRUE (email, @handle or phone)
    python main.py --suppress <ident>    # Do Not Contact = TRUE
    python main.py --stats               # counts from the master workbook

All state lives in Projects/leads_master.xlsx. There is no database here.

THERE IS NO --send FLAG, AND THERE MUST NEVER BE ONE.
Gemini only WRITES drafts. A human reads and pastes every single one.

At ~25 usable leads, automation is the wrong build. Sending by hand is faster
than the automation that would replace it; Gmail cannot tell the difference
(deliverability is decided by domain reputation, authentication, bounce rate and
engagement, not by who pressed the button); and a human in the loop is the only
thing that stops `Hi {{FirstName}},` going out 25 times, which is unrecoverable.

Send ~10-15 emails a day from ONE mailbox. That IS the warmup — no paid warmup
tool is needed. Spreading 25 emails across 5 mailboxes gives all five of them no
reputation at all.
"""

import argparse
import sys

import config
import draft
import generate
import leads as leads_mod
import master_registry
import verify
from genai_client import GeminiClient, GeminiError
from ledger import Ledger


def cmd_prep(limit: int, no_llm: bool = False, redraft: bool = False,
             mock_llm: bool = False) -> int:
    all_leads, rejected = leads_mod.load_all()
    print(f"[leads] {len(all_leads)} contactable leads in {master_registry.MASTER_FILE}")
    print(f"[leads] {len(rejected)} rejected before drafting")
    for identifier, reason in rejected:
        print(f"[purge] {identifier}: {reason}")

    ledger = Ledger()
    ordered = verify.send_order(all_leads)
    held, skipped, eligible = [], [], []

    # Phase A — gates. Everything that survives gets drafted.
    for lead in ordered:
        if lead.reached:
            skipped.append((lead, "already reached"))
            continue
        if lead.message and not redraft:
            skipped.append((lead, "already drafted (--redraft to regenerate)"))
            continue

        verdict, note = verify.check(lead)
        if verdict == verify.DROP:
            skipped.append((lead, note))
            continue
        if verdict == verify.HOLD:
            held.append((lead, note))
            continue

        if limit and len(eligible) >= limit:
            skipped.append((lead, f"beyond --limit {limit}"))
            continue
        eligible.append(lead)

    # Phase B — draft. Gemini by default, templates with --no-llm.
    client = None
    if no_llm:
        drafted_raw = []
        for i, lead in enumerate(eligible):
            try:
                subject, body = draft.build(lead, ledger, attempt_order=i)
            except draft.DraftError as exc:
                skipped.append((lead, str(exc)))
                continue
            ledger.hold_pending(lead.identifier, body)
            drafted_raw.append((lead, subject, body))
    else:
        try:
            client = GeminiClient(mock=mock_llm)
        except GeminiError as exc:
            print(f"\n[gemini] {exc}")
            return 1
        drafted_raw, failed = generate.draft_all(eligible, ledger, client)
        skipped.extend(failed)

    # Phase C — write back.
    drafted = []
    for lead, subject, message in drafted_raw:
        label = config.CHANNEL_LABELS[lead.channel]
        if not ledger.save_draft(lead.identifier, message, label):
            skipped.append((lead, "could not write Message back to the master"))
            continue
        drafted.append((lead, subject, message))

    _write_drafts_md(drafted, held, skipped)

    print(f"\n[prep] {len(drafted)} drafted, {len(held)} held, {len(skipped)} skipped")
    if client is not None:
        print(f"[gemini] {client.request_count} requests, "
              f"~{client.token_count} tokens ({client.model}"
              f"{', MOCK — nothing was spent' if client.mock else ''})")
    print(f"[prep] Message + Channel written in {master_registry.MASTER_FILE}")
    print(f"[prep] readable copy       -> {config.DRAFTS_FILE}")
    print("\nRead every draft before sending. Send the freshest domains first,")
    print("~10/day, from one mailbox. Any bounce: stop and re-check the HOLD list.")
    ledger.close()
    return 0


def _write_drafts_md(drafted, held, skipped) -> None:
    lines = ["# Outreach drafts", "",
             "Read each one. Verify the fact on their actual site. Fix anything that",
             "reads wrong. Paste it yourself, then run",
             "`python main.py --mark-sent <identifier>`.", ""]

    for channel, title in ((config.CHANNEL_EMAIL, "Emails"),
                           (config.CHANNEL_INSTAGRAM, "Instagram DMs"),
                           (config.CHANNEL_WHATSAPP, "WhatsApp messages")):
        rows = [d for d in drafted if d[0].channel == channel]
        if not rows:
            continue
        lines += [f"## {title} ({len(rows)})", ""]
        for lead, subject, body in rows:
            # The Message cell embeds the subject; don't show it twice here.
            if subject and body.startswith(f"Subject: {subject}"):
                body = body[len(f"Subject: {subject}"):].lstrip("\n")
            lines.append(f"### {lead.business}")
            if lead.channel == config.CHANNEL_WHATSAPP:
                lines.append(f"- **To:** `{lead.phone or lead.identifier}` (WhatsApp)")
            else:
                lines.append(f"- **To:** `{lead.identifier}`")
            if subject:
                lines.append(f"- **Subject:** {subject}")
            if lead.stale_days:
                lines.append(f"- **Site last touched:** {lead.stale_days} days ago")
            if lead.channel == config.CHANNEL_EMAIL and lead.is_role_address:
                lines.append("- **Note:** role address — expect a low reply rate")
            lines += ["", "```text", body, "```", ""]

    if held:
        lines += ["## Held back", "",
                  "Not drafted on purpose. Send these only once the mailbox has a "
                  "reputation.", ""]
        lines += [f"- `{l.identifier}` — {note}" for l, note in held] + [""]
    if skipped:
        lines += ["## Skipped", ""]
        lines += [f"- `{l.identifier}` — {note}" for l, note in skipped] + [""]

    with open(config.DRAFTS_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def cmd_mark_sent(identifier: str) -> int:
    ledger = Ledger()
    if not ledger.mark_sent(identifier):
        print(f"[master] no lead matching '{identifier}'. Check the spelling — "
              "an email address, an @handle, or a 10-digit phone number.")
        return 1
    print(f"[master] {identifier}: Reached = TRUE")
    return 0


def cmd_suppress(identifier: str) -> int:
    ledger = Ledger()
    if not ledger.suppress(identifier):
        print(f"[master] no lead matching '{identifier}'.")
        return 1
    print(f"[master] {identifier}: Do Not Contact = TRUE — never contacted again")
    return 0


def cmd_stats() -> int:
    s = Ledger().stats()
    print(f"master: {master_registry.MASTER_FILE}")
    print(f"  leads      {s['total']}")
    print(f"  drafted    {s['drafted']}")
    print(f"  reached    {s['reached']}")
    print(f"  suppressed {s['suppressed']}")
    for channel, count in sorted(s["by_channel"].items()):
        print(f"    {channel}: {count}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Prepare cold outreach drafts. Never sends anything.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--prep", action="store_true",
                       help="write the Message + Channel columns + drafts.md")
    group.add_argument("--mark-sent", metavar="IDENT",
                       help="record an email/@handle/phone you just sent by hand")
    group.add_argument("--suppress", metavar="IDENT",
                       help="permanent opt-out (Do Not Contact)")
    group.add_argument("--stats", action="store_true", help="show master totals")
    parser.add_argument("--limit", type=int, default=0,
                        help="cap how many drafts --prep produces (a day's batch)")
    parser.add_argument("--redraft", action="store_true",
                        help="regenerate leads that already have a Message")
    parser.add_argument("--no-llm", action="store_true",
                        help="skip Gemini and use the built-in templates")
    parser.add_argument("--mock-llm", action="store_true",
                        help="fake Gemini responses: full pipeline, zero quota")
    args = parser.parse_args()

    if args.prep:
        sys.exit(cmd_prep(args.limit, no_llm=args.no_llm, redraft=args.redraft,
                          mock_llm=args.mock_llm))
    if args.mark_sent:
        sys.exit(cmd_mark_sent(args.mark_sent))
    if args.suppress:
        sys.exit(cmd_suppress(args.suppress))
    sys.exit(cmd_stats())
