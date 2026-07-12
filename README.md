<img src="static/logo.svg" alt="Kaza" width="88" align="right">

# Kaza (קאזה)

[![CI](https://github.com/yonabo111-cpu/kaza/actions/workflows/ci.yml/badge.svg)](https://github.com/yonabo111-cpu/kaza/actions/workflows/ci.yml)

**Kaza** — like *casa*, but with roommates.

A full-stack web app for roommates sharing an apartment: track shared expenses with
automatic settlement ("who owes whom"), monthly budgets, a shared shopping list,
recipe → shopping-list resolution, recurring bills, chore rotation, a bulletin
board, in-app notifications — and a **private ledger** each member sees only
themselves.

Built with **Flask** (a modular application-factory backend) and **SQLite /
PostgreSQL**, served to a single-file vanilla-JS frontend. The UI is in **Hebrew
(RTL)**, designed mobile-first with a bottom navigation bar, dark-mode support,
and a friendly, modern look.

## Features

- **Accounts & households** — register with email + password (hashed), create an
  apartment or join one with a 6-character invite code. Any number of roommates.
- **Shared expenses** — every expense records who paid and how it splits:
  *equal*, *personal* (no split), or *custom* per-member shares.
- **Settlement** — running net balance per member, plus a suggested minimal set of
  transfers to settle up (greedy largest-debtor → largest-creditor matching).
- **Budgets** — monthly cap per category with progress meters and overspend alerts.
- **Shopping list** — shared, with urgent flags; checked-off items can be converted
  into a shared expense in one click.
- **Recipe → shopping list 🍝** — type "I feel like pasta bolognese" (in Hebrew,
  free-form) and get the ingredient list to review and add in one click. ~30
  common Israeli home dishes are built in and work offline; any other dish is
  resolved by Claude when an `ANTHROPIC_API_KEY` is configured (results are
  cached in SQLite so each dish is paid for once). Already-listed items are
  skipped, and added items are tagged with the dish name.
- **Bulletin board 📌** — sticky notes on the dashboard for quick updates between
  roommates ("technician coming tomorrow", "new Wi-Fi code"). Notes can be pinned
  to the top; the board is shared, so any roommate can take a note down — like a
  real note on the fridge. Household isolation is enforced server-side.
- **Recurring bills** — rent, utilities, etc. with due days; marking a bill paid
  auto-creates an equally-split expense. Overdue bills are flagged.
- **Chores** — rotating assignments; "done" passes the turn to the next roommate.
- **Private ledger 🔒** — per-member expenses stored in a separate table and
  returned **only to their owner**, never to other members, on any endpoint.
  Includes a personal monthly budget measured against *your true monthly spend*
  (your share of shared expenses + your private ones).
- **Dashboard** — monthly totals vs. last month, budget meters, 6-month trend
  chart, upcoming bills and urgent shopping items.
- **In-app notifications 🔔** — a bell with an unread badge: overdue / upcoming
  bills, budget overruns (household and personal), open debts, your chore turn
  and urgent shopping. Notifications are *derived* from current state on every
  request — no extra table, no scheduler — so they appear when a condition holds
  and disappear the moment it's resolved. Clicking one deep-links to the relevant
  tab; read-state is kept client-side per user.
- **Backup** — one-click JSON export (includes your own private expenses only).

## Architecture

The backend is a layered Flask package built with the application-factory
pattern; dependencies flow one way, `routes → services → models → db`:

```
kaza/
├── __init__.py       # create_app() application factory
├── config.py         # env-based config (development / production / testing)
├── db.py             # connection factory (SQLite / PostgreSQL), schema, indexes
├── security.py       # CSRF/origin guard, security headers, login rate limiter
├── auth.py           # password hashing, sessions, access decorators
├── utils.py          # request helpers & validators
├── models/           # data-access repositories (parameterised SQL only)
├── services/         # business logic (splits, balances, notifications, state)
└── routes/           # thin blueprints, one per domain
static/index.html     # single-file vanilla-JS frontend
app.py / wsgi.py      # dev runner / WSGI entry point
```

| Layer    | Tech                                      |
|----------|-------------------------------------------|
| Backend  | Python 3.10+ / Flask, blueprint REST API  |
| Database | SQLite (default) or PostgreSQL via `DATABASE_URL` |
| Frontend | Single-file HTML/CSS/JS, no framework      |
| Tooling  | ruff (lint + format), GitHub Actions CI, Docker |

Design decisions worth noting:

- **Materialized shares.** Each expense stores a per-member share row
  (`expense_shares`) computed at insert time, so historical splits stay correct
  when roommates join later. A member's balance = everything they paid minus the
  sum of their shares, adjusted by recorded settlements.
- **Privacy by construction.** Private expenses live in their own table and every
  query filters by the session user's id — they cannot leak into shared lists,
  totals, budgets or exports of other members.
- **Defense in depth** — password hashing (Werkzeug), signed session cookies
  (HttpOnly, SameSite=Lax, Secure in production), three independent CSRF layers
  (Origin check, `Sec-Fetch-Site`, JSON-only POST), a Content-Security-Policy
  plus a full set of security headers (HSTS in production), login rate-limiting
  per email *and* per IP, control-character input sanitisation, and
  per-household data isolation enforced in every query. The full model is
  documented in [SECURITY.md](SECURITY.md) and asserted end-to-end by a
  dedicated test suite.
- **Health & operations** — a `/healthz` endpoint (used by the Docker
  healthcheck), structured logging, and JSON error handlers for API routes.

## Quick start

```bash
pip install -r requirements.txt
python app.py            # http://localhost:5050
```

The server listens on `0.0.0.0`, so roommates on the same Wi-Fi can use
`http://<your-ip>:5050`.

### Configuration (environment variables)

All configuration is via environment variables — see [`.env.example`](.env.example).

| Variable            | Default           | Purpose                                  |
|---------------------|-------------------|------------------------------------------|
| `KAZA_ENV`          | `development`     | Config profile: `development` / `production` / `testing` |
| `PORT`              | `5050`            | HTTP port                                 |
| `DATA_DIR`          | `./data`          | Where the SQLite DB and secret key live   |
| `SECRET_KEY`        | auto-generated    | Session signing key (set explicitly in production) |
| `DATABASE_URL`      | unset (SQLite)    | PostgreSQL connection URL to switch drivers |
| `ANTHROPIC_API_KEY` | unset             | Optional — enables AI recipe lookup for dishes not in the built-in cookbook ([get a key](https://console.anthropic.com)) |
| `CLAUDE_MODEL`      | `claude-opus-4-8` | Model for recipe lookup (e.g. `claude-haiku-4-5` for cheaper/faster responses) |
| `LOG_LEVEL`         | `INFO`            | Logging verbosity                         |

## Tests

An end-to-end API test suite (158 checks across 6 suites) lives in
[`tests/`](tests): it simulates two roommates through every flow —
registration, invite codes, all split types, balances and settlement, bills,
shopping, chores, cross-household isolation, the privacy guarantees of the
personal ledger, recipe → shopping-list resolution, bulletin-board permissions,
notification derivation, and a dedicated security suite (headers, every CSRF
layer, auth walls, lockout, SQLi/XSS handling).

Run everything with one command — it boots the app on a throwaway database for
each suite and tears it down afterwards (this is exactly what CI runs):

```bash
pip install -r requirements-dev.txt
python tests/run_all.py
```

Each suite can also be run individually against a **fresh** `DATA_DIR` (they
register their own test users, so never point them at your real database):

```bash
DATA_DIR=/tmp/kaza-test python app.py          # in one terminal
API_BASE=http://localhost:5050/api python tests/api_test.py   # in another
```

### Linting & formatting

```bash
ruff check .          # lint
ruff format --check . # formatting
```

## Deploying

### Docker (any container host)

```bash
docker compose up --build      # → http://localhost:5050
```

The image serves the app with gunicorn and persists the SQLite database in a
named volume. For a real deployment set `KAZA_ENV=production` (behind HTTPS) and
a `SECRET_KEY`; see [`.env.example`](.env.example).

### PythonAnywhere (free, persistent disk — SQLite survives)

1. Sign up at <https://www.pythonanywhere.com> (free *Beginner* plan).
2. Upload this folder to `/home/<you>/home-app` (zip + `unzip` in a Bash console).
3. Console: `pip install --user flask`
4. **Web → Add a new web app → Manual configuration** (Python 3.10+).
5. Edit the WSGI configuration file to:

   ```python
   import sys
   sys.path.insert(0, "/home/<you>/home-app")
   from wsgi import app as application
   ```

6. **Reload** — the app is live at `https://<you>.pythonanywhere.com`. Share the
   link and your invite code with your roommates.

### Render / Railway / Fly

A `Procfile` (`gunicorn wsgi:app`) and a `Dockerfile` are included. On free tiers
the filesystem is ephemeral — attach a persistent disk or point `DATABASE_URL`
at a managed PostgreSQL instance so data survives redeploys.

## Roadmap

- AI insights: monthly spend analysis, savings tips, shared-buy suggestions
- Content Security Policy and CSRF tokens
- Frontend split into modules + accessibility pass
- Password reset via email, email verification
- Monthly report export
