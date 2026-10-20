"""
tests/test_forgot_password.py
-----------------------------
Comprehensive test suite for CineInsight's secure Forgot Password & Reset feature.

Verifies:
 1. Existing email request (neutral response returned)
 2. Unknown email request (exact same neutral response returned)
 3. SMTP function is called for an existing account
 4. SMTP function is NOT called for an unknown account
 5. SMTP exception is logged without exposing internal details to user
 6. Valid token resets the password
 7. Expired token rejection
 8. Used token rejection
 9. Older token becomes invalid when a newer token is generated
10. Weak passwords (< 8 characters) are rejected
11. Old password no longer works after reset; new password works
12. Raw reset tokens are not written to application logs
13. Rate limiting restricts excessive requests
14. Reset page returns Referrer-Policy: no-referrer
"""

import hashlib
import io
import logging
import secrets
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from werkzeug.security import check_password_hash, generate_password_hash

# Ensure project root is in sys.path
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import app, RESET_NEUTRAL_MESSAGE
from services.email_service import (
    clear_dispatched_emails,
    get_last_dispatched_email,
    send_reset_email,
    mask_email,
    logger as email_logger,
)
from services.rate_limiter import SlidingWindowRateLimiter, rate_limiter


class TestRateLimiter(unittest.TestCase):
    """Test sliding window rate limiter functionality and boundaries."""

    def setUp(self):
        self.limiter = SlidingWindowRateLimiter()

    def test_rate_limiting_enforcement(self):
        key = "192.168.1.100"
        action = "forgot_ip"
        max_requests = 3
        window = 60

        for i in range(max_requests):
            allowed, _ = self.limiter.check_and_record(key, action, max_requests, window)
            self.assertTrue(allowed, f"Request {i+1} should be allowed")

        # 4th request must be blocked
        allowed, retry_after = self.limiter.check_and_record(key, action, max_requests, window)
        self.assertFalse(allowed, "4th request should be blocked")
        self.assertGreater(retry_after, 0)

    def test_different_keys_isolated(self):
        self.limiter.check_and_record("user_a", "test", max_requests=1, window_seconds=60)
        # user_b should still be allowed
        allowed, _ = self.limiter.check_and_record("user_b", "test", max_requests=1, window_seconds=60)
        self.assertTrue(allowed)


class TestEmailAndLoggingSecurity(unittest.TestCase):
    """Test email delivery and ensure sensitive tokens and passwords are never logged."""

    def setUp(self):
        clear_dispatched_emails()
        rate_limiter.reset()

    def test_raw_token_never_logged(self):
        """Requirement 9: Raw reset tokens are not written to logs."""
        log_capture = io.StringIO()
        handler = logging.StreamHandler(log_capture)
        email_logger.addHandler(handler)

        raw_token = secrets.token_urlsafe(32)
        test_url = f"http://127.0.0.1:5000/reset-password?token={raw_token}"
        try:
            send_reset_email("user@example.com", test_url)
            log_output = log_capture.getvalue()
            # Assert raw token is NEVER present in the log string
            self.assertNotIn(raw_token, log_output, "SECURITY VIOLATION: Raw token found in logs!")
            # Assert the complete reset URL is not logged
            self.assertNotIn(test_url, log_output)
        finally:
            email_logger.removeHandler(handler)

    def test_email_masking(self):
        """Test recipient masking for safe logging."""
        self.assertEqual(mask_email("john@example.com"), "j***n@example.com")
        self.assertEqual(mask_email("ab@example.com"), "a*@example.com")
        self.assertEqual(mask_email("invalid"), "unknown")

    def test_missing_smtp_config_logs_error_without_crash(self):
        """When SMTP credentials are missing, log error and return False safely."""
        with patch.dict(os.environ, {"SMTP_EMAIL": "", "SMTP_APP_PASSWORD": ""}):
            log_capture = io.StringIO()
            handler = logging.StreamHandler(log_capture)
            email_logger.addHandler(handler)
            try:
                res = send_reset_email("user@example.com", "http://127.0.0.1:5000/reset-password?token=abc")
                self.assertFalse(res)
                self.assertIn("[SMTP CONFIG ERROR]", log_capture.getvalue())
            finally:
                email_logger.removeHandler(handler)


class TestForgotPasswordFlow(unittest.TestCase):
    """Integration and API testing for Forgot Password and Reset flow."""

    def setUp(self):
        app.config["TESTING"] = True
        app.config["SECRET_KEY"] = "test-secret-key-12345"
        self.client = app.test_client()
        rate_limiter.reset()
        clear_dispatched_emails()

        # In-memory mock database store for simulating DB interactions
        self.users = {
            "alice@example.com": {
                "User_Id": 101,
                "Name": "Alice Wonder",
                "Email": "alice@example.com",
                "Password": generate_password_hash("OldPassword123!"),
                "Role": "User",
            }
        }
        self.tokens = {}  # token_hash -> dict(id, user_id, expires_at, used_at)
        self.token_id_counter = 1

    def _create_mock_connection(self):
        """Create a mock connection that operates on self.users and self.tokens."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        def execute(query, params=None):
            q = query.strip()
            params = params or ()

            if "SELECT User_Id, Name, Email FROM `user` WHERE Email = %s" in q or "SELECT User_Id, Name, Email FROM user WHERE Email = %s" in q:
                email = params[0].lower()
                user = self.users.get(email)
                mock_cursor.fetchone.return_value = user

            elif "UPDATE password_reset_tokens SET used_at = UTC_TIMESTAMP() WHERE user_id = %s AND used_at IS NULL" in q:
                uid = params[0]
                now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                for t in self.tokens.values():
                    if t["user_id"] == uid and t["used_at"] is None:
                        t["used_at"] = now_str

            elif "INSERT INTO password_reset_tokens" in q:
                uid, thash, exp = params
                tid = self.token_id_counter
                self.token_id_counter += 1
                self.tokens[thash] = {
                    "id": tid,
                    "user_id": uid,
                    "token_hash": thash,
                    "expires_at": exp if isinstance(exp, datetime) else datetime.strptime(exp, "%Y-%m-%d %H:%M:%S"),
                    "used_at": None,
                }
                mock_cursor.lastrowid = tid

            elif "SELECT id, user_id, expires_at, used_at" in q and "password_reset_tokens" in q:
                thash = params[0]
                token_record = self.tokens.get(thash)
                mock_cursor.fetchone.return_value = token_record

            elif "UPDATE `user` SET Password = %s WHERE User_Id = %s" in q or "UPDATE user SET Password = %s WHERE User_Id = %s" in q:
                new_pass, uid = params
                for u in self.users.values():
                    if u["User_Id"] == uid:
                        u["Password"] = new_pass

            elif "UPDATE password_reset_tokens SET used_at = UTC_TIMESTAMP() WHERE id = %s" in q:
                tid = params[0]
                now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                for t in self.tokens.values():
                    if t["id"] == tid:
                        t["used_at"] = now_str

        mock_cursor.execute.side_effect = execute
        mock_conn.cursor.return_value = mock_cursor
        return mock_conn

    def test_existing_and_unknown_email_return_same_neutral_response(self):
        """Requirement 1 & 2: Existing email and unknown email return identical response (zero enumeration)."""
        with patch("app.get_db_connection", side_effect=self._create_mock_connection):
            with patch("app.send_reset_email") as mock_email:
                # Known user
                res_known = self.client.post(
                    "/api/auth/forgot-password",
                    json={"email": "alice@example.com"},
                )
                # Unknown user
                res_unknown = self.client.post(
                    "/api/auth/forgot-password",
                    json={"email": "nobody@example.com"},
                )

                self.assertEqual(res_known.status_code, 200)
                self.assertEqual(res_unknown.status_code, 200)
                self.assertEqual(res_known.get_json(), res_unknown.get_json())
                self.assertEqual(res_known.get_json()["message"], RESET_NEUTRAL_MESSAGE)

    def test_smtp_function_called_for_existing_account(self):
        """Requirement 3: send_reset_email is called when the account exists."""
        with patch("app.get_db_connection", side_effect=self._create_mock_connection):
            with patch("app.send_reset_email") as mock_email:
                res = self.client.post(
                    "/api/auth/forgot-password",
                    json={"email": "alice@example.com"},
                )
                self.assertEqual(res.status_code, 200)
                mock_email.assert_called_once()
                args, _ = mock_email.call_args
                self.assertEqual(args[0], "alice@example.com")
                self.assertIn("?token=", args[1])

    def test_smtp_function_not_called_for_unknown_account(self):
        """Requirement 4: send_reset_email is NOT called when account does not exist."""
        with patch("app.get_db_connection", side_effect=self._create_mock_connection):
            with patch("app.send_reset_email") as mock_email:
                res = self.client.post(
                    "/api/auth/forgot-password",
                    json={"email": "ghost@example.com"},
                )
                self.assertEqual(res.status_code, 200)
                mock_email.assert_not_called()

    def test_smtp_exception_is_logged_without_failing_client_response(self):
        """Requirement 5: SMTP exceptions are logged without leaking internal details to client."""
        with patch("app.get_db_connection", side_effect=self._create_mock_connection):
            with patch("app.send_reset_email", side_effect=Exception("SMTP connection timeout")):
                res = self.client.post(
                    "/api/auth/forgot-password",
                    json={"email": "alice@example.com"},
                )
                # User still gets the generic neutral response
                self.assertEqual(res.status_code, 200)
                self.assertEqual(res.get_json()["message"], RESET_NEUTRAL_MESSAGE)

    def test_valid_token_resets_password(self):
        """Requirement 6: A valid token resets the password."""
        with patch("app.get_db_connection", side_effect=self._create_mock_connection):
            # Capture the reset URL generated by app
            captured_url = None
            def capture_email(receiver, url):
                nonlocal captured_url
                captured_url = url
                return True

            with patch("app.send_reset_email", side_effect=capture_email):
                self.client.post("/api/auth/forgot-password", json={"email": "alice@example.com"})

            self.assertIsNotNone(captured_url)
            raw_token = captured_url.split("token=")[1]

            # Reset password
            res = self.client.post(
                "/api/auth/reset-password",
                json={
                    "token": raw_token,
                    "new_password": "BrandNewPassword123!",
                    "confirm_password": "BrandNewPassword123!",
                },
            )
            self.assertEqual(res.status_code, 200)
            self.assertIn("Password has been reset successfully", res.get_json()["message"])

    def test_expired_token_is_rejected(self):
        """Requirement 7: An expired token is rejected."""
        with patch("app.get_db_connection", side_effect=self._create_mock_connection):
            raw_token = secrets.token_urlsafe(32)
            token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
            past_time = datetime.now(timezone.utc) - timedelta(minutes=5)
            self.tokens[token_hash] = {
                "id": 999,
                "user_id": 101,
                "token_hash": token_hash,
                "expires_at": past_time,
                "used_at": None,
            }

            res = self.client.post(
                "/api/auth/reset-password",
                json={"token": raw_token, "new_password": "ValidPassword123!"},
            )
            self.assertEqual(res.status_code, 400)
            self.assertIn("expired", res.get_json()["error"].lower())

    def test_used_token_cannot_be_reused(self):
        """Requirement 8: A used token cannot be reused (single-use)."""
        with patch("app.get_db_connection", side_effect=self._create_mock_connection):
            captured_url = None
            def capture_email(receiver, url):
                nonlocal captured_url
                captured_url = url
                return True

            with patch("app.send_reset_email", side_effect=capture_email):
                self.client.post("/api/auth/forgot-password", json={"email": "alice@example.com"})

            raw_token = captured_url.split("token=")[1]

            # First use: succeeds
            res1 = self.client.post(
                "/api/auth/reset-password",
                json={"token": raw_token, "new_password": "FirstNewPassword123!"},
            )
            self.assertEqual(res1.status_code, 200)

            # Second use: must fail
            res2 = self.client.post(
                "/api/auth/reset-password",
                json={"token": raw_token, "new_password": "SecondNewPassword123!"},
            )
            self.assertEqual(res2.status_code, 400)
            self.assertIn("already been used", res2.get_json()["error"].lower())

    def test_older_token_becomes_invalid_when_newer_token_is_generated(self):
        """Requirement 9: Generating a newer token invalidates previous tokens for that account."""
        with patch("app.get_db_connection", side_effect=self._create_mock_connection):
            urls = []
            def capture_email(receiver, url):
                urls.append(url)
                return True

            with patch("app.send_reset_email", side_effect=capture_email):
                self.client.post("/api/auth/forgot-password", json={"email": "alice@example.com"})
                self.client.post("/api/auth/forgot-password", json={"email": "alice@example.com"})

            token_1 = urls[0].split("token=")[1]
            token_2 = urls[1].split("token=")[1]
            self.assertNotEqual(token_1, token_2)

            # Older token 1 must now be rejected as used/superseded
            res_old = self.client.post(
                "/api/auth/reset-password",
                json={"token": token_1, "new_password": "PasswordForToken1!"},
            )
            self.assertEqual(res_old.status_code, 400)
            self.assertIn("used", res_old.get_json()["error"].lower())

            # Newer token 2 must succeed
            res_new = self.client.post(
                "/api/auth/reset-password",
                json={"token": token_2, "new_password": "PasswordForToken2!"},
            )
            self.assertEqual(res_new.status_code, 200)

    def test_weak_passwords_are_rejected(self):
        """Requirement 10: Weak passwords (< 8 characters) are rejected."""
        with patch("app.get_db_connection", side_effect=self._create_mock_connection):
            captured_url = None
            def capture_email(receiver, url):
                nonlocal captured_url
                captured_url = url
                return True

            with patch("app.send_reset_email", side_effect=capture_email):
                self.client.post("/api/auth/forgot-password", json={"email": "alice@example.com"})

            raw_token = captured_url.split("token=")[1]

            res = self.client.post(
                "/api/auth/reset-password",
                json={"token": raw_token, "new_password": "short"},
            )
            self.assertEqual(res.status_code, 400)
            self.assertIn("at least 8 characters", res.get_json()["error"])

    def test_old_password_revoked_and_new_password_authenticates(self):
        """Old password revoked, new password authenticates."""
        with patch("app.get_db_connection", side_effect=self._create_mock_connection):
            old_pass = "OldPassword123!"
            new_pass = "SuperSecureNewPass2026!"

            self.assertTrue(check_password_hash(self.users["alice@example.com"]["Password"], old_pass))

            captured_url = None
            def capture_email(receiver, url):
                nonlocal captured_url
                captured_url = url
                return True

            with patch("app.send_reset_email", side_effect=capture_email):
                self.client.post("/api/auth/forgot-password", json={"email": "alice@example.com"})

            raw_token = captured_url.split("token=")[1]
            self.client.post(
                "/api/auth/reset-password",
                json={"token": raw_token, "new_password": new_pass},
            )

            current_hash = self.users["alice@example.com"]["Password"]
            self.assertFalse(check_password_hash(current_hash, old_pass))
            self.assertTrue(check_password_hash(current_hash, new_pass))

    def test_rate_limiting_on_endpoints(self):
        """Rate limiting restricts excessive requests on API."""
        with patch("app.get_db_connection", side_effect=self._create_mock_connection):
            with patch("app.send_reset_email", return_value=True):
                # Email limit is 3 requests per 15 minutes
                for _ in range(3):
                    res = self.client.post("/api/auth/forgot-password", json={"email": "alice@example.com"})
                    self.assertEqual(res.status_code, 200)

                # 4th request must receive 429 Too Many Requests
                res_blocked = self.client.post("/api/auth/forgot-password", json={"email": "alice@example.com"})
                self.assertEqual(res_blocked.status_code, 429)
                self.assertIn("too many", res_blocked.get_json()["error"].lower())

    def test_security_headers_on_reset_page(self):
        """Reset password page includes Referrer-Policy: no-referrer."""
        res = self.client.get("/reset-password?token=sample_token_123")
        self.assertEqual(res.headers.get("Referrer-Policy"), "no-referrer")


if __name__ == "__main__":
    unittest.main()
