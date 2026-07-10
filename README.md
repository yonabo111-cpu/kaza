# 🏠 Home Manager

A full-stack web app for roommates sharing an apartment: track shared expenses with
automatic settlement ("who owes whom"), monthly budgets, a shared shopping list,
recurring bills, chore rotation — and a **private ledger** each member sees only
themselves.

Built with Flask + SQLite on the backend and a single-file vanilla-JS frontend.
The UI is in **Hebrew (RTL)**, designed mobile-first with a bottom navigation bar,
dark-mode support, and a friendly, modern look.

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
- **Backup** — one-click JSON export (includes your own private expenses only).

## Architecture

| Layer    | Tech                                   | File                |
|----------|----------------------------------------|---------------------|
| Backend  | Python / Flask, REST API               | `app.py`            |
| Database | SQLite (auto-created, WAL mode)        | `data/app.db`       |
| Frontend | Single-file HTML/CSS/JS, no framework  | `static/index.html` |

Design decisions worth noting:

- **Materialized shares.** Each expense stores a per-member share row
  (`expense_shares`) computed at insert time, so historical splits stay correct
  when roommates join later. A member's balance = everything they paid minus the
  sum of their shares, adjusted by recorded settlements.
- **Privacy by construction.** Private expenses live in their own table and every
  query filters by the session user's id — they cannot leak into shared lists,
  totals, budgets or exports of other members.
- **Security basics** — password hashing (Werkzeug), signed session cookies
  (HttpOnly, SameSite=Lax), login rate-limiting, Origin check on state-changing
  requests, per-household data isolation enforced in every query.

## Quick start

```bash
pip install -r requirements.txt
python app.py            # http://localhost:5050
```

The server listens on `0.0.0.0`, so roommates on the same Wi-Fi can use
`http://<your-ip>:5050`.

### Configuration (environment variables)

| Variable            | Default           | Purpose                                  |
|---------------------|-------------------|------------------------------------------|
| `PORT`              | `5050`            | HTTP port                                 |
| `DATA_DIR`          | `./data`          | Where the SQLite DB and secret key live   |
| `SECRET_KEY`        | auto-generated    | Session signing key (persisted to a file) |
| `ANTHROPIC_API_KEY` | unset             | Optional — enables AI recipe lookup for dishes not in the built-in cookbook ([get a key](https://console.anthropic.com)) |
| `CLAUDE_MODEL`      | `claude-opus-4-8` | Model for recipe lookup (e.g. `claude-haiku-4-5` for cheaper/faster responses) |

## Tests

An end-to-end API test suite (113 checks) lives in [`tests/`](tests): it simulates
two roommates through every flow — registration, invite codes, all split types,
balances and settlement, bills, shopping, chores, cross-household isolation, the
privacy guarantees of the personal ledger, recipe → shopping-list resolution, and
bulletin-board permissions.

```bash
# start the server against a throwaway database first:
DATA_DIR=/tmp/home-test python app.py
# then, in another terminal:
pip install requests
python tests/api_test.py       # 52 checks
python tests/personal_test.py  # 26 checks
python tests/recipe_test.py    # 18 checks
python tests/bulletin_test.py  # 17 checks
```

> Each suite registers `testa@example.com`, so run them against a **fresh**
> `DATA_DIR` one at a time (wipe the DB between suites), not all three against
> one database.

> The tests register their own users on the running server — point `DATA_DIR`
> at a disposable location, not your real database.

## Deploying (free)

**PythonAnywhere** (recommended first deploy — persistent disk, so SQLite survives):

1. Sign up at <https://www.pythonanywhere.com> (free *Beginner* plan).
2. Upload this folder to `/home/<you>/home-app` (zip + `unzip` in a Bash console).
3. Console: `pip install --user flask`
4. **Web → Add a new web app → Manual configuration** (Python 3.10+).
5. Edit the WSGI configuration file to:

   ```python
   import sys
   sys.path.insert(0, "/home/<you>/home-app")
   from app import app as application
   ```

6. **Reload** — the app is live at `https://<you>.pythonanywhere.com`. Share the
   link and your invite code with your roommates.

**Render / Railway**: a `Procfile` (gunicorn) is included; note that on free tiers
the filesystem is ephemeral — attach a persistent disk or migrate to Postgres so
data survives redeploys.

## Roadmap

- Password reset via email, email verification
- In-app notifications (bill due soon, budget exceeded, your chore turn)
- Monthly report export
- Postgres option for ephemeral-disk hosts
