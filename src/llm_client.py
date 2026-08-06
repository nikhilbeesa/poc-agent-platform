"""
Shared LLM Client — Provider-Agnostic
=======================================
Every call site (agents, discovery) calls get_client() and then
client.generate(prompt, max_tokens) and gets back plain text — it never
touches a provider-specific API directly. That's what makes swapping
providers a config change, not a code change.

Provider is chosen via the LLM_PROVIDER env var ("anthropic" or "gemini",
defaults to "anthropic"). If the relevant API key isn't set, get_client()
returns None and every call site already treats that as "run in mock mode"
— nothing needed to change there.

  ANTHROPIC_API_KEY   required if LLM_PROVIDER=anthropic (the default)
  GEMINI_API_KEY      required if LLM_PROVIDER=gemini
  ANTHROPIC_MODEL     optional override (default: claude-sonnet-4-6)
  GEMINI_MODEL        optional override (default: gemini-3-flash-preview)

Why Gemini as the second option: Google's free tier is an actual ongoing
free tier, not just trial credit — useful if you want to run this without
an Anthropic budget. Free-tier model names and availability change often
(e.g. gemini-2.5-flash was restricted for new API keys ahead of its
official Oct 2026 shutdown date) — check https://ai.google.dev/gemini-api/docs/gemini-3
or https://ai.google.dev/pricing for the current list if GEMINI_MODEL's
default stops working, and override it via env var rather than waiting
for a code update.
"""

import os
import time

PROVIDER = os.environ.get("LLM_PROVIDER", "anthropic").lower()
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3-flash-preview")

# Free-tier / shared-capacity models occasionally return transient errors
# under load (e.g. Gemini's 503 "currently experiencing high demand," or
# Anthropic's 529 "overloaded"). These generally succeed on retry within
# seconds — so retry automatically rather than surfacing a scary error to
# the user for something that isn't actually broken.
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504, 529}
MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.5  # seconds; doubles each attempt (1.5, 3, 6)


def _is_retryable(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(exc, "code", None)  # google-genai uses .code
    return status in RETRYABLE_STATUS_CODES


class LLMClient:
    """Wraps whichever provider is active behind one uniform method."""

    def __init__(self, provider: str, raw_client):
        self.provider = provider
        self.raw_client = raw_client

    def generate(self, prompt: str, max_tokens: int = 800) -> str:
        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                return self._generate_once(prompt, max_tokens)
            except Exception as e:
                last_error = e
                if attempt < MAX_RETRIES - 1 and _is_retryable(e):
                    time.sleep(RETRY_BASE_DELAY * (2 ** attempt))
                    continue
                raise
        raise last_error  # pragma: no cover — loop always returns or raises

    def _generate_once(self, prompt: str, max_tokens: int) -> str:
        if self.provider == "anthropic":
            response = self.raw_client.messages.create(
                model=ANTHROPIC_MODEL,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text
        elif self.provider == "gemini":
            response = self.raw_client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
            )
            text = response.text
        else:
            raise ValueError(f"Unknown LLM_PROVIDER: {self.provider!r} (expected 'anthropic' or 'gemini')")

        return text.strip().replace("```json", "").replace("```", "").strip()


def get_client():
    """Returns an LLMClient for whichever provider is configured, or None
    if no relevant API key is set (mock mode)."""
    if PROVIDER == "anthropic":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return None
        import anthropic
        return LLMClient("anthropic", anthropic.Anthropic())

    if PROVIDER == "gemini":
        if not os.environ.get("GEMINI_API_KEY"):
            return None
        from google import genai
        raw_client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        return LLMClient("gemini", raw_client)

    raise ValueError(f"Unknown LLM_PROVIDER: {PROVIDER!r} (expected 'anthropic' or 'gemini')")


def call_llm(client: LLMClient, prompt: str, max_tokens: int = 800) -> str:
    """Kept for backward compatibility with existing call sites."""
    return client.generate(prompt, max_tokens)
