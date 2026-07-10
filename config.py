"""Configuration for the draft-prep tool.

This package NEVER sends anything. It prepares messages for a human to read and
paste. There is no SMTP client and no --send flag anywhere in it. The only API
key it knows about is Gemini's, and Gemini only WRITES drafts — a human still
sends every one.

All lead state lives in the ONE master workbook, Projects/leads_master.xlsx.
"""

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_dotenv() -> None:
    """Read BASE_DIR/.env into the environment. Real env vars win."""
    path = os.path.join(BASE_DIR, ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

# Leads are read from, and written back to, Projects/leads_master.xlsx — see
# master_registry.py. There is no database and no queue file here.
# The only artifact this repo produces is a human-readable copy of the drafts.
DRAFTS_FILE = os.path.join(BASE_DIR, "drafts.md")

CHANNEL_EMAIL = "email"
CHANNEL_INSTAGRAM = "instagram"
CHANNEL_WHATSAPP = "whatsapp"

# What --prep writes into the master's Channel column, so you know where to
# paste each message without re-deriving anything.
CHANNEL_LABELS = {
    CHANNEL_EMAIL: "Email",
    CHANNEL_INSTAGRAM: "Instagram DM",
    CHANNEL_WHATSAPP: "WhatsApp",
}

# --- Purge rules -----------------------------------------------------------

# /scraper's MOCK_TARGETS point at real companies, so `--mock` runs harvested
# live corporate inboxes straight into the real output CSVs. Every mock row is
# named "Demo <something>".
MOCK_NAME_PREFIXES = ("demo",)

# Harvested from those mock rows, plus enterprises that slipped the ICP filter.
# Cold-pitching web design to Haldiram's is a guaranteed complaint and zero
# upside; techmagnate.com is a competitor SEO agency, and it was their *jobs*
# inbox. All of these were really present in scraper/output as of 2026-07.
#
# This list is MANUAL and cannot be complete — there is no reliable heuristic for
# "is this a national brand". It is seeded with every enterprise actually found
# in the current data. Keep reading the drafts: a household name in the To: field
# is the signal to add it here. Local chains are fine; national ones are not.
ENTERPRISE_DOMAINS = {
    # harvested from /scraper's MOCK_TARGETS
    "livspace.com",
    "haldirams.com",
    "clovedental.com", "clovedental.in",
    "tothenew.com",
    "techmagnate.com",       # competitor SEO agency (their jobs@ inbox, no less)
    # enterprises that slipped the ICP filter into real rows
    "itchotels.in", "itchotels.com",
    "shangri-la.com",        # global luxury hotel group
    "allen.in", "allen.ac.in",  # national coaching chain, not a local institute
}

# Businesses that SELL tech / digital-marketing services — peers, not prospects.
# Copied from scraper/config.py:104. Applied to the EMAIL DOMAIN as well as the
# business name: the name-only check is what let jobs@techmagnate.com through.
EXCLUDED_KEYWORDS = [
    "digital", "marketing", "seo", "branding", "advertis", "adagenc",
    "ad agenc", "media house",
    "social media", "software", "tech", "infotech", "it solution", "it service",
    "saas", "web design", "webdesign", "web develop", "webdev", "website",
    "app develop", "graphic design",
]

# Geography gate. NOTE: we do NOT require an NCR city keyword to be present —
# most legitimate NCR domains (agargca.com, capulkit.com) name no city at all,
# so requiring one would reject nearly every real lead. Instead we reject
# domains/names that positively name a city outside the service area. This is
# what catches info@dentalcareudaipur.com.
OUT_OF_AREA_CITIES = [
    "udaipur", "mumbai", "pune", "jaipur", "bangalore", "bengaluru", "chennai",
    "kolkata", "hyderabad", "ahmedabad", "surat", "lucknow", "indore", "bhopal",
    "nagpur", "kanpur", "patna", "chandigarh", "dehradun", "kochi", "goa",
    "coimbatore", "vizag", "guwahati", "ranchi", "raipur", "varanasi",
    "gorakhpur", "amritsar", "ludhiana", "agra", "kanpur", "mysore",
]

# --- Deliverability --------------------------------------------------------

# A recycled spam trap is an abandoned address a mailbox provider reactivated to
# catch senders mailing scraped, unverified lists. A domain untouched for years
# is exactly that profile — which means the staleness signal that QUALIFIES a
# lead also makes its inbox dangerous. Hold the oldest ones back until the
# sending domain has a reputation. One trap hit is a Spamhaus listing.
TRAP_RISK_DAYS = 1095  # 3 years

# Free bounce protection: no paid verifier, just DNS. No MX record -> nothing can
# receive mail there -> guaranteed bounce -> drop before sending.
REQUIRE_MX = True

# --- Gemini ------------------------------------------------------------------

# The key never lives in this repo — put GEMINI_API_KEY=... in .env (gitignored)
# or the environment. A free key from https://aistudio.google.com/apikey is
# enough: a full 82-lead run is ~11 requests against a ~1,000/day allowance.
GEMINI_API_KEY_ENV = "GEMINI_API_KEY"
# gemini-2.5-flash-lite 404s for accounts created after mid-2026 ("no longer
# available to new users"); 3.1 is the current free-tier flash-lite.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
GEMINI_BATCH_SIZE = 8       # leads per request — fewer requests, not one giant one
GEMINI_TIMEOUT = 60         # seconds per HTTP call
GEMINI_HTTP_RETRIES = 3     # extra attempts on 429/5xx, exponential backoff
GEMINI_MIN_INTERVAL = 5.0   # seconds between requests => ~12 RPM, under the 15 RPM cap
REGEN_ROUNDS = 2            # regeneration rounds for duplicates/invalid drafts

# --- Message rules -----------------------------------------------------------

EMAIL_MAX_WORDS = 120
DM_MAX_WORDS = 70

# Gemini-drafted messages are tighter than the template ones: a "proper ~50-word
# email" and true one-liners for DM/WhatsApp.
LLM_EMAIL_MAX_WORDS = 60
LLM_EMAIL_MIN_WORDS = 25    # reject one-sentence stubs
ONE_LINER_MAX_CHARS = 200   # DM / WhatsApp: a single line, or it isn't a DM

# A legalistic opt-out inside a one-line DM reads bot-like and blows the char
# budget. Emails always keep EMAIL_OPTOUT.
ONE_LINER_INCLUDE_OPTOUT = False

# Two rendered messages closer than this are "the same email" for our purposes.
# An exact hash would be useless here: two bodies differing by one comma hash
# differently, so it would pass everything. Compared on the fully rendered body.
SIMILARITY_THRESHOLD = 0.80

SIGNATURE = "Ashutosh"

# Boilerplate. Lives here because BOTH draft.py (to render it) and ledger.py (to
# strip it before comparing) need the exact strings. Every message ends with the
# same opt-out by design, and leaving it in the similarity comparison inflates
# every ratio toward 1.0 — it would make two emails saying completely different
# things look like duplicates.
EMAIL_OPTOUT = ('If you\'d rather I didn\'t write again, just reply "no" and '
                "I'll leave you alone.")
DM_OPTOUT = "If you'd rather not hear from me, just say so and I'll leave it there."

# Placeholder addresses harvested from template/demo websites. sample@mail.com
# was sitting in the real scraper output. Mailing one is a bounce at best and a
# spam-trap hit at worst.
JUNK_LOCALPARTS = {
    "sample", "example", "test", "testing", "your", "yourname", "youremail",
    "email", "name", "user", "username", "demo", "abc", "xyz", "noreply",
    "no-reply", "donotreply", "do-not-reply", "mailer-daemon", "postmaster",
}
JUNK_DOMAINS = {
    "example.com", "example.org", "domain.com", "yourdomain.com", "yoursite.com",
    "test.com", "email.com", "mysite.com", "website.com", "sentry.io",
    "wixpress.com", "godaddy.com", "sentry.wixpress.com",
}

# Substrings that must never appear in an outgoing body. Plain text only: no
# links (Gmail autolinks bare domains too), no unrendered merge fields, no
# stringified Python. Note we forbid the URL *schemes*, not the bare word "http"
# — a clause may legitimately say "your site loads over plain HTTP".
FORBIDDEN_SUBSTRINGS = ("http://", "https://", "www.", "{{", "}}", "None", "N/A")
