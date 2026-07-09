"""Stage 2 — free bounce and spam-trap protection.

There is no budget for a paid verifier (ZeroBounce, NeverBounce). Two free
substitutes do most of the work:

1. MX lookup. A domain with no MX record cannot receive mail at all, so every
   send to it is a guaranteed bounce. Bounces damage a young sending reputation
   faster than complaints do.

2. Trap-risk scoring off staleness. This is the uncomfortable one. /scraper
   QUALIFIES a lead by how long its site has been untouched — 400 to 3,233 days
   in the current data. But an info@ mailbox on a domain nobody has touched since
   2017 is precisely the profile of a recycled spam trap: an abandoned address a
   mailbox provider reactivated to catch senders mailing scraped lists. The
   signal that makes them a good PROSPECT makes their inbox a bad TARGET, and one
   trap hit is a Spamhaus listing.

   So we HOLD the oldest domains rather than dropping them, and send in freshness
   order. If the recent domains bounce, the ancient ones will bounce harder —
   that is verification by observation, and it costs nothing.
"""

import config

SEND = "SEND"
HOLD = "HOLD"
DROP = "DROP"

_mx_cache: dict[str, bool | None] = {}


def _resolve_mx(domain: str) -> bool | None:
    """True = has MX, False = no MX, None = could not check (never punish these)."""
    if domain in _mx_cache:
        return _mx_cache[domain]
    try:
        import dns.resolver
    except ImportError:
        _mx_cache[domain] = None
        return None

    try:
        answers = dns.resolver.resolve(domain, "MX", lifetime=5.0)
        result = len(answers) > 0
    except dns.resolver.NXDOMAIN:
        result = False           # domain does not exist
    except dns.resolver.NoAnswer:
        result = False           # exists, but accepts no mail
    except Exception:
        result = None            # timeout / no nameserver / offline — unknown
    _mx_cache[domain] = result
    return result


def check(lead) -> tuple[str, str]:
    """Return (verdict, note) for one lead. DM leads never need mail checks."""
    if lead.channel != config.CHANNEL_EMAIL:
        return SEND, ""

    if config.REQUIRE_MX and lead.domain:
        mx = _resolve_mx(lead.domain)
        if mx is False:
            return DROP, f"no MX record on {lead.domain} — mail would bounce"
        if mx is None:
            return HOLD, f"could not resolve MX for {lead.domain} (offline?) — verify by hand"

    if lead.stale_days is not None and lead.stale_days > config.TRAP_RISK_DAYS:
        years = lead.stale_days / 365
        return HOLD, (f"site dead {years:.1f}y — high recycled-spam-trap risk; "
                      "send only after the domain has a reputation")

    return SEND, ""


def send_order(leads: list) -> list:
    """Freshest domains first. Unknown staleness sorts as middling, not best —
    we would rather open with a lead we can prove is alive."""
    def key(lead):
        if lead.channel != config.CHANNEL_EMAIL:
            return (0, 0)
        return (1, lead.stale_days if lead.stale_days is not None else 10_000)
    return sorted(leads, key=key)
