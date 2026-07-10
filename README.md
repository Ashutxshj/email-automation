# email-automation — a draft-prep tool that never sends

Reads leads from the one master workbook, has **Gemini** write a personalised
message per business (grounded in its rating, reviews, category and the
scraper's bullet points), writes each lead's `Message` + `Channel` back into
the workbook, and prints a human-readable copy for you to review.
**There is no `--send` flag, and there must never be one.** Gemini only writes
drafts; a human reads and pastes every single one.

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt

python main.py --prep                # Gemini-draft Message + Channel + drafts.md
python main.py --prep --limit 10     # a day's batch
python main.py --prep --redraft      # regenerate rows that already have a Message
python main.py --prep --no-llm       # offline template drafts (no Gemini)
python main.py --prep --mock-llm     # fake Gemini: test the pipeline, zero quota
python main.py --mark-sent <ident>   # Reached = TRUE
python main.py --suppress <ident>    # Do Not Contact = TRUE
python main.py --stats
```

`<ident>` is an email address, an `@handle`, or a 10-digit phone number.

## Gemini setup (one-time)

Get a **free** API key at <https://aistudio.google.com/apikey> (no billing
needed) and put it in a `.env` file in this repo (gitignored):

```
GEMINI_API_KEY=your-key-here
```

Model: `gemini-3.1-flash-lite` (override with `GEMINI_MODEL=`; 2.5-flash-lite
404s for accounts created after mid-2026). Quota math on
the free tier (~15 requests/min, ~1,000/day): leads are batched 8 per request,
so drafting the whole 82-lead workbook is **~11 requests**, and because `--prep`
skips rows that already have a `Message`, the steady state after a scraper
import is 1–2 requests. Requests are paced 5 s apart (~12 RPM) and 429s are
retried with backoff, so a full run finishes in about a minute and never trips
the limit. Every run prints `[gemini] N requests, ~M tokens` so you can see
exactly what it cost.

No key, or offline? `--no-llm` falls back to the built-in template skeletons
(limited: with only a few skeletons, most leads in a big batch collide with the
similarity gate and get flagged for hand-writing — Gemini is the fix for that).

## One file holds everything

`Projects/leads_master.xlsx` (`master_registry.py`). No SQLite, no `queue.xlsx`,
no per-repo registry. Scrapers own the first eleven columns; this repo owns the
last four and never writes the others.

| Column | Written by |
|---|---|
| Business Name, Category, Lead Type, First Reported At | scraper |
| Has_Website, Phone Number, Email Address, Instagram | scraper |
| Rating, Reviews, Bullet points… | scraper |
| **Message** | `--prep` |
| **Reached** | `--mark-sent` |
| **Do Not Contact** | `--suppress` |
| **Channel** | `--prep` — where to paste: `Email` / `Instagram DM` / `WhatsApp` |

`Channel` was appended at the **end** of the sheet on purpose: the scraper repos
carry older copies of `master_registry.py` that read the header from the file,
so a trailing column they don't know about is simply ignored. (Still, per the
change-one-change-all rule, copy the updated `master_registry.py` into
`/scraper`, `/scraper2` and `/scraper3` when convenient.)

Channel priority per lead — what's available decides what gets drafted:

1. `Instagram` handle → **one-line DM**
2. else `Email Address` → **~50-word email** (the `Message` cell embeds the
   subject as a `Subject: …` first line, so one cell is one paste)
3. else `Phone Number` → **one-line WhatsApp message**

Phone-only leads used to be skipped; they are now WhatsApp leads by explicit
decision. `Do Not Contact` still beats everything. A suppressed lead never
loads again.

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
Quoting one as fact is how you lose a lead. Better no email than a wrong one.

Gemini is boxed in the same way (`generate.py` + `draft.validate_llm()`):

- the prompt forbids inventing anything and requires citing a provided fact;
  a lead whose `has_website` is false is never told you "looked at their site"
- `validate_llm()` **re-checks every number**: a draft claiming "4.8 stars" or
  "99 reviews" that doesn't exactly match the row's `Rating`/`Reviews` is
  rejected and regenerated — a plausible-but-wrong number is worse than none
- a draft citing no concrete fact at all (rating, review count, category or a
  bullet) is rejected too
- emails are 25–60 words with a 2–5 word subject; DMs and WhatsApp messages are
  a **single line, ≤200 chars** — anything else regenerates
- the signature and opt-out are appended by code, never written by the model

Every message: plain text, **zero links**, no attachments, one specific
observation, one question as the CTA. `validate()` / `validate_llm()` enforce
all of it and raise rather than let a broken message reach your clipboard.

Business names are cleaned first. `Tara Institute® : CTET Coaching, NDA, CDS...`
becomes `Tara Institute` — dropping a raw SEO-stuffed Maps title into an email is
the loudest possible tell that it was scraped.

## Uniqueness is by similarity, not by hash

Two bodies differing by one comma hash differently, so a hash-based "are these
unique?" check passes everything and guarantees nothing. `ledger.py` compares each
draft against every `Message` already in the master with `difflib` and blocks
anything above `SIMILARITY_THRESHOLD` (0.80). The comparison runs with
`autojunk=False` and takes the max of both argument orders — the difflib
defaults silently collapsed the ratio for email-length bodies and made
near-threshold results depend on drafting order. A separate gate rejects any
draft whose **first five words** match an existing message's opening, which
similarity alone misses on short one-liners.

The comparison **strips the shared boilerplate first** (signature, opt-out line).
Those are identical in every draft by design and are a large fraction of a
90-word email; leaving them in drags every pair toward 1.0, and two emails making
completely different points score ~0.90. Stripped, the ratio measures whether the
two messages actually *say* the same thing.

Every Gemini draft goes through the same gate, plus an in-batch one (two leads
in one run can't receive near-twins either). A collision is quoted back to the
model — "too similar to a message already sent, take a different angle" — for
up to `REGEN_ROUNDS` regenerations. Each lead also gets a rotating *angle*
(rating / review count / what they sell / website gap) so a batch can't
converge on one hook in the first place. If a lead still can't clear the
threshold it is flagged **write this one by hand** rather than silently sent a
near-duplicate. The `--no-llm` template path keeps the old skeleton-rotation
behaviour.

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
