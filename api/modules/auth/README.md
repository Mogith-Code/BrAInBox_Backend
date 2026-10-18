# `auth` module

| | |
|---|---|
| **Owner** | Mogith |
| **Purpose** | Register a Firebase user in our database and manage the logged-in account. |
| **Tables** | `users` |
| **Jira epic** | BRN-E01 Auth & Accounts *(placeholder key – replace with the real one)* |
| **Git branch** | `feature/auth` (tasks: `feature/auth/BRN-xx-short-name`) |

## Planned endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/auth/register` | Create the users row for a new Firebase account (uses FirebaseClaimsDep, not CurrentUserDep) |
| GET | `/api/v1/auth/me` | Current user |
| PATCH | `/api/v1/auth/me` | Update display name etc. |
| DELETE | `/api/v1/auth/me` | Delete / anonymise the account |

Placeholder right now: `GET /api/v1/auth/status` → `{"module": "auth", "status": "todo"}` (needs login).

## Files

| File | What goes in it |
|---|---|
| `router.py` | HTTP endpoints only (validate, check role, call service) |
| `schemas.py` | Pydantic request/response models |
| `service.py` | Business logic |
| `repository.py` | All SQL queries for this module |

Models live in `shared/db/models/`. Call other modules through their `service.py`, never their `repository.py`.
Tests: `tests/api/test_auth.py`.
