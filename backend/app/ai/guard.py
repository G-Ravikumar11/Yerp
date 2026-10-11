"""What every AI endpoint does around its model call: who may ask, whether the wallet covers it, what is recorded.

An endpoint written with `run_feature` gets the same behaviour as every other: it works without a key (the plain
checks still run, the AI part says it is unavailable), it is charged only when the model actually produced something,
and each use is written to the audit log.
"""
from typing import Callable

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from app.ai import config
from app.ai.llm_client import AiResult
from app.core.audit import log_audit
from app.services.wallet_ai import charge_after_success, ensure_can_afford


def status() -> dict:
    """What the screens need to know before offering an AI button."""
    return {"enabled": config.enabled(), "configured": config.configured(),
            "claude": bool(config.anthropic_key()), "groq": bool(config.groq_key()), "reads_photos": bool(config.groq_key() or config.anthropic_key()), "available": config.enabled() and config.configured()}


def run_feature(db: Session, request: Request, client, action_key: str, label: str, reference: str,
                call: Callable[[], AiResult]) -> AiResult:
    """Check the wallet, make the call, charge on success, record it. Returns the result either way."""
    if not config.enabled() or not config.configured():
        return call()                 # it will answer "off" or "no_key" without a network call
    ensure_can_afford(db, client.id, action_key)
    result = call()
    if result.ok:
        charge_after_success(db, client.id, action_key, 1, reference[:60])
        log_audit(db, client.id, action_key, "ai", None, label, "%s %s in=%s out=%s" % (
            result.provider, result.model, result.usage.get("input", 0), result.usage.get("output", 0)), request)
        db.commit()
    return result


def refuse(result: AiResult):
    """Turn a failed result into the plain HTTP answer."""
    raise HTTPException(status_code=503 if result.reason in ("off", "no_key", "needs_vision") else 422 if result.reason in ("scanned_pdf", "too_big") else 502, detail=result.message)
