"""Stage 3 — turn a lead into a message a human will read before sending.

The personalisation asset is /scraper's `Website Issues` column, produced by
site_audit.py from the real homepage HTML. Those facts are checkable, which is
the whole point: "you're on HTTP, so Chrome shows a Not secure warning" opens
doors that "we do web design" never will.

But site_audit also emits OPINIONS, and quoting one as fact is how you lose a
lead. `design/markup looks passable but long-neglected` is a judgement, and
`no glaring on-page issues detected` says the opposite of a pitch. So we
whitelist the objectively verifiable fragments and refuse to draft at all when a
lead has none — better no email than a wrong one.

Skeleton rotation: every draft is checked against the ledger for similarity. A
single template would make draft #2 a ~0.9 match for draft #1 and every lead
after the first would be blocked, so each lead tries the skeletons in a rotated
order and keeps the first one that clears the threshold.
"""

import re

import config

# --- Fact extraction --------------------------------------------------------

# Whitelist: (matcher, priority, renderer). Lower priority number = stronger
# hook. Every renderer must produce a clause that reads true from the recipient's
# side, with no link and no jargon they'd have to look up.
_STALE_RE = re.compile(r"untouched for (\d+) days", re.I)
_COPYRIGHT_RE = re.compile(r"copyright stuck at (\d{4})", re.I)

_FACTS: list[tuple[str, int, str]] = [
    ("no https", 1,
     "your site still loads over plain HTTP, so Chrome puts a \"Not secure\" "
     "warning in front of anyone who visits"),
    ("no mobile viewport", 2,
     "the site has no mobile viewport set, so on a phone it renders at "
     "desktop width and visitors have to pinch to read it"),
    ("embeds flash", 3,
     "there's still Flash embedded on the homepage, and no browser has been "
     "able to run it since 2020"),
    ("obsolete 1990s-era html", 4,
     "the homepage is still built with 1990s-era tags like <font> and <center>"),
    ("decade-old jquery", 5,
     "the homepage loads jQuery 1.x, which is about a decade old now"),
    ("missing page title", 6,
     "the homepage has no title tag, so browser tabs and Google results show "
     "a bare URL instead of your name"),
    ("missing meta description", 7,
     "there's no meta description, so Google is writing your search snippet "
     "for you out of whatever text it finds"),
]

# Never quote these. The first is an opinion; the rest describe the audit
# failing, not the site.
_OPINION_FRAGMENTS = (
    "design/markup looks passable",
    "no glaring on-page issues detected",
    "site could not be analyzed",
    "homepage failed to load during scrape",
)

_SUBJECTS = {
    "no https": "your site's security warning",
    "no mobile viewport": "your site on phones",
    "embeds flash": "flash on your site",
    "obsolete 1990s-era html": "your homepage markup",
    "decade-old jquery": "an old script on your site",
    "missing page title": "your google listing",
    "missing meta description": "your google listing",
    "copyright": "your footer year",
    "stale": "your website",
}


def is_opinion_only(lead) -> bool:
    """True when the audit produced nothing but judgement calls. Such a lead has
    no honest hook, and inventing one is how you lose it."""
    issues = (lead.issues or "").lower()
    if not issues:
        return True
    return extract_fact(lead) is None and any(op in issues for op in _OPINION_FRAGMENTS)


def extract_fact(lead) -> tuple[str, str] | None:
    """Best verifiable observation about this lead's site as (key, clause).

    Only the whitelisted fragments above are ever rendered, so an opinion like
    `design/markup looks passable but long-neglected` can never reach a prospect
    even though site_audit.py emits it into the same column.
    """
    issues = (lead.issues or "").lower()

    best: tuple[int, str, str] | None = None
    for key, priority, clause in _FACTS:
        if key in issues and (best is None or priority < best[0]):
            best = (priority, key, clause)
    if best:
        return best[1], best[2]

    year = _COPYRIGHT_RE.search(lead.issues or "")
    if year:
        return "copyright", (f"the footer still reads {year.group(1)}, which tends to "
                             "make people wonder whether you're still open")

    days = _STALE_RE.search(lead.issues or "")
    stale = int(days.group(1)) if days else lead.stale_days
    if stale and stale > 365:
        return "stale", (f"nothing on the site has changed in about "
                         f"{stale // 365} year{'s' if stale >= 730 else ''}")
    return None


# --- Skeletons --------------------------------------------------------------

_EMAIL_SKELETONS = [
    ("Hi,\n\n"
     "I was looking at {business} online and noticed {fact}.\n\n"
     "I build and rebuild websites for small businesses around Delhi NCR. That "
     "particular thing is usually a day's work. Happy to tell you what else I'd "
     "change even if you never hire me.\n\n"
     "Worth a short reply?\n\n"
     "{signature}\n\n"
     "{optout}"),
    ("Hello,\n\n"
     "Quick note about the {business} website — {fact}.\n\n"
     "I'm a web designer here in Delhi. I'd rather point it out than let it keep "
     "costing you visitors. If it's useful I can walk you through what I'd fix "
     "first, no charge for the conversation.\n\n"
     "Any interest?\n\n"
     "{signature}\n\n"
     "{optout}"),
    ("Hi,\n\n"
     "I came across {business} while looking at local businesses, and one thing "
     "stood out: {fact}.\n\n"
     "Rebuilding a site like yours is the sort of work I do. Before you spend "
     "anything, I'm glad to just tell you which parts actually matter and which "
     "don't.\n\n"
     "Would that be useful?\n\n"
     "{signature}\n\n"
     "{optout}"),
    ("Hi there,\n\n"
     "I had a look at the {business} site today. {fact_capitalised}.\n\n"
     "I design websites for local businesses in and around Delhi. Small fixes "
     "like this one usually pay for themselves quickly. I can show you what a "
     "rebuild would look like before you commit to anything.\n\n"
     "Shall I?\n\n"
     "{signature}\n\n"
     "{optout}"),
]

_DM_SKELETONS = [
    ("Hi! Found {business} on Google Maps — {social_proof}, but no website.\n\n"
     "When someone searches for a {category} nearby, they land on whoever has "
     "one. I build them for local businesses here.\n\n"
     "Want me to show you what yours could look like?\n\n"
     "{optout}"),
    ("Hey — {business} came up while I was looking at local businesses. "
     "{social_proof_capitalised}, and no website anywhere.\n\n"
     "That's a lot of people finding you on Maps who can't find you on Google. "
     "I build sites for businesses like yours.\n\n"
     "Interested in seeing one?\n\n"
     "{optout}"),
    ("Hi! {social_proof_capitalised} and still no website — that's the first "
     "thing I noticed about {business}.\n\n"
     "I'm a web designer in Delhi. Happy to mock something up so you can see it "
     "before deciding anything.\n\n"
     "Worth a look?\n\n"
     "{optout}"),
]

# Defined in config so ledger.py can strip them before comparing similarity.
_EMAIL_OPTOUT = config.EMAIL_OPTOUT
_DM_OPTOUT = config.DM_OPTOUT


def _social_proof(lead) -> str:
    if lead.rating and lead.reviews:
        return f"{lead.rating} stars from {lead.reviews:,} reviews"
    if lead.reviews:
        return f"{lead.reviews:,} reviews"
    if lead.rating:
        return f"rated {lead.rating} stars"
    return "people clearly rate you"


def _capitalise(clause: str) -> str:
    return clause[0].upper() + clause[1:] if clause else clause


class DraftError(Exception):
    """This lead cannot be drafted honestly."""


def _render_email(lead, skeleton: str, fact: str) -> tuple[str, str]:
    key, clause = fact
    body = skeleton.format(
        business=lead.business,
        fact=clause,
        fact_capitalised=_capitalise(clause),
        signature=config.SIGNATURE,
        optout=_EMAIL_OPTOUT,
    )
    return _SUBJECTS.get(key, "your website"), body


def _render_dm(lead, skeleton: str) -> tuple[str, str]:
    proof = _social_proof(lead)
    body = skeleton.format(
        business=lead.business,
        category=(lead.category or "business").lower(),
        social_proof=proof,
        social_proof_capitalised=_capitalise(proof),
        optout=_DM_OPTOUT,
    )
    return "", body


def validate(body: str, channel: str) -> None:
    """Hard rules. Raise rather than let a broken message reach a human's clipboard."""
    lowered = body.lower()
    for bad in config.FORBIDDEN_SUBSTRINGS:
        if bad.lower() in lowered:
            raise DraftError(f"contains forbidden substring {bad!r}")
    cap = (config.EMAIL_MAX_WORDS if channel == config.CHANNEL_EMAIL
           else config.DM_MAX_WORDS)
    words = len(body.split())
    if words > cap:
        raise DraftError(f"{words} words exceeds the {cap}-word cap for {channel}")


def build(lead, ledger, attempt_order: int = 0) -> tuple[str, str]:
    """Draft (subject, body) for one lead, rotating skeletons until one is unique.

    Raises DraftError if the lead has no verifiable fact, or if every skeleton
    collides with something already sent. A collision is not a reason to send a
    near-duplicate — it's a reason to write that one by hand.
    """
    if lead.channel == config.CHANNEL_EMAIL:
        fact = extract_fact(lead)
        if not fact:
            raise DraftError("no verifiable fact about this site — refusing to "
                             "invent one; write this lead by hand")
        skeletons = _EMAIL_SKELETONS
    else:
        fact = None
        skeletons = _DM_SKELETONS

    collisions = []
    for i in range(len(skeletons)):
        skeleton = skeletons[(attempt_order + i) % len(skeletons)]
        subject, body = (_render_email(lead, skeleton, fact) if fact
                         else _render_dm(lead, skeleton))
        validate(body, lead.channel)
        similar = ledger.most_similar(body)
        if similar is None or similar[1] < config.SIMILARITY_THRESHOLD:
            return subject, body
        collisions.append(f"{similar[1]:.2f} vs {similar[0]}")

    raise DraftError("every skeleton is too similar to an already-sent message "
                     f"({'; '.join(collisions)}) — write this one by hand")
