"""Settings for every AI feature, read from the environment so keys never sit in the code.

Put these in backend/.env (locally) or in the Railway Variables tab (live):

    GROQ_API_KEY        the default for every text task (summaries, flags worded, email drafts, comparisons).
    ANTHROPIC_API_KEY   Claude. Used for anything that has to LOOK at a document (scanned bills, quote PDFs and photos),
                        and for text too if AI_PROVIDER=claude or there is no Groq key.
    AI_PROVIDER         "groq" (default) or "claude": which one answers text tasks when both keys are set.
    GROQ_MODEL          the Groq model: default llama-3.3-70b-versatile
    AI_ENABLED          "1" (default) or "0" to switch every Ai_service feature off at once.
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
