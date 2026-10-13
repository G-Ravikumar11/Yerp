"""Settings for every AI feature, read from the environment so keys never sit in the code.

Put these in backend/.env (locally) or in the Railway Variables tab (live):

    GROQ_API_KEY        the main key. Groq does everything: text, photos (its vision model), and PDFs that have text
                        in them (read here, then sent as words).
    ANTHROPIC_API_KEY   optional. Claude is used only for what Groq cannot read (a PDF that is a scan, a very large
                        picture), or for everything if AI_PROVIDER=claude.
    AI_PROVIDER         "groq" (default) or "claude": which one answers text tasks when both keys are set.
    GROQ_MODEL          the Groq text model: default openai/gpt-oss-120b
    GROQ_VISION_MODEL   the Groq model for photos: default qwen/qwen3.8-27b
    AI_ENABLED          "1" (default) or "0" to switch every AI feature off at once.
    AI_MODEL_SMART      the model for reading documents and judging: default claude-sonnet-5-5
    AI_MODEL_FAST       the model for short, cheap tasks: default claude-haiku-5-5
    AI_TIMEOUT_SECONDS  how long to wait for an answer: default 60
    DRAWING_3D_PROVIDER "claude" (default), "local" or "groq": who traces a floor plan for the 3D view.
    LOCAL_AI_URL        a local OpenAI-style endpoint, e.g. http://localhost:11434/v1/chat/completions (Ollama)
    LOCAL_AI_MODEL      the local vision model: default qwen2.5vl:7b
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
    return (os.getenv("GROQ_MODEL") or "openai/gpt-oss-120b").strip()


def groq_vision_model() -> str:
    return (os.getenv("GROQ_VISION_MODEL") or "qwen/qwen3.8-27b").strip()


def local_url() -> str:
    """An OpenAI-style chat endpoint on this machine (Ollama: http://localhost:11434/v1/chat/completions). Empty = off."""
    return (os.getenv("LOCAL_AI_URL") or "").strip()


def local_model() -> str:
    return (os.getenv("LOCAL_AI_MODEL") or "qwen2.5vl:7b").strip()


def local_timeout() -> float:
    try:
        return float(os.getenv("LOCAL_AI_TIMEOUT_SECONDS", "600"))   # a laptop GPU takes minutes for one plan
    except ValueError:
        return 600.0


def drawing_3d_provider() -> str:
    """Which model traces a plan for 3D: "claude" (default), "local" or "groq"."""
    return (os.getenv("DRAWING_3D_PROVIDER", "claude") or "claude").strip().lower()


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
