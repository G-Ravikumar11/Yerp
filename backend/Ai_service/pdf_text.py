"""The words in a PDF, read here so a text model (Groq) can use them. No AI is involved.

A PDF made by software (a typed bill, an exported quotation) has its text inside it. A scan has only pictures, and this
returns nothing for it; the caller then needs a model that can look at pictures.
"""
import io
import logging

logger = logging.getLogger("Ai_service")

MIN_USEFUL_CHARS = 40


def extract_text(data: bytes, max_pages: int = 25, max_chars: int = 24000) -> str:
    """The text of the first pages of a PDF, or "" when there is none (a scan) or it cannot be read."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            reader.decrypt("")
        out, total = [], 0
        for page in reader.pages[:max_pages]:
            text = (page.extract_text() or "").strip()
            if text:
                out.append(text)
                total += len(text)
            if total >= max_chars:
                break
        return "\n\n".join(out)[:max_chars]
    except Exception as exc:
        logger.warning("Could not read PDF text: %s", exc)
        return ""


def has_text(text: str) -> bool:
    return len((text or "").strip()) >= MIN_USEFUL_CHARS
