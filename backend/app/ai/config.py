"""Settings for every AI feature, read from the environment so keys never sit in the code.

Put these in backend/.env (locally) or in the Railway Variables tab (live):

    GROQ_API_KEY        the main key. Groq does everything: text, photos (its vision model), and PDFs that have text
                        in them (read here, then sent as words).
    ANTHROPIC_API_KEY   optional. Claude is used only for what Groq cannot read (a PDF that is a scan, a very large
                        picture), or for everything if AI_PROVIDER=claude.
    AI_PROVIDER         "groq" (default) or "claude": which one answers text tasks when both keys are set.
    GROQ_MODEL          the Groq text model: default llama-3.3-70b-versatile
    GROQ_VISION_MODEL   the Groq model for photos: default meta-llama/llama-4-scout-17b-16e-instruct
    AI_ENABLED          "1" (default) or "0" to switch every AI feature off at once.
    AI_MODEL_SMART      the model for reading documents and judging: default claude-sonnet-5-5
    AI_MODEL_FAST       the model for short, cheap tasks: default claude-haiku-5-5
    AI_TIMEOUT_SECONDS  how long to wait for an answer: default 60
"""
import os

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


def anthropic_key() -> str:
    return (os.getenv("ANTHROPIC_API_KEY") or "").strip()


def groq_key() -> str:
    return (os.getenv("GROQ_API_KEY") or "").strip()


def groq_model() -> str:
    return (os.getenv("GROQ_MODEL") or "llama-3.3-70b-versatile").strip()


def groq_vision_model() -> str:
    return (os.getenv("GROQ_VISION_MODEL") or "meta-llama/llama-4-scout-17b-16e-instruct").strip()


def prefer_groq() -> bool:
    return (os.getenv("AI_PROVIDER", "groq") or "groq").strip().lower() != "claude"


def enabled() -> bool:
    return (os.getenv("AI_ENABLED", "1") or "1").strip().lower() not in ("0", "false", "no", "off")


def configured() -> bool:
    return bool(anthropic_key() or groq_key())


def model_smart() -> str:
    return (os.getenv("AI_MODEL_SMART") or "claude-sonnet-5-5").strip()


def model_fast() -> str:
    return (os.getenv("AI_MODEL_FAST") or "claude-haiku-5-5").strip()


def timeout() -> float:
    try:
        return float(os.getenv("AI_TIMEOUT_SECONDS", "60"))
    except ValueError:
        return 60.0
