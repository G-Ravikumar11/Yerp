"""What an AI "read this" endpoint accepts: an uploaded picture or PDF, or pasted text. Checked the same way everywhere."""
from typing import List, Optional, Tuple

from fastapi import HTTPException, UploadFile

from Ai_service.llm_client import Attachment

READABLE = ("application/pdf", "image/jpeg", "image/png", "image/webp", "image/gif")
MAX_BYTES = 8 * 1024 * 1024


def take(file: Optional[UploadFile], text: str, what: str) -> Tuple[List[Attachment], str]:
    """(attachments, text) from the request, or a plain 400 saying what to send."""
    text = (text or "").strip()
    attachments: List[Attachment] = []
    if file is not None and file.filename:
        data = file.file.read()
        media = (file.content_type or "").lower()
        if media not in READABLE:
            raise HTTPException(400, "Upload a PDF or a picture (JPG, PNG), or paste the %s as text." % what)
        if len(data) > MAX_BYTES:
            raise HTTPException(400, "That file is over 8 MB.")
        attachments.append(Attachment(data, media))
    elif not text:
        raise HTTPException(400, "Upload the %s, or paste its text." % what)
    return attachments, text
