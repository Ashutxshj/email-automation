# email-automation — a draft-prep tool that never sends

Reads leads from the one master workbook, writes each lead's `Message` back into
it, and prints a human-readable copy for you to review. **There is no `--send`
flag, and there must never be one.**

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt

python main.py --prep                # write the Message column + drafts.md
python main.py --prep --limit 10     # a day's batch
python main.py --mark-sent <ident>   # Reached = TRUE
python main.py --suppress <ident>    # Do Not Contact = TRUE
python main.py --stats
```

`<ident>` is an email address or an `@handle`.

## One file holds everything

`Projects/leads_master.xlsx` (`master_registry.py`). No SQLite, no `queue.xlsx`,
no per-repo registry. Scrapers own the first eleven columns; this repo owns the
last three and never writes the others.

| Column | Written by |
|---|---|
| Business Name, Category, Lead Type, First Reported At | scraper |
| Has_Website, Phone Number, Email Address, Instagram | scraper |
| Rating, Reviews, Bullet points… | scraper |
| **Message** | `--prep` |
| **Reached** | `--mark-sent` |
| **Do Not Contact** | `--suppress` |

Channel is derived, not stored: an `Email Address` means email, otherwise an
`Instagram` handle means DM, otherwise the lead is phone-only and skipped —
we don't cold-call.

`Do Not Contact` beats everything. A suppressed lead never loads again.

## Why it doesn't send

At ~25 usable leads, automation is the wrong build. Sending by hand is faster
than the automation that would replace it. Gmail cannot tell the difference —
deliverability is decided by domain reputation, authentication, bounce rate and
engagement, not by who pressed the button. And a human in the loop is the only
thing that stops `Hi {{FirstName}},` going out 25 times, which is unrecoverable.

The crossover where automation pays is ~50 sends/day sustained. We are an order
of magnitude below it. **The bottleneck is lead supply, not dispatch.**

Send ~10–15 emails a day from **one** mailbox. That *is* the warmup; no paid
warmup tool is needed. Spreading 25 emails across 5 mailboxes gives all five of
them no reputation at all.

Do **not** route these through Resend. Its AUP prohibits cold outreach to scraped
lists, and it would burn shared IPs. Resend's only job in this project is mailing
the master workbook to you, from inside the scraper repos.

## The purge is the most important part

`/scraper`'s `MOCK_TARGETS` point at `livspace.com`, `haldirams.com` and
`clovedental.in`. Running it with `--mock` harvested those **live corporate
inboxes** into real lead rows. Cold-pitching web design to Haldiram's is a
guaranteed spam complaint with zero upside. `jobs@techmagnate.com` is worse — a
competitor SEO agency's *jobs* inbox.

`leads.py` rejects, before a draft is ever built:

- rows named `Demo *` (every mock row)
- `ENTERPRISE_DOMAINS` — the harvested corporate inboxes, plus ITC Hotels,
  Shangri-La and ALLEN. The list is **manual** and cannot be complete; there is
  no reliable heuristic for "is this a national brand". A household name in the
  `To:` field is the signal to add it.
- `EXCLUDED_KEYWORDS` matched against **the email domain**, not just the business
  name — the name-only check is exactly what let `jobs@techmagnate.com` through
- placeholder addresses scraped off template sites (`sample@mail.com` was really
  in there)
- businesses naming a city outside the service area (`dentalcareudaipur.com`,
  `parthadental.com` → Vizag)

The geography rule rejects domains that *positively name* an outside city. It
does **not** require an NCR keyword: most legitimate NCR domains (`agargca.com`,
`capulkit.com`) name no city at all, so requiring one would reject nearly every
real lead.

## The uncomfortable part: staleness cuts both ways

`/scraper` qualifies a lead by how long its site has been untouched — 400 to
3,233 days in the real data. But an `info@` mailbox on a domain nobody has
touched since 2017 is precisely the profile of a **recycled spam trap**: an
abandoned address a mailbox provider reactivated to catch senders mailing scraped
lists. One trap hit is a Spamhaus listing, and it takes the whole domain with it.

So the signal that makes a business a good **prospect** makes its inbox a bad
**target**. `verify.py`:

- **DROPs** any domain with no MX record (guaranteed bounce — free, via DNS)
- **HOLDs** anything dead longer than `TRAP_RISK_DAYS` (3 years)
- orders the rest **freshest first**

Send in that order, in small batches. If the recent domains bounce, the ancient
ones will bounce harder — verification by observation, and it costs nothing. Paid
verifiers do this better; we have no budget.

## Honest content

The hook is the master's bullet-points column, written by whichever scraper found
the lead. `master_registry.website_bullets()` whitelists only the checkable
observations from `site_audit.py` and drops its **opinions** —
`design/markup looks passable but long-neglected` — and its failure notes.
Quoting one as fact is how you lose a lead. **A lead with no bullets gets no
draft.** Better no email than a wrong one.

The skeleton is chosen by `Has_Website`, not by channel. A no-website business
reached by email must never be told you "had a look at their site" — that single
sentence disqualifies you instantly.

Every message: plain text, **zero links**, no attachments, one specific
observation, one question as the CTA, a soft opt-out. Emails ≤120 words, DMs ≤70.
`validate()` enforces all of it and raises rather than let a broken message reach
your clipboard.

Business names are cleaned first. `Tara Institute® : CTET Coaching, NDA, CDS...`
becomes `Tara Institute` — dropping a raw SEO-stuffed Maps title into an email is
the loudest possible tell that it was scraped.

## Uniqueness is by similarity, not by hash

Two bodies differing by one comma hash differently, so a hash-based "are these
unique?" check passes everything and guarantees nothing. `ledger.py` compares each
draft against every `Message` already in the master with `difflib` and blocks
anything above `SIMILARITY_THRESHOLD` (0.80).

The comparison **strips the shared boilerplate first** (signature, opt-out line).
Those are identical in every draft by design and are a large fraction of a
90-word email; leaving them in drags every pair toward 1.0, and two emails making
completely different points score ~0.90. Stripped, the ratio measures whether the
two messages actually *say* the same thing.

Each lead tries the skeletons in a rotated order and keeps the first that clears
the threshold. If they all collide, the lead is flagged **write this one by
hand** rather than silently sent a near-duplicate.

## Before you send

Open the business's site and confirm the claim. `site_audit.py` is a set of
heuristics, not an oracle. If the draft says "loads over plain HTTP", check the
padlock really is missing. If it's wrong, fix the sentence or skip the lead. That
sixty seconds is not overhead — it's the work, and it's where replies come from.

## Expectation

~25 sendable emails at a good cold reply rate of 5–10% is **one to three
replies**, realistically zero to one client. That is not an argument against
sending them. It is the reason the next thing to build is more lead supply, not a
bigger sender.
