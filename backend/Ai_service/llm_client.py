"""The one place a model is called.

A feature file never talks to a provider. It builds its facts, calls `ask()` or `ask_json()` here, and checks the
answer. That keeps keys, fallbacks, time limits and error words in one file, and lets a test replace `ask` and run a
whole feature without a network.

Claude is used when ANTHROPIC_API_KEY is set (it can read photos and PDFs). Groq answers text-only tasks when that is
the only key there is. A task that needs to *see* a document and has no Claude key says so; it never guesses.
"""
import base64
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

from Ai_service import config

logger = logging.getLogger("Ai_service")

MESSAGES = {
    "off": "AI is switched off (AI_ENABLED=0).",
    "no_key": "AI is not set up yet. Add ANTHROPIC_API_KEY (or GROQ_API_KEY for text tasks) and it switches on.",
    "needs_vision": "Reading a scanned document needs ANTHROPIC_API_KEY; the text-only fallback cannot see it.",
    "bad_key": "The AI key was rejected. Check the key in the settings.",
    "rate_limited": "The AI is busy right now. Try again in a moment.",
    "timeout": "The AI took too long to answer. Try again.",
    "network_error": "Could not reach the AI service.",
    "upstream_error": "The AI service returned an error.",
    "bad_answer": "The AI answered, but not in a form that could be read. Nothing was changed.",
}


@dataclass
class Attachment:
    """A picture or PDF the model should look at."""
    data: bytes
    media_type: str            # image/jpeg | image/png | image/webp | image/gif | application/pdf


@dataclass
class AiResult:
    ok: bool
    text: str = ""
    data: Optional[Any] = None
    reason: str = ""            # a key of MESSAGES when not ok
    provider: str = ""
    model: str = ""
    usage: Dict[str, int] = field(default_factory=dict)

    @property
    def message(self) -> str:
        return MESSAGES.get(self.reason, "The AI is unavailable right now.") if not self.ok else ""


def _blocks(prompt: str, attachments: List[Attachment]):
    out = []
    for a in attachments:
        kind = "document" if a.media_type == "application/pdf" else "image"
        out.append({"type": kind, "source": {"type": "base64", "media_type": a.media_type,
                                             "data": base64.b64encode(a.data).decode("ascii")}})
    out.append({"type": "text", "text": prompt})
    return out


def _claude(system, prompt, attachments, model, max_tokens, temperature) -> AiResult:
    try:
        resp = httpx.post(
            config.ANTHROPIC_URL,
            headers={"x-api-key": config.anthropic_key(), "anthropic-version": config.ANTHROPIC_VERSION,
                     "content-type": "application/json"},
            json={"model": model, "max_tokens": max_tokens, "temperature": temperature, "system": system,
                  "messages": [{"role": "user", "content": _blocks(prompt, attachments)}]},
            timeout=config.timeout(),
        )
    except httpx.TimeoutException:
        return AiResult(False, reason="timeout", provider="anthropic", model=model)
    except Exception as exc:
        logger.error("Claude call failed: %s", exc)
        return AiResult(False, reason="network_error", provider="anthropic", model=model)
    if resp.status_code != 200:
        logger.error("Claude API error %d: %s", resp.status_code, resp.text[:300])
        reason = {401: "bad_key", 403: "bad_key", 429: "rate_limited", 529: "rate_limited"}.get(resp.status_code, "upstream_error")
        return AiResult(False, reason=reason, provider="anthropic", model=model)
    body = resp.json()
    text = "".join(b.get("text", "") for b in body.get("content", []) if b.get("type") == "text").strip()
    usage = {"input": (body.get("usage") or {}).get("input_tokens", 0), "output": (body.get("usage") or {}).get("output_tokens", 0)}
    return AiResult(True, text=text, provider="anthropic", model=model, usage=usage)


def _groq(system, prompt, max_tokens, temperature, as_json=False) -> AiResult:
    body = {"model": config.groq_model(), "temperature": temperature, "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}
    if as_json:
        body["response_format"] = {"type": "json_object"}
    try:
        resp = httpx.post(
            config.GROQ_URL,
            headers={"Authorization": "Bearer " + config.groq_key(), "Content-Type": "application/json"},
            json=body,
            timeout=config.timeout(),
        )
    except httpx.TimeoutException:
        return AiResult(False, reason="timeout", provider="groq", model=config.groq_model())
    except Exception as exc:
        logger.error("Groq call failed: %s", exc)
        return AiResult(False, reason="network_error", provider="groq", model=config.groq_model())
    if resp.status_code != 200:
        logger.error("Groq API error %d: %s", resp.status_code, resp.text[:300])
        reason = {401: "bad_key", 403: "bad_key", 429: "rate_limited"}.get(resp.status_code, "upstream_error")
        return AiResult(False, reason=reason, provider="groq", model=config.groq_model())
    text = resp.json()["choices"][0]["message"]["content"].strip()
    return AiResult(True, text=text, provider="groq", model=config.groq_model())


def ask(system: str, prompt: str, attachments: Optional[List[Attachment]] = None, smart: bool = True,
        max_tokens: int = 2048, temperature: float = 0.1, as_json: bool = False) -> AiResult:
    """Ask the model something. Text goes to Groq by default; anything with a picture or PDF goes to Claude."""
    attachments = attachments or []
    if not config.enabled():
        return AiResult(False, reason="off")
    if attachments:                      # only Claude can look at a picture or a PDF
        if not config.anthropic_key():
            return AiResult(False, reason="needs_vision" if config.groq_key() else "no_key")
        return _claude(system, prompt, attachments, config.model_smart() if smart else config.model_fast(), max_tokens, temperature)
    if config.groq_key() and (config.prefer_groq() or not config.anthropic_key()):
        return _groq(system, prompt, max_tokens, temperature, as_json)
    if config.anthropic_key():
        return _claude(system, prompt, [], config.model_smart() if smart else config.model_fast(), max_tokens, temperature)
    return AiResult(False, reason="no_key")


def parse_json(text: str):
    """The first JSON object in an answer, tolerating a code fence or a sentence around it; None if there is none."""
    if not text:
        return None
    if "```" in text:
        for part in text.split("```"):
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("{") or part.startswith("["):
                text = part
                break
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        pass
    try:
        return json.loads(text[text.index("{"):text.rindex("}") + 1])
    except (ValueError, TypeError):
        return None


def ask_json(system: str, prompt: str, attachments: Optional[List[Attachment]] = None, smart: bool = True,
             max_tokens: int = 2048) -> AiResult:
    """Like ask(), but the answer must be a JSON object; `data` holds it."""
    result = ask(system + "\nAnswer with one JSON object and nothing else.", prompt, attachments, smart, max_tokens, as_json=True)
    if not result.ok:
        return result
    data = parse_json(result.text)
    if not isinstance(data, dict):
        logger.error("AI answer was not JSON: %s", result.text[:200])
        return AiResult(False, text=result.text, reason="bad_answer", provider=result.provider, model=result.model, usage=result.usage)
    result.data = data
    return result
