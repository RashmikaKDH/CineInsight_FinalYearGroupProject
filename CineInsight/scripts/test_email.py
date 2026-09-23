"""
scripts/test_email.py
---------------------
SMTP Smoke-Test Script for CineInsight.

Validates SMTP configuration and tests email delivery without exposing credentials.

Usage:
    # 1. Validate configuration only (does not send an email)
    python scripts/test_email.py

    # 2. Send a real test email to an explicit recipient
    python scripts/test_email.py recipient@example.com
"""

import os
import sys
import smtplib
from email.mime.text import MIMEText

# 1. Load .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def mask_str(s: str, visible: int = 2) -> str:
    """Mask a string for safe display."""
    if not s:
        return "<NOT SET>"
    if len(s) <= visible * 2:
        return "*" * len(s)
    return s[:visible] + "*" * (len(s) - visible * 2) + s[-visible:]


def test_smtp():
    print("=" * 60)
    print("  CineInsight — SMTP Connection & Delivery Smoke Test")
    print("=" * 60)

    host = os.environ.get("SMTP_HOST", "smtp.gmail.com").strip()
    port_val = os.environ.get("SMTP_PORT", "465").strip()
    port = int(port_val) if port_val.isdigit() else 465

    user = (os.environ.get("SMTP_EMAIL") or os.environ.get("SMTP_USERNAME") or "").strip()
    password = (os.environ.get("SMTP_APP_PASSWORD") or os.environ.get("SMTP_PASSWORD") or "").replace(" ", "").strip()
    reset_url = os.environ.get("RESET_PASSWORD_URL", "http://127.0.0.1:5000/reset-password").strip()

    # Diagnostic summary (masked)
    print(f"SMTP Host:          {host}")
    print(f"SMTP Port:          {port}")
    print(f"SMTP Sender Email:  {mask_str(user, 3)}")
    print(f"SMTP Password:      {'[CONFIGURED]' if password else '<MISSING>'}")
    print(f"Reset Password URL: {reset_url}")
    print("-" * 60)

    # 1. Validation checks
    if not user or not password:
        print("\n[ERROR] SMTP credentials are not configured in your .env file!")
        print("Please add the following to your CineInsight/.env file:")
        print("    SMTP_HOST=smtp.gmail.com")
        print("    SMTP_PORT=465")
        print("    SMTP_EMAIL=yourgmail@gmail.com")
        print("    SMTP_APP_PASSWORD=your_16_char_app_password")
        print("\nFor Gmail:")
        print("  1. Go to https://myaccount.google.com/apppasswords")
        print("  2. Create an App Password (named 'CineInsight')")
        print("  3. Paste the 16-character code into SMTP_APP_PASSWORD")
        sys.exit(1)

    # 2. Check if a recipient was provided
    if len(sys.argv) < 2:
        print("\n[INFO] No test recipient specified. Validating SMTP handshake & authentication only...")
        recipient = None
    else:
        recipient = sys.argv[1].strip()
        print(f"\n[INFO] Test recipient specified: {recipient}")

    # 3. Connect and authenticate
    server = None
    try:
        print(f"Connecting to {host}:{port}...")
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=15)
        else:
            server = smtplib.SMTP(host, port, timeout=15)
            server.starttls()

        print("Authenticating credentials...")
        server.login(user, password)
        print("[SUCCESS] SMTP Authentication successful!")

        # 4. If recipient provided, send test email
        if recipient:
            print(f"Sending test email to {recipient}...")
            msg = MIMEText(
                "Hello!\n\nThis is a smoke test email from CineInsight to verify that your SMTP email settings are working correctly.\n\nBest regards,\nCineInsight Security Team",
                "plain",
                "utf-8"
            )
            msg["Subject"] = "CineInsight — SMTP Smoke Test Successful"
            msg["From"] = f"CineInsight Security <{user}>"
            msg["To"] = recipient

            server.sendmail(user, [recipient], msg.as_string())
            print(f"[SUCCESS] Test email successfully delivered to {recipient}!")
            print("Please check your Inbox (and Spam/Junk folder) to verify receipt.")
        else:
            print("\n[TIP] To send a real test email, run:")
            print("    python scripts/test_email.py your_email@example.com")

        print("=" * 60)
        sys.exit(0)

    except smtplib.SMTPAuthenticationError as e:
        print(f"\n[ERROR] Authentication Failed: {e}")
        print("Causes:")
        print("  1. Incorrect Gmail address or App Password.")
        print("  2. If using Gmail, you MUST use an App Password, not your standard account password.")
        print("  3. 2-Step Verification must be enabled on your Google account.")
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] SMTP Test Failed [{type(e).__name__}]: {e}")
        sys.exit(1)
    finally:
        if server is not None:
            try:
                server.quit()
            except Exception:
                pass


if __name__ == "__main__":
    test_smtp()
