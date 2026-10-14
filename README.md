# Campus Share

A college resource-sharing platform (Flask + SQLite + Jinja).

## Setup

```bash
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000 — you'll land on the login page. Register an account to get started.

## What's new in this version

- **Left sidebar navigation** replacing the old top navbar (logged-in views only; login/register keep
  a lightweight top bar). All existing routes (Browse, Upload, My Uploads, Bookmarks, Requests,
  Notifications, Settings, Admin) are unchanged — only their entry point moved into the sidebar.
- **Mobile responsive layout** — the sidebar collapses into a hamburger-triggered slide-out drawer
  under 900px width; filters, forms, resource grids, and action buttons stack vertically on phones.
- **Doubt Box** (`/doubts`) — students can post academic doubts, browse/search/filter by subject or
  answered-status, answer each other, and the asker can mark one answer as "Accepted".
- **Senior Connect** (`/mentors`) — 3rd/4th year students only can create a mentor profile listing
  subjects + bio, toggle availability on/off, and other students can browse/filter mentors by
  subject, year, branch. Eligibility is enforced server-side (`app.py` → `MENTOR_ELIGIBLE_YEARS`),
  not just hidden in the UI — a non-eligible student's direct POST to `/mentors/profile` is rejected
  before any database write.

No existing model, route, or template was removed. New tables added: `doubt`, `doubt_answer`, `mentor`.

## Notes carried over from the previous version

- The database schema changed (new tables above). As with the last update, delete any old
  `campus_share.db` before running — a fresh one is created automatically on first run.
- To make a user an admin, run once from the project folder:

  ```bash
  python3 -c "
  from app import app, db, User
  with app.app_context():
      u = User.query.filter_by(email='YOUR_EMAIL_HERE').first()
      u.role = 'admin'
      db.session.commit()
      print('promoted', u.name)
  "
  ```

- Low-quality auto-flagging threshold (`LOW_QUALITY_MIN_RATINGS`, `LOW_QUALITY_THRESHOLD` in `app.py`).
- Duplicate detection hashes file contents (SHA-256), not filenames.
