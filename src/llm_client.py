"""
Shared LLM Client — Provider-Agnostic. LLM_PROVIDER env var picks
"anthropic" (default) or "gemini". Automatic retry on transient errors.
"""

import os
import time

PROVIDER = os.environ.get("LLM_PROVIDER", "anthropic").lower()
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite")

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504, 529}
MAX_RETRIES = 5
RETRY_BASE_DELAY = 2.0
RETRY_MAX_DELAY = 20.0


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
            try:
                return self._generate_once(prompt, max_tokens)
            except Exception as e:
                last_error = e
                if attempt < MAX_RETRIES - 1 and _is_retryable(e):
                    delay = min(RETRY_BASE_DELAY * (2 ** attempt), RETRY_MAX_DELAY)
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
