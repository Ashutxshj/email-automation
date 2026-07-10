"""Stage 3 — turn a lead into a message a human will read before sending.

The personalisation asset is the master file's bullet-points column, written by
whichever scraper found the lead. Those bullets are already restricted to
verifiable claims — master_registry.website_bullets() drops site_audit.py's
opinions ("design/markup looks passable but long-neglected") and its failure
notes ("site could not be analyzed"), because quoting one of those as fact is
how you lose a lead. A lead with no bullets gets no draft; better no email than
a wrong one.

Skeleton rotation: every draft is checked for similarity against every Message
already in the master. A single template would make draft #2 a ~0.9 match for
draft #1 and every lead after the first would be blocked, so each lead tries the
skeletons in a rotated order and keeps the first that clears the threshold.
"""

import re

import config

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

# A no-website business reached by EMAIL. Same pitch as a DM (why a site helps),
# but at email length. Selecting the redesign skeletons here would tell someone
# with no website that you "had a look at their site" — instantly disqualifying.
_EMAIL_NO_SITE_SKELETONS = [
    ("Hi,\n\n"
     "I was looking up {business} and noticed {fact}.\n\n"
     "I build websites for small businesses around Delhi NCR. When people search "
     "for a {category} nearby, they tend to land on whoever has one. Happy to "
     "show you what yours could look like before you commit to anything.\n\n"
     "Worth a short reply?\n\n"
     "{signature}\n\n"
     "{optout}"),
    ("Hello,\n\n"
     "Quick note about {business} — {fact}.\n\n"
     "I'm a web designer here in Delhi. A simple site would let you show timings, "
     "prices and directions to the people already looking for you. I can mock one "
     "up so you can see it first, no charge for that.\n\n"
     "Any interest?\n\n"
     "{signature}\n\n"
     "{optout}"),
    ("Hi,\n\n"
     "I came across {business} while looking at local businesses, and one thing "
     "stood out: {fact}.\n\n"
     "That's a lot of people finding you on Maps who can't find you anywhere "
     "else. Building sites for businesses like yours is what I do, and I'd rather "
     "show you one than describe it.\n\n"
     "Would that be useful?\n\n"
     "{signature}\n\n"
     "{optout}"),
]

_DM_SKELETONS = [
    ("Hi! Found {business} on Google Maps — {fact_lower}.\n\n"
     "When someone searches for a {category} nearby, they land on whoever has a "
     "site. I build them for local businesses here.\n\n"
     "Want me to show you what yours could look like?\n\n"
     "{optout}"),
    ("Hey — {business} came up while I was looking at local businesses. "
     "{fact_capitalised}.\n\n"
     "That's a lot of people finding you on Maps who can't find you on Google. "
     "I build sites for businesses like yours.\n\n"
     "Interested in seeing one?\n\n"
     "{optout}"),
    ("Hi! {fact_capitalised} — that's the first thing I noticed about "
     "{business}.\n\n"
     "I'm a web designer in Delhi. Happy to mock something up so you can see it "
     "before deciding anything.\n\n"
     "Worth a look?\n\n"
     "{optout}"),
]

# Subject lines are chosen off the bullet's content: lowercase, 2-5 words, no
# marketing vocabulary, looks like a person wrote it in a hurry.
_SUBJECT_KEYS = [
    ("not secure", "your site's security warning"),
    ("mobile viewport", "your site on phones"),
    ("flash", "flash on your site"),
    ("1990s-era", "your homepage markup"),
    ("jquery", "an old script on your site"),
    ("title tag", "your google listing"),
    ("meta description", "your google listing"),
    ("copyright", "your footer year"),
    ("changed in", "your website"),
]


def _capitalise(clause: str) -> str:
    return clause[0].upper() + clause[1:] if clause else clause


def _decapitalise(clause: str) -> str:
    """'Rated 4.8 stars...' -> 'rated 4.8 stars...' for mid-sentence use."""
    if not clause:
        return clause
    # Don't lowercase an acronym or a digit-led clause.
    return clause[0].lower() + clause[1:] if clause[:2].istitle() else clause


def _subject(bullet: str) -> str:
    lowered = bullet.lower()
    for key, subject in _SUBJECT_KEYS:
        if key in lowered:
            return subject
    return "your website"


class DraftError(Exception):
    """This lead cannot be drafted honestly."""


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


# --- Gemini-drafted messages -------------------------------------------------

# "4.8 stars" / "4.8-star" / "rated 4.8" and "732 reviews" / "900+ reviews" /
# "732 five-star reviews" claims. Any such number in a draft must equal the
# row's Rating / Reviews exactly — a plausible-but-wrong number is worse than
# no number.
_STARS_RE = re.compile(r"(\d+(?:\.\d+)?)[ -]stars?\b", re.I)
_RATED_RE = re.compile(r"\brated\s+(\d+(?:\.\d+)?)\b", re.I)
_REVIEWS_RE = re.compile(r"([\d,]+)\+?\s+(?:[\w'-]+\s+)?reviews?\b", re.I)

# Language that implies you SAW a website. Allowed when they have one; a lead
# with no website told "your site looks dated" disqualifies you instantly.
_SITE_VISIT_PHRASES = (
    "visited your", "had a look at your", "looked at your", "checked your",
    "saw your site", "saw your website", "your site loads", "your website loads",
    "your site looks", "your website looks", "your site is", "your website is",
    "your current site", "your current website", "your existing site",
    "your existing website", "your homepage", "on your site", "on your website",
)


def _same_number(claimed: str, actual) -> bool:
    try:
        return abs(float(str(claimed).replace(",", "")) - float(actual)) < 1e-9
    except (TypeError, ValueError):
        return False


def _mentions_specifics(lead, body: str) -> bool:
    """Does the body cite at least one concrete fact from the row?"""
    lowered = body.lower()
    if lead.rating and any(_same_number(m.group(1), lead.rating)
                           for m in _STARS_RE.finditer(body)):
        return True
    if lead.reviews and (f"{lead.reviews:,}" in body or str(lead.reviews) in body):
        return True
    if any(len(tok) > 3 and tok in lowered
           for tok in (lead.category or "").lower().split()):
        return True
    for bullet in lead.bullets:
        distinctive = [w for w in re.findall(r"[a-z]{5,}", bullet.lower())
                       if w in lowered]
        if len(distinctive) >= 2:
            return True
    return False


def validate_llm(lead, subject: str, body: str) -> None:
    """Hard rules for a Gemini draft. Raise rather than trust the model."""
    haystack = f"{subject}\n{body}".lower()
    for bad in config.FORBIDDEN_SUBSTRINGS:
        if bad.lower() in haystack:
            raise DraftError(f"contains forbidden substring {bad!r}")

    if lead.channel == config.CHANNEL_EMAIL:
        words = len(body.split())
        if words > config.LLM_EMAIL_MAX_WORDS:
            raise DraftError(f"{words} words exceeds the "
                             f"{config.LLM_EMAIL_MAX_WORDS}-word email cap")
        if words < config.LLM_EMAIL_MIN_WORDS:
            raise DraftError(f"{words} words is a stub, not an email")
        if not subject.strip():
            raise DraftError("email draft has no subject")
        if "\n" in subject or len(subject.split()) > 6:
            raise DraftError(f"subject {subject!r} should be a few plain words")
    else:
        if "\n" in body.strip():
            raise DraftError("DM/WhatsApp message must be a single line")
        if len(body) > config.ONE_LINER_MAX_CHARS:
            raise DraftError(f"{len(body)} chars exceeds the "
                             f"{config.ONE_LINER_MAX_CHARS}-char one-liner cap")

    text = f"{subject}\n{body}"  # numbers in the subject count too
    for pattern in (_STARS_RE, _RATED_RE):
        for match in pattern.finditer(text):
            if not lead.rating or not _same_number(match.group(1), lead.rating):
                raise DraftError(f"claims '{match.group(0)}' but the row says "
                                 f"rating={lead.rating or 'unknown'}")
    for match in _REVIEWS_RE.finditer(text):
        if not lead.reviews or not _same_number(match.group(1), lead.reviews):
            raise DraftError(f"claims '{match.group(0)}' but the row says "
                             f"reviews={lead.reviews or 'unknown'}")

    if not lead.has_website:
        hit = next((p for p in _SITE_VISIT_PHRASES if p in haystack), None)
        if hit:
            raise DraftError(f"implies you saw a website ('{hit}') but this "
                             "business has none")

    if not _mentions_specifics(lead, body):
        raise DraftError("cites no concrete fact about this business "
                         "(rating, reviews, category or a bullet)")


def compose_message(lead, subject: str, body: str) -> str:
    """The exact text for the Message cell — what a human copies and pastes.

    Boilerplate is appended HERE, deterministically, never by Gemini: that keeps
    ledger._comparable()'s boilerplate stripping exact.
    """
    if lead.channel == config.CHANNEL_EMAIL:
        return (f"Subject: {subject}\n\n{body}\n\n"
                f"{config.SIGNATURE}\n\n{config.EMAIL_OPTOUT}")
    if config.ONE_LINER_INCLUDE_OPTOUT:
        return f"{body} {config.DM_OPTOUT}"
    return body


def _render(lead, skeleton: str, bullet: str) -> str:
    return skeleton.format(
        business=lead.business,
        category=(lead.category or "business").lower(),
        fact=_decapitalise(bullet),
        fact_lower=_decapitalise(bullet),
        fact_capitalised=_capitalise(bullet),
        signature=config.SIGNATURE,
        optout=(config.EMAIL_OPTOUT if lead.channel == config.CHANNEL_EMAIL
                else config.DM_OPTOUT),
    )


def build(lead, ledger, attempt_order: int = 0) -> tuple[str, str]:
    """Draft (subject, body) for one lead, rotating skeletons until one is unique.

    Raises DraftError if the lead has no bullet to anchor on, or if every
    skeleton collides with a Message already in the master. A collision is not a
    reason to send a near-duplicate — it's a reason to write that one by hand.
    """
    if not lead.bullets:
        raise DraftError("no verifiable bullet points for this business — "
                         "refusing to invent one; write this lead by hand")

    bullet = lead.bullets[0]  # scrapers emit the strongest hook first
    # Chosen by whether they HAVE a site, not by channel. A no-website business
    # reached by email must not be told you looked at their website.
    if lead.channel != config.CHANNEL_EMAIL:
        skeletons, subject = _DM_SKELETONS, ""
    elif lead.has_website:
        skeletons, subject = _EMAIL_SKELETONS, _subject(bullet)
    else:
        skeletons, subject = _EMAIL_NO_SITE_SKELETONS, "your website"

    collisions = []
    for i in range(len(skeletons)):
        body = _render(lead, skeletons[(attempt_order + i) % len(skeletons)], bullet)
        validate(body, lead.channel)
        similar = ledger.most_similar(body, exclude=lead.identifier)
        if similar is None or similar[1] < config.SIMILARITY_THRESHOLD:
            return subject, body
        collisions.append(f"{similar[1]:.2f} vs {similar[0]}")

    raise DraftError("every skeleton is too similar to an existing message "
                     f"({'; '.join(collisions)}) — write this one by hand")
