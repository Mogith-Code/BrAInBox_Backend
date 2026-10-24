# `auth` module

| | |
|---|---|
| **Owner** | Mogith |
| **Purpose** | Our `users` row for each Firebase account; 6-digit codes for email verification and password reset. |
| **Tables** | `users`, `email_codes`, `password_reset_tokens` |
| **Branch** | `feature/auth/<short-name>` (this work: `feature/auth/email-codes`) |

## How sign-in works

1. The app signs the student in with **Firebase Auth** (email + password, or Google).
2. The app sends the Firebase ID token on every call: `Authorization: Bearer <token>`.
3. After sign-up the app calls `POST /auth/register` once. That creates our `users` row.
   Every other endpoint needs that row (otherwise `401 USER_NOT_REGISTERED`).

Passwords are **never** stored in our database. Firebase keeps them.

## Why we send our own 6-digit codes

Firebase's built-in verification and reset emails use **links**, but our designs use **6-digit codes**. So the
backend creates, emails and checks them:

| Rule | Value |
|---|---|
| Code | 6 random digits (`secrets`) |
| Stored as | HMAC-SHA256 with `AUTH_CODE_SECRET` (never the raw code) |
| Valid for | 10 minutes |
| Wrong tries | 5, then the code is dead (`TOO_MANY_ATTEMPTS`) |
| Resend | after 60 s (`RESEND_TOO_SOON`, 429, with `retry_after` + `Retry-After` header) |
| New code | cancels older codes for the same purpose |

- **Verify email**: after a correct code we set `users.email_verified = true` **and** call
  `firebase_admin.auth.update_user(uid, email_verified=True)`.
- **Reset password**: correct code → `reset_token` (random 256-bit, stored hashed, single use, 10 min) →
  the app sends the new password → we call `update_user(uid, password=...)` → the app signs in again.
- **Unknown emails**: `password-reset/send` always answers `{sent: true}` and applies the same cooldown, but no
  email is sent. Nobody can find out which emails are registered.
- **Google users** arrive with `email_verified: true` in the token. We copy that on `register` and `me`.

## Endpoints

| Method & path | Auth | Request | Response | Errors |
|---|---|---|---|---|
| `POST /auth/register` | token | `{full_name, phone?, consent: true}` | `UserOut` (201 new / 200 existing) | `CONSENT_REQUIRED`, `INVALID_PHONE`, `EMAIL_IN_USE` |
| `GET /auth/me` | token | – | `UserOut` | `USER_NOT_FOUND` (404) |
| `PATCH /auth/me` | token | `{full_name?, phone?}` (`phone: null` removes it) | `UserOut` | `INVALID_PHONE` |
| `DELETE /auth/me` | token | – | 204 | `FIREBASE_ERROR` (503) |
| `POST /auth/email-code/send` | token | – | `{sent, resend_in: 60, expires_in: 600, dev_code?}` | `ALREADY_VERIFIED`, `RESEND_TOO_SOON` |
| `POST /auth/email-code/verify` | token | `{code}` | `UserOut` | `CODE_INVALID` (+`attempts_left`), `CODE_EXPIRED`, `TOO_MANY_ATTEMPTS` |
| `POST /auth/password-reset/send` | none | `{email}` | always `{sent, resend_in, expires_in, dev_code?}` | `RESEND_TOO_SOON` |
| `POST /auth/password-reset/verify` | none | `{email, code}` | `{reset_token, expires_in: 600}` | `CODE_INVALID`, `CODE_EXPIRED`, `TOO_MANY_ATTEMPTS` |
| `POST /auth/password-reset/complete` | none | `{reset_token, new_password}` | `{reset: true}` | `RESET_TOKEN_INVALID`, `WEAK_PASSWORD`, `FIREBASE_ERROR` |

`UserOut`: `{id, email, full_name, phone, role, email_verified, onboarding: {profile_completed, diagnostic_completed, diagnostic_skipped}}`

- **Phone**: optional, Sri Lankan mobiles only, normalised to E.164 (`077 123 4567` → `+94771234567`).
- **Password policy**: at least 8 characters, with a letter and a number (the app checks it too).

## Email

`api/core/email.py`: `EMAIL_BACKEND=console` prints the email in the api log (body only in `ENVIRONMENT=dev`);
`EMAIL_BACKEND=smtp` sends real email (`SMTP_*`, `EMAIL_FROM`).

- If sending fails, nothing is saved: the older code stays valid, there is **no** 60-second cooldown, and the app gets
  `503 EMAIL_SEND_FAILED` (or `EMAIL_NOT_CONFIGURED` when `SMTP_HOST` is empty), so "Resend" works at once.
- Emails have `Date` + `Message-ID` headers (fewer spam-folder hits). The logo is shown only when `LOGO_URL` is a
  public `https://` address.

**Testing without email (dev only):** set `ENVIRONMENT=dev` and `DEV_EXPOSE_CODES=true`, and the send endpoints
also return `"dev_code"`. It is ignored in every other environment (tested).

### Sending real OTP emails with Gmail (free, about 500 emails a day)

1. Make (or use) a Google account for the project, e.g. `brainbox.app@gmail.com`.
2. Turn on **2-Step Verification**: <https://myaccount.google.com/security>.
3. Create an **App Password**: <https://myaccount.google.com/apppasswords> → name it "BrAInBox backend" → copy the
   16 letters (spaces don't matter). This is **not** your normal password, and it goes **only** in `.env`.
4. In `.env`:
   ```
   EMAIL_BACKEND=smtp
   SMTP_HOST=smtp.gmail.com
   SMTP_PORT=587
   SMTP_USE_TLS=true
   SMTP_USER=brainbox.app@gmail.com
   SMTP_PASSWORD=abcdefghijklmnop
   EMAIL_FROM=BrAInBox <brainbox.app@gmail.com>
   ```
5. Check it: `python scripts/send_test_email.py --to your.name@gmail.com` → "OK: sent". If you see
   "rejected the username/password", the App Password is wrong or 2-Step Verification is off.
6. Restart the api (`docker compose up -d` or uvicorn). Codes now arrive by email.

For more volume later, switch to a mail provider with SMTP (Brevo, SendGrid, Amazon SES): only the `SMTP_*` values change.

## Firebase project setup (once, by Mogith)

1. <https://console.firebase.google.com> → **Add project** (e.g. `brainbox`).
2. **Authentication → Sign-in method**: enable **Email/Password** and **Google**.
3. **Project settings → General**: copy the **Project ID** → `.env` `FIREBASE_PROJECT_ID=...`.
4. **Project settings → Service accounts → Generate new private key** → save it as
   `secrets/firebase-service-account.json` (git-ignored, never commit it) →
   `GOOGLE_APPLICATION_CREDENTIALS=./secrets/firebase-service-account.json`.
   Needed so the backend can mark emails verified, set new passwords and delete accounts.
5. Add the Android/iOS/web apps in the same project for the Flutter team (`flutterfire configure`).

## Registration with OTP: the whole flow (Firebase + this backend)

Firebase Auth creates the account and signs in. Firebase can't email 6-digit codes (only links), so **this backend**
sends and checks the OTP.

| # | Screen | Flutter app | Backend |
|---|---|---|---|
| 1 | Create account | `FirebaseAuth.instance.createUserWithEmailAndPassword(email, password)` | – |
| 2 | (same tap) | `POST /api/v1/auth/register` with the ID token, `{full_name, phone, consent: true}` | creates `users` row → 201 |
| 3 | (same tap) | `POST /api/v1/auth/email-code/send` | emails the 6-digit code |
| 4 | Check your inbox | user types the code → `POST /api/v1/auth/email-code/verify {code}` | marks the email verified (DB + Firebase) |
| 5 | (after verify) | `await FirebaseAuth.instance.currentUser!.reload()` then `getIdToken(true)` | – |
| 6 | Resend button | wait `resend_in` seconds; on 429 use `retry_after` | new code, old one cancelled |
| 7 | Next | `GET /api/v1/auth/me` → `onboarding` says which screen comes next | – |

Google sign-in skips steps 3–5: the token already says `email_verified: true`.
Forgot password uses the same idea: `password-reset/send` → `verify` → `complete`, then the app signs in with the new
password (`signInWithEmailAndPassword`).

Errors on the inbox screen: `CODE_INVALID` (shows `attempts_left`), `CODE_EXPIRED` (ask for a new code),
`TOO_MANY_ATTEMPTS` (ask for a new code), `EMAIL_SEND_FAILED` (try "Resend").

## Files

| File | What goes in it |
|---|---|
| `router.py` | HTTP endpoints only |
| `schemas.py` | Pydantic request/response models |
| `service.py` | Business logic (codes, hashing, Firebase calls via `api/core/firebase_users.py`) |
| `repository.py` | All SQL for `users`, `email_codes`, `password_reset_tokens` |

Tests: `tests/api/test_auth.py` (Firebase and email are faked).
