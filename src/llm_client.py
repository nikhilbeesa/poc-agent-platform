"""
Shared LLM Client — Provider-Agnostic. LLM_PROVIDER env var picks
"anthropic" (default) or "gemini". Automatic retry on transient errors.
"""

import os
import re
import threading
import time
from collections import deque

PROVIDER = os.environ.get("LLM_PROVIDER", "anthropic").lower()
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite")

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504, 529}
MAX_RETRIES = 8
RETRY_BASE_DELAY = 2.0
RETRY_MAX_DELAY = 30.0

# Client-side throttle: stay safely UNDER the provider's requests-per-minute
# limit so a 429 never happens in the first place. Gemini free tier = 15 RPM,
# so default to 12. Set LLM_MAX_RPM=0 to disable, or raise it on a paid tier.
MAX_RPM = int(os.environ.get("LLM_MAX_RPM", "12"))


class LLMQuotaExhausted(Exception):
    """The provider's DAILY quota is used up. Retrying can't help until it
    resets, so fail fast with a clear message instead of retrying for minutes."""


class _RateLimiter:
    """Thread-safe sliding-window limiter (max N calls per 60s) shared by every
    LLM call in the process, plus a global cool-down that pauses all threads
    when the provider says "retry in Ns"."""

    def __init__(self, max_per_minute: int):
        self.max = max_per_minute
        self.calls: deque[float] = deque()
        self.cooldown_until = 0.0
        self.lock = threading.Lock()

    def acquire(self) -> None:
        if self.max <= 0:
            return
        while True:
            with self.lock:
                now = time.monotonic()
                while self.calls and now - self.calls[0] >= 60.0:
                    self.calls.popleft()
                wait = max(0.0, self.cooldown_until - now)
                if wait == 0.0 and len(self.calls) < self.max:
                    self.calls.append(now)
                    return
                if wait == 0.0:
                    wait = 60.0 - (now - self.calls[0])
            time.sleep(min(max(wait, 0.05), 5.0))

    def cool_down(self, seconds: float) -> None:
        with self.lock:
            self.cooldown_until = max(self.cooldown_until, time.monotonic() + seconds)


_limiter = _RateLimiter(MAX_RPM)


def _retry_after_seconds(exc: Exception) -> float | None:
    """Server-suggested wait, e.g. Gemini's 'Please retry in 23.4s' or a
    Retry-After header."""
    resp = getattr(exc, "response", None)
    headers = getattr(resp, "headers", None)
    if headers:
        try:
            v = headers.get("retry-after") or headers.get("Retry-After")
            if v:
                return float(v)
        except (TypeError, ValueError):
            pass
    m = re.search(r"retry(?:Delay)?\W+(?:in\W+)?(\d+(?:\.\d+)?)\s*s", str(exc), re.IGNORECASE)
    return float(m.group(1)) if m else None


def _is_daily_quota(exc: Exception) -> bool:
    msg = str(exc)
    return "PerDay" in msg or "per day" in msg.lower() or "daily" in msg.lower() and "quota" in msg.lower()


class LLMTruncated(Exception):
    """The model hit its output-token limit mid-reply, so the text is cut
    off (and, for JSON, unparseable). Not retryable as-is — callers should
    ask for a smaller chunk. `partial` holds whatever text was returned."""

    def __init__(self, partial: str = ""):
        super().__init__("LLM output was truncated at the max-token limit")
        self.partial = partial


def _is_retryable(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(exc, "code", None)
    return status in RETRYABLE_STATUS_CODES


class LLMClient:
    def __init__(self, provider: str, raw_client):
        self.provider = provider
        self.raw_client = raw_client

    def generate(self, prompt: str, max_tokens: int = 800) -> str:
        last_error = None
        for attempt in range(MAX_RETRIES):
            _limiter.acquire()  # every attempt (incl. retries) counts against the RPM budget
            try:
                return self._generate_once(prompt, max_tokens)
            except Exception as e:
                last_error = e
                if getattr(e, "status_code", getattr(e, "code", None)) == 429 and _is_daily_quota(e):
                    raise LLMQuotaExhausted(
                        "The daily request quota for the LLM provider is used up. "
                        "It resets automatically (Gemini: midnight Pacific time), or switch to a paid tier."
                    ) from e
                if attempt < MAX_RETRIES - 1 and _is_retryable(e):
                    delay = min(RETRY_BASE_DELAY * (2 ** attempt), RETRY_MAX_DELAY)
                    hinted = _retry_after_seconds(e)
                    if hinted is not None:
                        delay = min(max(delay, hinted + 1.0), 90.0)
                    if getattr(e, "status_code", getattr(e, "code", None)) == 429:
                        _limiter.cool_down(delay)  # pause ALL threads, not just this one
                    time.sleep(delay)
                    continue
                raise
        raise last_error

    def _generate_once(self, prompt: str, max_tokens: int) -> str:
        truncated = False
        if self.provider == "anthropic":
            response = self.raw_client.messages.create(
                model=ANTHROPIC_MODEL, max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text
            truncated = getattr(response, "stop_reason", None) == "max_tokens"
        elif self.provider == "gemini":
            from google.genai import types
            # Cap the output explicitly and ask for JSON directly: without
            # a cap the model's default applies (and a lite model tends to
            # answer tersely), and without JSON mode it may wrap the reply
            # in prose/fences that break parsing.
            response = self.raw_client.models.generate_content(
                model=GEMINI_MODEL, contents=prompt,
                config=types.GenerateContentConfig(
                    max_output_tokens=max_tokens,
                    response_mime_type="application/json",
                ),
            )
            text = response.text
            if text is None:
                raise RuntimeError("Gemini returned an empty response (possibly blocked or filtered).")
            try:
                reason = str(response.candidates[0].finish_reason)
                truncated = "MAX_TOKENS" in reason.upper()
            except Exception:
                truncated = False
        else:
            raise ValueError(f"Unknown LLM_PROVIDER: {self.provider!r}")
        text = text.strip().replace("```json", "").replace("```", "").strip()
        if truncated:
            raise LLMTruncated(text)
        return text


def get_client():
    if PROVIDER == "anthropic":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return None
        import anthropic
        return LLMClient("anthropic", anthropic.Anthropic())
    if PROVIDER == "gemini":
        if not os.environ.get("GEMINI_API_KEY"):
            return None
        from google import genai
        return LLMClient("gemini", genai.Client(api_key=os.environ["GEMINI_API_KEY"]))
    raise ValueError(f"Unknown LLM_PROVIDER: {PROVIDER!r}")


def call_llm(client: LLMClient, prompt: str, max_tokens: int = 800) -> str:
    return client.generate(prompt, max_tokens)
