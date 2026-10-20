# CineInsight — Authentication & Password Reset API Documentation

This document describes the REST APIs, cryptographic security controls, and frontend integration for CineInsight's secure password reset flow.

---

## Architecture & Security Highlights

1. **Zero-Knowledge User Enumeration Defense:**
   The `POST /api/auth/forgot-password` endpoint returns the identical 200 HTTP response regardless of whether the requested email exists in the database.
2. **Cryptographic Random Tokens:**
   Tokens are generated using Python's `secrets.token_urlsafe(32)` providing 256 bits of entropy.
3. **One-Way Hashing in Database:**
   Raw tokens are NEVER stored in the database. Only SHA-256 hashes (`VARCHAR(64)`) are stored.
4. **Token Expiration & Single Use:**
   Tokens are strictly valid for **15 minutes**. Once consumed, the token's `used_at` timestamp is set, preventing reuse.
5. **Superseded Token Invalidation:**
   Generating a new reset request for an account invalidates all previously issued, unused reset tokens for that user.
6. **Concurrent Replay & Race Condition Protection:**
   The password reset transaction issues a `SELECT ... FOR UPDATE` lock on the token record, preventing simultaneous reuse.
7. **Zero Token Logging:**
   Neither the raw token nor the complete URL containing the token is ever written to application log files.
8. **Sliding-Window Rate Limiting:**
   - Forgot Password: max 5 requests / 15 min per IP; max 3 requests / 15 min per email.
   - Reset Password: max 5 attempts / 15 min per IP.
9. **Referrer Header Suppression:**
   All reset password views and responses return `Referrer-Policy: no-referrer` to prevent query string leakage to third-party assets or search engines.
10. **Modern Password Hashing:**
    Passwords are encrypted using `werkzeug.security.generate_password_hash` (`scrypt`). Plaintext passwords are never stored or logged.

---

## Endpoints

### 1. Request Password Reset Link

* **Endpoint:** `POST /api/auth/forgot-password`
* **Content-Type:** `application/json` (or `application/x-www-form-urlencoded`)
* **Rate Limit:** 5 requests / 15 min per IP, 3 requests / 15 min per email

#### Request Body
```json
{
  "email": "user@example.com"
}
```

#### Success Response
* **Status Code:** `200 OK`
```json
{
  "message": "If an account exists for this email, a password reset link has been sent."
}
```
*(Note: Identical response returned whether the email exists or not.)*

#### Error Responses
* **Status Code:** `400 Bad Request`
```json
{
  "error": "Please provide a valid email address."
}
```
* **Status Code:** `429 Too Many Requests`
```json
{
  "error": "Too many password reset requests. Please try again later.",
  "retry_after": 842
}
```

---

### 2. Reset Password with Token

* **Endpoint:** `POST /api/auth/reset-password`
* **Content-Type:** `application/json` (or `application/x-www-form-urlencoded`)
* **Rate Limit:** 5 attempts / 15 min per IP

#### Request Body
```json
{
  "token": "43-character-urlsafe-reset-token-received-in-email",
  "new_password": "NewSecurePassword123",
  "confirm_password": "NewSecurePassword123"
}
```

#### Success Response
* **Status Code:** `200 OK`
```json
{
  "message": "Password has been reset successfully. Please sign in with your new password."
}
```

#### Error Responses
* **Status Code:** `400 Bad Request` (Invalid or Expired Token)
```json
{
  "error": "Invalid or expired password reset link."
}
```
* **Status Code:** `400 Bad Request` (Weak Password)
```json
{
  "error": "Password must be at least 8 characters long."
}
```
* **Status Code:** `400 Bad Request` (Password Mismatch)
```json
{
  "error": "Passwords do not match."
}
```
* **Status Code:** `429 Too Many Requests`
```json
{
  "error": "Too many password reset attempts. Please try again later.",
  "retry_after": 720
}
```

---

## Web Views

| Route | Method | Description | Headers |
|:---|:---|:---|:---|
| `/signin` | GET, POST | Login page with "Forgot password?" link | Standard |
| `/forgot` | GET, POST | Web form to enter registered email and request reset link | Standard |
| `/reset-password` | GET, POST | Web form to enter new password using `?token=` query param | `Referrer-Policy: no-referrer`<br>`Cache-Control: no-store` |

---

## Database Schema

```sql
CREATE TABLE `password_reset_tokens` (
  `id` INT(11) NOT NULL AUTO_INCREMENT,
  `user_id` INT(11) NOT NULL,
  `token_hash` VARCHAR(64) NOT NULL,
  `expires_at` DATETIME NOT NULL,
  `used_at` DATETIME DEFAULT NULL,
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  INDEX `idx_token_hash` (`token_hash`),
  INDEX `idx_user_id` (`user_id`),
  CONSTRAINT `fk_prt_user_id` FOREIGN KEY (`user_id`) REFERENCES `user` (`User_Id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
```
