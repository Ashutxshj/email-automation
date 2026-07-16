"""Gemini transport. This module knows HTTP; generate.py knows prompts.

Free-tier discipline, enforced here so no caller can forget it:
  * requests are paced GEMINI_MIN_INTERVAL seconds apart (~12 RPM < the 15 RPM cap)
  * 429/5xx are retried with backoff, honouring the retryDelay Google sends back
  * every request and token is counted, and --prep prints the totals

Stdlib urllib only — no SDK dependency, and the whole thing is mockable:
GEMINI_MOCK=1 (or --mock-llm) returns deterministic fake drafts derived from the
lead payload, zero network, so the full parse/validate/dedup/write pipeline can
be exercised without spending a single request.
"""

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request

import config

_API_URL = ("https://generativelanguage.googleapis.com/v1beta/models/"
            "{model}:generateContent")
_RETRYABLE = {429, 500, 502, 503, 504}

# A 429 body carries {"details": [..., {"retryDelay": "37s"}]} — honour it.
_RETRY_DELAY_RE = re.compile(r'"retryDelay"\s*:\s*"(\d+(?:\.\d+)?)s"')


def _retry_delay(detail: str) -> float:
    match = _RETRY_DELAY_RE.search(detail or "")
    return float(match.group(1)) + 1.0 if match else 0.0


class GeminiError(Exception):
    """The API could not produce a usable response."""


class GeminiClient:
    def __init__(self, model: str = "", mock: bool = False):
        self.model = model or config.GEMINI_MODEL
        self.mock = mock or bool(os.getenv("GEMINI_MOCK"))
        self.request_count = 0
        self.token_count = 0
        self._last_call = 0.0
        if self.mock:
            self.api_key = ""
            return
        self.api_key = os.getenv(config.GEMINI_API_KEY_ENV, "").strip()
        if not self.api_key:
            raise GeminiError(
                f"{config.GEMINI_API_KEY_ENV} is not set. Get a free key at "
                "https://aistudio.google.com/apikey and put "
                f"{config.GEMINI_API_KEY_ENV}=... in {config.BASE_DIR}\\.env, "
                "or run with --no-llm for template drafts.")

    # --- public ---------------------------------------------------------------

    def generate_json(self, system: str, user: str, schema: dict) -> list:
        """One generateContent call constrained to a JSON array; parsed result.

        `user` is a JSON array of lead payloads (generate.py's contract). Raises
        GeminiError after retries are exhausted or on malformed output.
        """
        if self.mock:
            return self._mock(user)

        request = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": schema,
                "temperature": 0.9,
            },
        }
        payload = self._call_with_retries(request)

        try:
            text = payload["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError):
            reason = (payload.get("promptFeedback") or {}).get("blockReason", "")
            raise GeminiError(f"response had no text candidate"
                              f"{f' (blocked: {reason})' if reason else ''}")
        self.token_count += (payload.get("usageMetadata") or {}).get(
            "totalTokenCount", 0)
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise GeminiError(f"model returned malformed JSON: {exc}")
        if not isinstance(parsed, list):
            raise GeminiError("model returned JSON that is not an array")
        return parsed

    # --- HTTP -------------------------------------------------------------------

    def _pace(self) -> None:
        wait = config.GEMINI_MIN_INTERVAL - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def _call_with_retries(self, request: dict) -> dict:
        delay = 10.0
        last_error = "unknown error"
        for attempt in range(config.GEMINI_HTTP_RETRIES + 1):
            self._pace()
            try:
                return self._post(request)
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")
                last_error = f"HTTP {exc.code}: {detail[:300]}"
                if exc.code not in _RETRYABLE:
                    raise GeminiError(last_error)
                delay = max(delay, _retry_delay(detail))
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = f"network error: {exc}"
            if attempt < config.GEMINI_HTTP_RETRIES:
                time.sleep(delay)
                delay *= 3
        raise GeminiError(f"gave up after {config.GEMINI_HTTP_RETRIES + 1} "
                          f"attempts — {last_error}")

    def _post(self, request: dict) -> dict:
        req = urllib.request.Request(
            _API_URL.format(model=self.model),
            data=json.dumps(request).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "x-goog-api-key": self.api_key},
            method="POST")
        self.request_count += 1
        with urllib.request.urlopen(req, timeout=config.GEMINI_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))

    # --- mock -------------------------------------------------------------------

    def _mock(self, user: str) -> list:
        """Deterministic fake drafts, one per payload lead. Lead-specific facts
        keep the pairwise similarity low enough to clear the ledger."""
        self.request_count += 1
        try:
            items = json.loads(user)
        except json.JSONDecodeError:
            raise GeminiError("mock mode expects the user turn to be JSON")

        out = []
        for item in items:
            ident = str(item.get("id", ""))
            # Feedback participates in the seed so a regeneration round
            # actually produces different text, as the real model would.
            seed_src = ident + str(item.get("previous_attempt_feedback", ""))
            seed = int(hashlib.md5(seed_src.encode("utf-8")).hexdigest(), 16)
            # The real model shortens SEO-stuffed names naturally; the mock
            # truncates so one-liners stay inside the char cap.
            business = " ".join(str(item.get("business") or
                                    "your business").split()[:4])
            category = (item.get("category") or "business").lower()
            rating = item.get("rating") or ""
            reviews = item.get("reviews") or 0
            fact = (f"{rating} stars across {reviews:,} Google reviews"
                    if rating and reviews else f"your {category} listing on Maps")

            if item.get("channel") == "email":
                openers = [
                    f"I was reading up on {business} and {fact} stood out.",
                    f"{business} keeps coming up when I look at local "
                    f"{category} listings — {fact} is hard to miss.",
                    f"While comparing {category} options nearby I found "
                    f"{business}, and noticed {fact}.",
                    f"Quick note about {business}: {fact} caught my eye today.",
                    f"Came across {business} this morning — {fact}, which is "
                    "rarer than it sounds.",
                ]
                middles = [
                    "I build simple, fast websites for small businesses across "
                    "India, and a business with that kind of reputation "
                    "usually gets real mileage out of one.",
                    "I'm a web designer based in Delhi, and yours is exactly "
                    "the kind of business a clean site tends to help most.",
                    "Websites for local businesses are what I build, and I'd "
                    "happily sketch what one for you could look like first.",
                    "My work is building sites for businesses like yours, and "
                    "seeing one usually beats hearing about one.",
                ]
                closers = ["Worth a short reply?", "Open to a quick look?",
                           "Shall I send over an example?", "Curious to see it?"]
                body = (f"{openers[seed % len(openers)]}\n\n"
                        f"{middles[seed // 7 % len(middles)]} "
                        f"{closers[seed // 31 % len(closers)]}")
                subject = ["your google listing", "a site for " + category,
                           "quick question", "your online presence"][seed % 4]
            else:
                openers = [
                    f"Hi — {fact} for {business} is hard to ignore;",
                    f"Hey! Found {business} on Maps, {fact};",
                    f"Hi, {fact} says a lot about {business} —",
                    f"Hello — {business} showing {fact} deserves more than a "
                    "Maps pin;",
                    f"Hey, noticed {business} has {fact};",
                    f"Hi! {business} came up in {category} listings nearby, "
                    f"{fact} —",
                ]
                pitches = [
                    f"I build websites for {category}s",
                    "I design simple sites for small businesses",
                    "making websites for businesses like yours is what I do",
                    "I turn listings like that into proper websites",
                    "a clean one-page site could catch all that traffic, and I "
                    "build those",
                ]
                closers = ["want a quick mock-up?", "can I send a sample?",
                           "open to seeing an example?",
                           "curious what yours could look like?",
                           "shall I sketch one for you?"]
                body = (f"{openers[seed % len(openers)]} "
                        f"{pitches[seed // 11 % len(pitches)]} — "
                        f"{closers[seed // 71 % len(closers)]}")
                subject = ""

            out.append({"id": ident, "subject": subject, "message": body})
        return out
