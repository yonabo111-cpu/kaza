# Security Model

Kaza is a small self-hosted app that holds real household data (expenses,
balances, private ledgers), so it applies defense-in-depth appropriate to its
size. This document describes the layers, in request order.

## Transport & headers

Every response carries (see `kaza/security.py`):

| Header | Value | Purpose |
|---|---|---|
| `Content-Security-Policy` | `default-src 'self'` + explicit allowances | Blocks foreign scripts/objects/framing; only Google Fonts is allowed externally |
| `X-Frame-Options` / `frame-ancestors` | `DENY` / `'none'` | Clickjacking |
| `X-Content-Type-Options` | `nosniff` | MIME confusion |
| `Referrer-Policy` | `same-origin` | No URL leakage to other sites |
| `Permissions-Policy` | camera/mic/geolocation/payment off | Least capability |
| `Strict-Transport-Security` | 1 year (production only) | Forces HTTPS once deployed behind TLS |

> The CSP currently includes `'unsafe-inline'` because the single-file frontend
> uses inline style/script. The planned frontend split moves code to external
> files, after which `'unsafe-inline'` will be dropped for scripts.

## Sessions & authentication

- Passwords are stored as salted PBKDF2 hashes (Werkzeug); never in plain text.
- Session cookies: signed, `HttpOnly`, `SameSite=Lax`, and `Secure` in
  production. Sessions are cleared and re-issued on every login (no fixation).
- Login is rate-limited twice: per email (5 failures → 60s lockout, and the
  lockout answers even a *correct* password) and per IP (sliding window).
  Registration is rate-limited per IP.

## CSRF (three independent layers)

State-changing API calls (`POST/PATCH/PUT/DELETE /api/*`) must pass all of:

1. **Origin check** — if the browser sends an `Origin`, it must match our host.
2. **`Sec-Fetch-Site` check** — requests labelled `cross-site` are rejected.
3. **JSON-only POST** — HTML forms cannot send `application/json`, and a
   cross-origin script cannot either without a CORS preflight this app never
   grants.

Combined with `SameSite=Lax` cookies (browsers omit the session cookie on
cross-site POSTs to begin with), classic CSRF has no path through.

## Injection & input hygiene

- **SQL**: every query in `kaza/models/` is parameterised; user input is never
  interpolated into SQL strings.
- **XSS**: the API stores and returns user text verbatim (it is a data layer);
  the frontend escapes all user content at render time via a single `esc()`
  helper. CSP is the backstop.
- **Input validation**: every field is validated server-side — length caps,
  strict date/month/email formats, numeric ranges (amounts capped at 1M), and
  membership checks. Free text passes `clean_text()` which strips control
  characters.

## Tenant isolation

Every query is scoped by `household_id` (or `user_id` for private ledgers) at
the SQL level — a row belonging to another household behaves exactly like a row
that does not exist (404), on every endpoint. Private expenses are additionally
scoped to their owning user only, including in backups.

## Verification

`tests/security_test.py` asserts all of the above end-to-end against a running
server: headers, cookie flags, each CSRF layer, a 401 sweep of protected
endpoints, cross-household 404s, login lockout, SQLi/XSS payload handling, and
control-character stripping. It runs in CI on every push.

## Reporting

Found something? Please open a GitHub issue (or contact the maintainer
privately for sensitive reports).
