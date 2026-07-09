# email-automation — a draft-prep tool that never sends

Prepares cold outreach for a human to read and paste. **There is no `--send`
flag, and there must never be one.**

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt

python main.py --prep                # build drafts.md + queue.xlsx
python main.py --prep --limit 10     # a day's batch
python main.py --mark-sent <ident>   # record what you actually sent
python main.py --suppress <ident>    # permanent opt-out, all channels
python main.py --stats
```

## Why it doesn't send

At ~25 usable leads, automation is the wrong build. Sending by hand is faster
than the automation that would replace it. Gmail cannot tell the difference —
deliverability is decided by domain reputation, authentication, bounce rate and
engagement, not by who pressed the button. And a human in the loop is the only
thing that stops `Hi {{FirstName}},` going out 25 times, which is unrecoverable.

The crossover where automation starts to pay is ~50 sends/day sustained. We are
an order of magnitude below it. **The bottleneck is lead supply, not dispatch.**

Send ~10–15 emails a day from **one** mailbox. That *is* the warmup; no paid
warmup tool is needed. Spreading 25 emails across 5 mailboxes gives all five of
them no reputation at all.

Do **not** route these through Resend. Its AUP prohibits cold outreach to scraped
lists, and it would burn shared IPs. Resend's only job in this project is mailing
lead reports to you, from inside the scraper repos.

## Channels

| Source | Channel | Pitch |
|---|---|---|
| `/scraper` | Email | They *have* a stale site → a redesign, anchored on a real audited fault |
| `/scraper3` | Instagram DM | They have *no* site → why having one helps, anchored on their rating |

## The purge is the most important part

`/scraper`'s `MOCK_TARGETS` point at `livspace.com`, `haldirams.com` and
`clovedental.in`. Running it with `--mock` harvested those **live corporate
inboxes** into the real output CSVs. Cold-pitching web design to Haldiram's is a
guaranteed spam complaint with zero upside. `jobs@techmagnate.com` is worse — a
competitor SEO agency's *jobs* inbox.

`leads.py` rejects, before a draft is ever built:

- rows named `Demo *` (every mock row)
- `ENTERPRISE_DOMAINS` (the harvested corporate inboxes + ITC Hotels)
- `EXCLUDED_KEYWORDS` matched against **the email domain**, not just the business
  name — the name-only check is exactly what let `jobs@techmagnate.com` through
- placeholder addresses scraped off template sites (`sample@mail.com` was really
  in there)
- businesses naming a city outside the service area (`dentalcareudaipur.com`,
  `parthadental.com` → Vizag)

Note the geography rule rejects domains that *positively name* an outside city.
It does **not** require an NCR keyword to be present: most legitimate NCR domains
(`agargca.com`, `capulkit.com`) name no city at all, so requiring one would
reject nearly every real lead.

## The uncomfortable part: staleness cuts both ways

`/scraper` qualifies a lead by how long its site has been untouched — 400 to
3,233 days in the current data. But an `info@` mailbox on a domain nobody has
touched since 2017 is precisely the profile of a **recycled spam trap**: an
abandoned address a mailbox provider reactivated to catch senders mailing
scraped lists. One trap hit is a Spamhaus listing, and it takes the whole domain
with it.

So the signal that makes a business a good **prospect** makes its inbox a bad
**target**. `verify.py` therefore:

- **DROPs** any domain with no MX record (guaranteed bounce — free, via DNS)
- **HOLDs** anything dead longer than `TRAP_RISK_DAYS` (3 years)
- orders the rest **freshest first**

Send in that order, in small batches. If the recent domains bounce, the ancient
ones will bounce harder — that is verification by observation, and it costs
nothing. Paid verifiers do this better; we have no budget.

## Honest content

The personalisation asset is `/scraper`'s `Website Issues` column, produced by
`site_audit.py` from the real homepage HTML. Those facts are checkable.

But `site_audit.py` also emits **opinions**, and quoting one as fact is how you
lose a lead. `draft.py` whitelists only the verifiable fragments (no HTTPS, no
mobile viewport, Flash, obsolete tags, old jQuery, stuck copyright year, missing
title/description) and **refuses to draft at all** when a lead has none. Better
no email than a wrong one. Telling a dentist his site is broken when it isn't
costs you the lead and earns a complaint.

Every message: plain text, **zero links**, no attachments, one specific
observation, one question as the CTA, a soft opt-out. Emails ≤120 words, DMs ≤70.
`validate()` enforces all of it and raises rather than let a broken message reach
your clipboard.

Business names are cleaned before use. `Tara Institute® : CTET Coaching, NDA,
CDS, AFCAT...` becomes `Tara Institute` — dropping a raw SEO-stuffed Maps title
into an email is the loudest possible tell that it was scraped.

## Uniqueness is by similarity, not by hash

Two bodies differing by one comma hash differently, so a hash-based "are these
unique?" check passes everything and guarantees nothing. `ledger.py` compares the
rendered body against every prior message with `difflib` and blocks anything
above `SIMILARITY_THRESHOLD` (0.80).

The comparison **strips the shared boilerplate first** (signature, opt-out line).
Those are identical in every draft by design and are a large fraction of a
90-word email; leaving them in drags every pair toward 1.0, and two emails making
completely different points score ~0.90. Stripped, the ratio measures whether the
two messages actually *say* the same thing.

Each lead tries the skeletons in a rotated order and keeps the first that clears
the threshold. If they all collide, the lead is flagged **write this one by
hand** rather than silently sent a near-duplicate.

## Storage

SQLite (`outreach.db`, WAL), not a spreadsheet. A crash between "sent the email"
and "saved the workbook" loses the write, and a lost write means the next run
**double-sends to a live prospect**. `queue.xlsx` is generated *from* the DB, for
reading.

`outreach.db` is the only record of who has actually been contacted. The
scrapers' `reported_businesses.xlsx` / `contacted_businesses.xlsx` mean something
else entirely — "already included in a report emailed to *you*" — and a business
can appear there having never been contacted.

## Expectation

~25 sendable emails at a good cold reply rate of 5–10% is **one to three
replies**, realistically zero to one client. That is not an argument against
sending them. It is the reason the next thing to build is more lead supply, not a
bigger sender.
