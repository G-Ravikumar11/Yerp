import os
import json
import logging
import httpx

logger = logging.getLogger(__name__)

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
MODEL = "llama-3.1-8b-instant"


def llm_configured() -> bool:
    """Whether an API key is set at all.

    Callers use this to tell "nobody has configured this" apart from "the call
    failed", which used to look identical because both came back as None.
    """
    return bool(GROQ_API_KEY)


# Why the last call failed, for the endpoints to pass on. A single "AI
# unavailable" told the user nothing they could act on.
LAST_ERROR = {"reason": ""}


def llm_last_error() -> str:
    return LAST_ERROR["reason"]


def llm_chat(messages, temperature=0.3, max_tokens=1024):
    if not GROQ_API_KEY:
        LAST_ERROR["reason"] = "no_key"
        return None
    try:
        resp = httpx.post(
            f"{GROQ_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={"model": MODEL, "messages": messages, "temperature": temperature, "max_tokens": max_tokens},
            timeout=30,
        )
        if resp.status_code == 200:
            LAST_ERROR["reason"] = ""
            return resp.json()["choices"][0]["message"]["content"].strip()
        LAST_ERROR["reason"] = {
            401: "bad_key", 403: "bad_key", 429: "rate_limited",
        }.get(resp.status_code, "upstream_error")
        logger.error("Groq API error %d: %s", resp.status_code, resp.text[:200])
    except httpx.TimeoutException:
        LAST_ERROR["reason"] = "timeout"
        logger.error("Groq call timed out")
    except Exception as e:
        LAST_ERROR["reason"] = "network_error"
        logger.error("Groq call failed: %s", e)
    return None


# What to put in front of a person for each reason.
LLM_MESSAGES = {
    "no_key": "AI is not set up yet. Add a GROQ_API_KEY and it will switch on.",
    "bad_key": "The AI key was rejected. Check GROQ_API_KEY.",
    "rate_limited": "The AI is busy right now. Try again in a moment.",
    "timeout": "The AI took too long to answer. Try again.",
    "network_error": "Could not reach the AI service.",
    "upstream_error": "The AI service returned an error.",
}


def llm_error_message() -> str:
    return LLM_MESSAGES.get(LAST_ERROR["reason"], "The AI is unavailable right now.")


def llm_json(messages, temperature=0.2):
    text = llm_chat(messages, temperature=temperature, max_tokens=2048)
    if not text:
        return None
    try:
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
        return json.loads(text.strip())
    except json.JSONDecodeError:
        try:
            start = text.index("{")
            end = text.rindex("}") + 1
            return json.loads(text[start:end])
        except (ValueError, json.JSONDecodeError):
            logger.error("Failed to parse LLM JSON: %s", text[:200])
            return None
