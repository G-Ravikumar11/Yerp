"""What an AI "read this" endpoint accepts: any document someone is likely to have, or pasted text. Checked the same
way everywhere.

A PDF (typed or scanned) and a photo go to the model as they are; a Word, Excel, OpenOffice, RTF, CSV or text file is
turned into words first (doc_text). So a vendor's quotation is read in whatever form he sent it.
"""
from typing import List, Optional, Tuple

from fastapi import HTTPException, UploadFile

from app.ai import doc_text
from app.ai.llm_client import Attachment

READABLE = ("application/pdf", "image/jpeg", "image/png", "image/webp", "image/gif")
ACCEPT = doc_text.ACCEPT
MAX_BYTES = 15 * 1024 * 1024


def read_bytes(data: bytes, filename: str, content_type: str, text: str, what: str) -> Tuple[List[Attachment], str]:
    """(attachments, text) for a file already in hand: a PDF or picture to look at, or the file's words added to text."""
    if len(data) > MAX_BYTES:
        raise HTTPException(400, "That file is over 15 MB. Send the quotation as a smaller PDF, or a photo of each page.")
    if not data:
        raise HTTPException(400, "That file is empty.")
    try:
        kind, words, picture = doc_text.to_text_or_picture(data, filename, content_type)
    except doc_text.Unreadable as exc:
        raise HTTPException(400, str(exc))
    if kind == "pdf":
        return [Attachment(data, "application/pdf")], text
    if picture is not None:
        return [Attachment(picture[0], picture[1])], text
    return [], ("%s\n\n%s" % (text, words)).strip() if text else words


def take(file: Optional[UploadFile], text: str, what: str) -> Tuple[List[Attachment], str]:
    """(attachments, text) from the request, or a plain 400 saying what to send."""
    text = (text or "").strip()
    if file is not None and file.filename:
        return read_bytes(file.file.read(), file.filename, file.content_type or "", text, what)
    if not text:
        raise HTTPException(400, "Upload the %s (a PDF, Word, Excel or photo), or paste its text." % what)
    return [], text
