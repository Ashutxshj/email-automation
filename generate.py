"""Stage 3 (LLM path) — Gemini drafts every message; this module keeps it honest.

Division of labour:
  * genai_client.py — HTTP, pacing, retries, mock mode
  * this module     — prompts, batching, and the regenerate loop
  * draft.py        — validate_llm() (hard rules) and compose_message() (boilerplate)
  * ledger.py       — similarity dedup against every Message ever written

Anti-duplicate strategy, in order of cheapness:
  1. each lead in a batch gets a rotating "angle" (rating / reviews / category /
     website gap), so the model is FORCED to vary hooks before the ledger runs
  2. every draft is compared against every existing Message (threshold 0.80);
     a collision regenerates with the near-duplicate quoted back at the model
  3. after REGEN_ROUNDS the lead is surfaced as "write this one by hand" —
     a near-duplicate is never saved

Quota: leads are batched GEMINI_BATCH_SIZE per request, so a full 82-lead run is
~11 requests plus a few regeneration batches (worst case ~33 — still ~3% of the
free tier's daily 1,000). --prep also skips rows that already have a Message
(see main.py), so the steady-state cost is 1-2 requests per scraper import.
"""

import json

import config
import draft
from genai_client import GeminiError

RESPONSE_SCHEMA = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "id": {"type": "STRING"},
            "subject": {"type": "STRING"},
            "message": {"type": "STRING"},
        },
        "required": ["id", "subject", "message"],
    },
}

# Rotated per lead so consecutive drafts can't share a hook.
_ANGLES = (
    "lead with their star rating",
    "lead with their review count",
    "lead with what they sell",
    "lead with the website gap (no site, or a stale/broken one)",
)

SYSTEM_PROMPT = f"""You write cold outreach for Ashutosh, a solo website \
designer based in Delhi who builds and rebuilds websites for small businesses \
anywhere in India. He is BASED in Delhi but does not only serve it: the lead \
you are writing to may be in Chennai, Mumbai or any other city, so never imply \
the service area is Delhi NCR and never assume the reader is nearby. Every \
message invites the business to talk about getting a website built (or \
rebuilt). A human reads and pastes each one by hand — write text that survives \
that reading.

Hard rules for every message:
- Plain text only. No links, no URLs, no "www.", no emojis, no placeholders, \
no merge fields, no markdown, no [brackets].
- Use ONLY the facts provided for that lead. Never invent ratings, review \
counts, or anything else. Each message must cite at least one concrete fact \
(their rating, their review count, or what they sell).
- If has_website is false, NEVER imply you saw or visited their website.
- Sound like one busy person typing, not a campaign: no "I hope this finds \
you well", no "boost your online presence", no "unlock", no "elevate", no \
exclamation-mark enthusiasm. End with one short question.
- Every message in the batch must open differently and be structured \
differently from the others. Use each lead's "angle" field as the hook to \
lead with. If a lead has "previous_attempt_feedback", obey it.

Formats by channel:
- "email": subject = 2-5 lowercase words, no marketing vocabulary, reads like \
a colleague's note. message = {config.LLM_EMAIL_MIN_WORDS}-\
{config.LLM_EMAIL_MAX_WORDS} words, two short paragraphs. NO greeting-name \
guessing, NO signature, NO sign-off — those are appended separately.
- "instagram_dm" or "whatsapp": subject = "" (empty). message = exactly ONE \
line, max {config.ONE_LINER_MAX_CHARS - 20} characters, conversational.

Example (email, lead_type "Stale Website", has_website true, fact "Footer \
copyright still reads 2017"):
{{"id": "owner@example-salon.in", "subject": "your footer year",
"message": "Your site's footer still says 2017, which is usually a sign \
nothing on it has moved since then. Customers notice that faster than we \
think.\\n\\nI'm a web designer based in Delhi and I rebuild sites like this for \
small businesses across India — happy to show you what a refresh would look \
like before you commit to anything. Worth a look?"}}

Example (instagram_dm, lead_type "Goldenrod", has_website false, rating 4.9, \
reviews 733):
{{"id": "@example.salon", "subject": "",
"message": "4.9 stars from 733 reviews and nowhere to send all that traffic — \
I build websites for salons, want me to mock one up for you?"}}

Return ONLY a JSON array with one object per input lead: \
{{"id", "subject", "message"}}. Copy each "id" exactly as given.
"""

_CHANNEL_NAMES = {
    config.CHANNEL_EMAIL: "email",
    config.CHANNEL_INSTAGRAM: "instagram_dm",
    config.CHANNEL_WHATSAPP: "whatsapp",
}


def _payload(lead, angle_index: int, feedback: str) -> dict:
    item = {
        "id": lead.identifier,
        "channel": _CHANNEL_NAMES[lead.channel],
        "business": lead.business,
        "category": lead.category or "local business",
        "lead_type": lead.lead_type,
        "rating": lead.rating,
        "reviews": lead.reviews,
        "has_website": lead.has_website,
        "facts": lead.bullets,
        "angle": _ANGLES[angle_index % len(_ANGLES)],
    }
    if feedback:
        item["previous_attempt_feedback"] = feedback
    return item


def _chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def draft_all(leads: list, ledger, client) -> tuple[list, list]:
    """Draft every lead via Gemini. Returns (drafted, failed) where drafted is
    [(lead, subject, message)] — message is the final Message-cell text with
    boilerplate already composed — and failed is [(lead, reason)]."""
    drafted: list = []
    failed: list = []
    queue: list = [(i, lead, "") for i, lead in enumerate(leads)]

    for round_no in range(config.REGEN_ROUNDS + 1):
        if not queue:
            break
        retry: list = []
        for batch in _chunks(queue, config.GEMINI_BATCH_SIZE):
            payload = [_payload(lead, angle + round_no, feedback)
                       for angle, lead, feedback in batch]
            try:
                results = client.generate_json(
                    SYSTEM_PROMPT, json.dumps(payload, ensure_ascii=False),
                    RESPONSE_SCHEMA)
            except GeminiError as exc:
                failed.extend((lead, f"Gemini unavailable: {exc}")
                              for _, lead, _ in batch)
                continue

            by_id = {str(r.get("id", "")).strip(): r
                     for r in results if isinstance(r, dict)}
            for angle, lead, _ in batch:
                result = by_id.get(lead.identifier)
                if result is None:
                    retry.append((angle, lead,
                                  "your previous reply skipped this lead — "
                                  "include it this time"))
                    continue
                subject = str(result.get("subject") or "").strip()
                body = str(result.get("message") or "").strip()
                if lead.channel != config.CHANNEL_EMAIL:
                    subject = ""
                    body = " ".join(body.split())  # flatten stray newlines

                try:
                    draft.validate_llm(lead, subject, body)
                except draft.DraftError as exc:
                    retry.append((angle, lead,
                                  f"your previous attempt was rejected ({exc}) "
                                  "— write a different message that fixes this"))
                    continue

                message = draft.compose_message(lead, subject, body)
                similar = ledger.most_similar(message, exclude=lead.identifier)
                if similar and similar[1] >= config.SIMILARITY_THRESHOLD:
                    retry.append((angle, lead,
                                  "your previous attempt was too similar to a "
                                  "message already sent to someone else — take "
                                  "a completely different angle and opening"))
                    continue
                if ledger.opening_clash(message, exclude=lead.identifier):
                    retry.append((angle, lead,
                                  "your previous attempt opened with the same "
                                  "words as a message already sent to someone "
                                  "else — open completely differently"))
                    continue

                ledger.hold_pending(lead.identifier, message)
                drafted.append((lead, subject, message))
        queue = retry

    failed.extend((lead, "could not get a valid, unique draft out of Gemini "
                         f"in {config.REGEN_ROUNDS + 1} rounds — write this "
                         "one by hand")
                  for _, lead, _ in queue)
    return drafted, failed
