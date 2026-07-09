"""Stage 1 — load leads from the scraper repos, then purge what must never be contacted.

Sources (read-only):
  * /scraper/output/delhi_ncr_leads_*.csv        -> email channel  (they HAVE a
    stale website, so the pitch is a redesign, anchored on a real audited fault)
  * /scraper3/output/delhi_ncr_instagram_leads_*.csv -> Instagram DM channel
    (no website at all, so the pitch is why having one helps)

The purge is the single most important thing in this repo. /scraper's mock
targets point at livspace.com, haldirams.com and clovedental.com; running it with
--mock harvested those live corporate inboxes into the real output CSVs. Mailing
them from a cold domain is a guaranteed spam complaint with no upside.
"""

import csv
import glob
import os
import re
from dataclasses import dataclass, field

import config

_STALE_DAYS_RE = re.compile(r"\((\d+)\s+days ago", re.I)

# Google Maps titles are SEO-stuffed: "Turning Point Institute - Best IIT JEE
# NEET CBSE Coaching Center in Paschim Vihar Delhi". Dropping that whole string
# into an email is the loudest possible tell that it was scraped and automated.
# The real name is everything before the first separator.
_NAME_SEPARATOR_RE = re.compile(r"\s+[-–—]\s+|\s*[|:]\s*")
_TRAILING_PAREN_RE = re.compile(r"\s*\([^)]*\)\s*$")
_TRADEMARK_RE = re.compile(r"[®™©]")


def clean_business(name: str) -> str:
    """'Tara Institute® : CTET Coaching, NDA, CDS...' -> 'Tara Institute'."""
    cleaned = _TRADEMARK_RE.sub("", name or "").strip()
    cleaned = _NAME_SEPARATOR_RE.split(cleaned, maxsplit=1)[0].strip()
    cleaned = _TRAILING_PAREN_RE.sub("", cleaned).strip()
    return cleaned or (name or "").strip()


@dataclass
class Lead:
    channel: str
    identifier: str          # email address, or @handle
    business: str
    category: str = ""
    domain: str = ""         # email domain, '' for DM leads
    phone: str = ""
    issues: str = ""         # /scraper's audited "Website Issues" line
    stale_days: int | None = None
    rating: str = ""
    reviews: int = 0
    source: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def is_role_address(self) -> bool:
        """info@, contact@, sales@ ... — low reply rate, often a catch-all."""
        local = self.identifier.split("@")[0].lower()
        return local in {"info", "contact", "admin", "support", "sales", "office",
                         "enquiry", "enquiries", "care", "hello", "mail", "jobs"}


def _stale_days(last_updated: str) -> int | None:
    match = _STALE_DAYS_RE.search(last_updated or "")
    return int(match.group(1)) if match else None


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
    name = (business or "").strip().lower()
    if not name:
        return "no business name"
    if name.startswith(config.MOCK_NAME_PREFIXES):
        return "mock/demo row from a --mock scraper run"
    if domain and domain in config.ENTERPRISE_DOMAINS:
        return f"enterprise/competitor domain ({domain})"
    if "@" in identifier:
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


def _csv_files(directory: str, pattern: str) -> list[str]:
    """Newest first, skipping the *_latest.csv copy (it duplicates a stamped file)."""
    files = [f for f in glob.glob(os.path.join(directory, pattern))
             if not f.endswith("_latest.csv")]
    return sorted(files, reverse=True)


def load_email_leads() -> tuple[list[Lead], list[tuple[str, str]]]:
    """Leads from /scraper. Returns (kept, [(identifier, rejection_reason), ...])."""
    kept: dict[str, Lead] = {}
    rejected: list[tuple[str, str]] = []
    seen: set[str] = set()

    for path in _csv_files(config.SCRAPER_OUTPUT_DIR, config.SCRAPER_GLOB):
        with open(path, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                email = (row.get("Email") or "").strip().lower()
                if not email or "@" not in email or email in seen:
                    continue
                seen.add(email)
                business = (row.get("Business Name") or "").strip()
                domain = _domain(email)
                reason = rejection_reason(business, email, domain)
                if reason:
                    rejected.append((email, reason))
                    continue
                kept[email] = Lead(
                    channel=config.CHANNEL_EMAIL,
                    identifier=email,
                    business=clean_business(business),
                    category=(row.get("Category") or "").strip(),
                    domain=domain,
                    phone=(row.get("Phone Number") or "").strip(),
                    issues=(row.get("Website Issues") or "").strip(),
                    stale_days=_stale_days(row.get("Last Updated") or ""),
                    source=os.path.basename(path),
                )
    return list(kept.values()), rejected


def load_dm_leads() -> tuple[list[Lead], list[tuple[str, str]]]:
    """Leads from /scraper3. Only rows we can actually DM (an Instagram handle)."""
    kept: dict[str, Lead] = {}
    rejected: list[tuple[str, str]] = []

    for path in _csv_files(config.SCRAPER3_OUTPUT_DIR, config.SCRAPER3_GLOB):
        with open(path, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                handle = (row.get("Instagram") or "").strip()
                if not handle or handle.lower() in kept:
                    continue
                business = (row.get("Business Name") or "").strip()
                reason = rejection_reason(business, handle, "")
                if reason:
                    rejected.append((handle, reason))
                    continue
                try:
                    reviews = int(float(row.get("Reviews") or 0))
                except (TypeError, ValueError):
                    reviews = 0
                kept[handle.lower()] = Lead(
                    channel=config.CHANNEL_INSTAGRAM,
                    identifier=handle,
                    business=clean_business(business),
                    category=(row.get("Category") or "").strip(),
                    phone=(row.get("Phone Number") or "").strip(),
                    rating=str(row.get("Rating") or "").strip(),
                    reviews=reviews,
                    source=os.path.basename(path),
                )
    return list(kept.values()), rejected


def load_all() -> tuple[list[Lead], list[tuple[str, str]]]:
    emails, rej_e = load_email_leads()
    dms, rej_d = load_dm_leads()
    return emails + dms, rej_e + rej_d
