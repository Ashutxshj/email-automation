"""Stage 1 — read leads from the ONE master workbook, then purge what must
never be contacted.

Source: Projects/leads_master.xlsx (master_registry.py). Every scraper appends
to it; nothing here writes the scraper-owned columns.

Channel is derived here (and recorded by --prep in the master's Channel column):
  * an Instagram      -> DM        (one-line message, pasted by hand)
  * else an Email     -> email     (proper short email)
  * else a Phone      -> WhatsApp  (one-line message, pasted by hand)
  * else               -> unreachable; skipped

The purge is the single most important thing in this repo. /scraper's mock
targets point at livspace.com, haldirams.com and clovedental.com; running it with
--mock harvested those live corporate inboxes into real lead rows. Mailing them
from a cold domain is a guaranteed spam complaint with no upside.
"""

import re
from dataclasses import dataclass, field

import config
import master_registry

# Google Maps titles are SEO-stuffed: "Turning Point Institute - Best IIT JEE
# NEET CBSE Coaching Center in Paschim Vihar Delhi". Dropping that whole string
# into an email is the loudest possible tell that it was scraped and automated.
# The real name is everything before the first separator.
_NAME_SEPARATOR_RE = re.compile(r"\s+[-–—]\s+|\s*[|:]\s*")
_TRAILING_PAREN_RE = re.compile(r"\s*\([^)]*\)\s*$")
_TRADEMARK_RE = re.compile(r"[®™©]")
_STALE_DAYS_RE = re.compile(r"\((\d+)\s+days\)")


def clean_business(name: str) -> str:
    """'Tara Institute® : CTET Coaching, NDA, CDS...' -> 'Tara Institute'."""
    cleaned = _TRADEMARK_RE.sub("", str(name or "")).strip()
    cleaned = _NAME_SEPARATOR_RE.split(cleaned, maxsplit=1)[0].strip()
    cleaned = _TRAILING_PAREN_RE.sub("", cleaned).strip()
    return cleaned or str(name or "").strip()


@dataclass
class Lead:
    channel: str
    identifier: str          # email address, @handle, or 10-digit phone
    business: str
    category: str = ""
    lead_type: str = ""      # Goldenrod / New Bark / Stale Website
    domain: str = ""         # email domain, '' for DM leads
    phone: str = ""
    has_website: bool = False
    bullets: list[str] = field(default_factory=list)
    stale_days: int | None = None
    rating: str = ""
    reviews: int = 0
    message: str = ""        # already-written Message from the master, if any
    reached: bool = False    # the master's Reached column

    @property
    def is_role_address(self) -> bool:
        """info@, contact@, sales@ ... — low reply rate, often a catch-all."""
        local = self.identifier.split("@")[0].lower()
        return local in {"info", "contact", "admin", "support", "sales", "office",
                         "enquiry", "enquiries", "care", "hello", "mail", "jobs"}


def _domain(email: str) -> str:
    return email.split("@")[-1].strip().lower() if "@" in email else ""


def _keyword_hit(*fields: str) -> str | None:
    hay = " ".join(f.lower() for f in fields if f)
    return next((kw for kw in config.EXCLUDED_KEYWORDS if kw in hay), None)


def _out_of_area(*fields: str) -> str | None:
    hay = " ".join(f.lower() for f in fields if f)
    return next((c for c in config.OUT_OF_AREA_CITIES if c in hay), None)


def rejection_reason(business: str, identifier: str, domain: str) -> str | None:
    """Why this lead must never be contacted, or None if it's safe to draft."""
    name = str(business or "").strip().lower()
    if not name:
        return "no business name"
    if name.startswith(config.MOCK_NAME_PREFIXES):
        return "mock/demo row from a --mock scraper run"
    if domain and domain in config.ENTERPRISE_DOMAINS:
        return f"enterprise/competitor domain ({domain})"
    if "@" in identifier and not identifier.startswith("@"):
        local = identifier.split("@")[0].strip().lower()
        if local in config.JUNK_LOCALPARTS:
            return f"placeholder address scraped from a template site ({identifier})"
        if domain in config.JUNK_DOMAINS:
            return f"placeholder domain ({domain})"
    # Name AND domain: the name-only check is what let jobs@techmagnate.com pass.
    kw = _keyword_hit(business, domain)
    if kw:
        return f"sells tech/marketing services (matched '{kw}')"
    city = _out_of_area(business, domain)
    if city:
        return f"outside Delhi NCR (names '{city}')"
    return None


def _bullets(raw) -> list[str]:
    return [b.lstrip("• ").strip() for b in str(raw or "").split("\n") if b.strip()]


def _stale_days(bullets: list[str]) -> int | None:
    """The scraper encodes staleness into a bullet: '... (416 days)'."""
    for bullet in bullets:
        match = _STALE_DAYS_RE.search(bullet)
        if match:
            return int(match.group(1))
    return None


def _reviews(raw) -> int:
    try:
        return int(float(raw or 0))
    except (TypeError, ValueError):
        return 0


def load_all() -> tuple[list[Lead], list[tuple[str, str]]]:
    """(contactable leads, [(identifier, rejection_reason), ...]) from the master."""
    kept: list[Lead] = []
    rejected: list[tuple[str, str]] = []

    for row in master_registry.load_rows():
        if master_registry.is_true(row.get("Do Not Contact")):
            continue  # opted out; not a rejection, just permanently off-limits

        email = master_registry.norm_email(row.get("Email Address"))
        handle = str(row.get("Instagram") or "").strip()
        phone = master_registry.norm_phone(row.get("Phone Number"))
        business = str(row.get("Business Name") or "").strip()

        if handle:
            channel, identifier, domain = config.CHANNEL_INSTAGRAM, handle, ""
        elif email:
            channel, identifier, domain = config.CHANNEL_EMAIL, email, _domain(email)
        elif len(phone) == 10:
            channel, identifier, domain = config.CHANNEL_WHATSAPP, phone, ""
        else:
            continue  # no usable contact channel at all

        # Purge on the email domain even when the chosen channel isn't email —
        # a DM to an enterprise or a competitor is just as pointless.
        reason = rejection_reason(business, identifier, _domain(email))
        if reason:
            rejected.append((identifier, reason))
            continue

        bullets = _bullets(row.get(master_registry.BULLETS_COLUMN))
        kept.append(Lead(
            channel=channel,
            identifier=identifier,
            business=clean_business(business),
            category=str(row.get("Category") or "").strip(),
            lead_type=str(row.get("Lead Type") or "").strip(),
            domain=domain,
            phone=str(row.get("Phone Number") or "").strip(),
            has_website=master_registry.is_true(row.get("Has_Website")),
            bullets=bullets,
            stale_days=_stale_days(bullets),
            rating=str(row.get("Rating") or "").strip(),
            reviews=_reviews(row.get("Reviews")),
            message=str(row.get("Message") or "").strip(),
            reached=master_registry.is_true(row.get("Reached")),
        ))
    return kept, rejected
