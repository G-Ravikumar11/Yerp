"""The rules and workings behind the auth endpoints."""
import os
from datetime import datetime

from app import models

from app.core.currency import esc
from app.core.security import hash_reset_token


def superadmin_google_emails():
    """The addresses allowed to sign in to the platform console with Google: only those named in
    SUPERADMIN_EMAILS. A row in the table is not enough - one was once made for a default address on
    somebody else's domain."""
    return {e.strip().lower() for e in os.getenv("SUPERADMIN_EMAILS", "").split(",") if e.strip()}


def google_configured() -> bool:
    return bool(os.getenv("GOOGLE_CLIENT_ID") and os.getenv("GOOGLE_CLIENT_SECRET"))


def find_valid_reset(db, token: str):
    """The reset a token refers to, or None if it is unknown, spent or expired."""
    if not token:
        return None
    row = db.query(models.DBPasswordReset).filter(
        models.DBPasswordReset.token_hash == hash_reset_token(token)
    ).first()
    if not row or row.used_at:
        return None
    try:
        expires = datetime.strptime(row.expires_at, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None
    if expires < datetime.now():
        return None
    return row


def reset_email_bodies(link, who, minutes):
    """The same wording for both, so there is one thing to keep right."""
    text_body = (
        f"Hello,\n\nSomeone asked to reset the password for {who} on Y ERP.\n\n"
        f"Open this link to choose a new one:\n{link}\n\n"
        f"The link works once and expires in {minutes} minutes.\n"
        "If this was not you, ignore this email - your password has not changed.\n"
    )
    html_body = f"""
    <!DOCTYPE html>
    <html><body style="font-family:Arial,Helvetica,sans-serif;background:#f1f5f9;margin:0;padding:0;">
      <div style="max-width:520px;margin:0 auto;padding:40px 20px;">
        <div style="background:#fff;border-radius:12px;overflow:hidden;">
          <div style="background:#0f172a;padding:32px;text-align:center;">
            <div style="font-size:13px;letter-spacing:2px;text-transform:uppercase;color:#94a3b8;">Billing</div>
            <div style="font-size:22px;font-weight:800;color:#fff;margin-top:6px;">Reset your password</div>
          </div>
          <div style="padding:28px;">
            <p style="font-size:15px;margin:0 0 18px;">
              Someone asked to reset the password for <strong>{esc(who)}</strong>.
            </p>
            <p style="margin:0 0 24px;">
              <a href="{esc(link)}" style="display:inline-block;background:#0f172a;color:#fff;text-decoration:none;padding:12px 22px;border-radius:8px;font-weight:700;">Choose a new password</a>
            </p>
            <p style="font-size:13px;color:#64748b;margin:0 0 8px;">
              The link works once and expires in {minutes} minutes.
            </p>
            <p style="font-size:13px;color:#64748b;margin:0;">
              If this was not you, ignore this email. Your password has not changed.
            </p>
          </div>
        </div>
      </div>
    </body></html>
    """
    return text_body, html_body
