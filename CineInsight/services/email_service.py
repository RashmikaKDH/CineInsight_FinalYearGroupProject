"""
services/email_service.py
-------------------------
Secure SMTP email dispatch service for CineInsight password reset.

Environment variables:
- SMTP_HOST (default: smtp.gmail.com)
- SMTP_PORT (default: 465)
- SMTP_EMAIL (sender Gmail address, e.g. project@gmail.com)
- SMTP_APP_PASSWORD (16-character Gmail App Password)
- RESET_PASSWORD_URL (default: http://127.0.0.1:5000/reset-password)
"""

import os
import sys
import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional, Dict, Any, List

# 1. Load environment variables from .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logger = logging.getLogger("cineinsight.email")
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter("[%(asctime)s] %(levelname)s in %(name)s: %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

# Test sink allowing automated tests to inspect dispatches without live SMTP
_TEST_DISPATCH_LOG: List[Dict[str, Any]] = []


def get_last_dispatched_email() -> Optional[Dict[str, Any]]:
    """Return the most recently dispatched email dictionary from the test sink."""
    if _TEST_DISPATCH_LOG:
        return _TEST_DISPATCH_LOG[-1]
    return None


def clear_dispatched_emails() -> None:
    """Clear test sink dispatches."""
    _TEST_DISPATCH_LOG.clear()


def mask_email(email: str) -> str:
    """
    Mask an email address for safe logging without exposing PII.
    Example: 'johndoe@example.com' -> 'j***e@example.com'
    """
    if not email or "@" not in email:
        return "unknown"
    local, domain = email.split("@", 1)
    if len(local) <= 2:
        masked_local = local[0] + "*"
    else:
        masked_local = local[0] + "***" + local[-1]
    return f"{masked_local}@{domain}"


def get_email_config() -> Dict[str, Any]:
    """Load and return email configuration from environment variables."""
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com").strip()
    port_val = os.environ.get("SMTP_PORT", "465").strip()
    port = int(port_val) if port_val.isdigit() else 465

    # Consistent SMTP credentials (with fallback support)
    email_user = (os.environ.get("SMTP_EMAIL") or os.environ.get("SMTP_USERNAME") or "").strip()
    email_pass = (os.environ.get("SMTP_APP_PASSWORD") or os.environ.get("SMTP_PASSWORD") or "").strip()

    reset_base_url = os.environ.get(
        "RESET_PASSWORD_URL", "http://127.0.0.1:5000/reset-password"
    ).strip()

    return {
        "smtp_host": host,
        "smtp_port": port,
        "smtp_email": email_user,
        "smtp_app_password": email_pass,
        "reset_base_url": reset_base_url,
    }


def send_reset_email(receiver: str, reset_url: str) -> bool:
    """
    Send password reset email to the receiver containing the secure reset URL.

    Security rules:
    - Never logs passwords, tokens, or the full reset URL.
    - Masks receiver address in logs (e.g. u***r@example.com).
    - Uses port 465 (SSL) or 587 (TLS) with connection timeout.
    - Displays clear errors in console during development when configuration is missing.
    """
    config = get_email_config()
    subject = "Reset Your CineInsight Password"

    # Plain-text email body
    text_content = f"""Hello,

We received a request to reset the password for your CineInsight account.

To set a new password, click or paste the following link into your browser:
{reset_url}

Important:
- This link will expire in 15 minutes.
- It can only be used once.

If you did not request a password reset, you can safely ignore this email. Your password will remain unchanged.

Best regards,
The CineInsight Team
"""

    # Rich HTML email body matching CineInsight branding
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>CineInsight Password Reset</title>
</head>
<body style="margin: 0; padding: 0; font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #0F172A; color: #F8FAFC;">
    <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="min-width: 100%; background-color: #0F172A; padding: 40px 10px;">
        <tr>
            <td align="center">
                <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="max-width: 540px; background-color: #1E293B; border-radius: 16px; border: 1px solid #334155; overflow: hidden; box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.4);">
                    <tr>
                        <td style="padding: 28px 36px 20px; text-align: left; border-bottom: 1px solid #334155;">
                            <div style="display: inline-block; vertical-align: middle; background-color: #E35614; width: 36px; height: 36px; border-radius: 8px; text-align: center; line-height: 36px;">
                                <span style="color: #FFFFFF; font-weight: bold; font-size: 20px;">C</span>
                            </div>
                            <span style="display: inline-block; vertical-align: middle; margin-left: 12px; font-size: 20px; font-weight: 700; color: #FFFFFF; letter-spacing: -0.5px;">CineInsight</span>
                        </td>
                    </tr>
                    <tr>
                        <td style="padding: 36px; text-align: left;">
                            <h1 style="margin: 0 0 16px; font-size: 22px; font-weight: 700; color: #FFFFFF;">Password Reset Request</h1>
                            <p style="margin: 0 0 20px; font-size: 15px; line-height: 1.6; color: #94A3B8;">
                                We received a request to reset your CineInsight account password. Click the button below to set a new password:
                            </p>
                            <div style="text-align: center; margin: 28px 0;">
                                <a href="{reset_url}" target="_blank" style="display: inline-block; padding: 14px 32px; background: linear-gradient(135deg, #E35614 0%, #FF7336 100%); color: #FFFFFF; font-size: 15px; font-weight: 600; text-decoration: none; border-radius: 8px; box-shadow: 0 4px 14px rgba(227, 86, 20, 0.4);">
                                    Reset Password
                                </a>
                            </div>
                            <div style="background-color: #0F172A; border: 1px solid #334155; border-radius: 8px; padding: 14px 16px; margin: 24px 0;">
                                <p style="margin: 0; font-size: 13px; color: #CBD5E1; line-height: 1.5;">
                                    ⏰ <strong>Important:</strong> This link is valid for <strong>15 minutes</strong> and can only be used once.
                                </p>
                            </div>
                            <p style="margin: 20px 0 0; font-size: 13px; color: #64748B; line-height: 1.5;">
                                If you did not request a password reset, please ignore this email. Your CineInsight account remains secure.
                            </p>
                            <hr style="border: none; border-top: 1px solid #334155; margin: 24px 0;" />
                            <p style="margin: 0; font-size: 12px; color: #64748B; word-break: break-all;">
                                Button not working? Copy and paste this link in your browser:<br>
                                <span style="color: #94A3B8;">{reset_url}</span>
                            </p>
                        </td>
                    </tr>
                    <tr>
                        <td style="padding: 18px 36px; text-align: center; border-top: 1px solid #334155; background-color: #182234;">
                            <p style="margin: 0; font-size: 12px; color: #64748B;">
                                &copy; 2026 CineInsight — AI-Driven Multimodal Video Sentiment Analysis
                            </p>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>
"""

    # Record in test sink for automated unit tests
    _TEST_DISPATCH_LOG.append({
        "receiver": receiver,
        "recipient": receiver,
        "subject": subject,
        "reset_url": reset_url,
    })

    host = config["smtp_host"]
    port = config["smtp_port"]
    user = config["smtp_email"].strip()
    password = config["smtp_app_password"].replace(" ", "").strip()

    # Validate configuration
    if not user or not password:
        logger.error(
            "[SMTP CONFIG ERROR] Missing SMTP_EMAIL or SMTP_APP_PASSWORD in environment. Cannot send reset email to %s.",
            mask_email(receiver),
        )
        return False

    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = f"CineInsight Security <{user}>"
    message["To"] = receiver

    part_text = MIMEText(text_content, "plain", "utf-8")
    part_html = MIMEText(html_content, "html", "utf-8")
    message.attach(part_text)
    message.attach(part_html)

    server = None
    try:
        if port == 465:
            # Port 465 uses SSL
            server = smtplib.SMTP_SSL(host, port, timeout=15)
        else:
            # Port 587 (or other) uses STARTTLS
            server = smtplib.SMTP(host, port, timeout=15)
            server.starttls()

        server.login(user, password)
        server.sendmail(user, [receiver], message.as_string())
        logger.info(
            "Password reset email sent successfully via SMTP (%s:%d) to %s",
            host,
            port,
            mask_email(receiver),
        )
        return True
    except Exception as e:
        logger.error(
            "Failed to send password reset email to %s via %s:%d [%s: %s]",
            mask_email(receiver),
            host,
            port,
            type(e).__name__,
            str(e),
        )
        return False
    finally:
        if server is not None:
            try:
                server.quit()
            except Exception:
                pass


# Backward compatibility wrapper
def send_password_reset_email(recipient_email: str, recipient_name: str, raw_token: str) -> bool:
    """Compatibility wrapper that constructs the reset URL and delegates to send_reset_email."""
    config = get_email_config()
    reset_url = f"{config['reset_base_url']}?token={raw_token}"
    return send_reset_email(recipient_email, reset_url)
