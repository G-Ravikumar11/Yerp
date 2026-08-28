# Deploying to Railway

The app is one FastAPI service serving its own frontend. There is no build
step for the UI and no separate worker.

## What Railway needs from you

Create the service from the repo, add a **Postgres** database to the project,
then set these in the service's **Variables** tab.

### Required — the app refuses to start without them

| Variable | Where it comes from |
| --- | --- |
| `DATABASE_URL` | Railway's Postgres plugin exposes this. Reference it as `${{Postgres.DATABASE_URL}}` so it follows the database. |
| `SECRET_KEY` | `python -c "import secrets; print(secrets.token_hex(32))"` |

Both are set in the service's **Variables** tab, not in `.env` - `.env` is
for a local machine and never reaches the container. A deploy that crashes
on either of these is the guard working; set the variable and Railway
redeploys on save.

The service and the database should sit in the same region. Start-up runs
the whole migration, which is a few dozen round trips: across an ocean that
is slow enough to matter, and the healthcheck allows 300 seconds for it.

Both refusals are deliberate. Without `DATABASE_URL` the app would fall back to
a SQLite file on the container's own disk: it would work perfectly and lose
every row on each redeploy. Without `SECRET_KEY` it would generate one per
boot, signing every user out each time you ship. Neither failure announces
itself, so the app stops instead.

### Strongly recommended

| Variable | Why |
| --- | --- |
| `APP_BASE_URL` | Password-reset and invoice links are built from it. Set it to the public URL. |
| `COOKIE_SECURE=true` | Sessions over HTTPS only. |
| `CORS_ORIGINS` | The public URL. |
| `ADMIN_PASSWORD`, `SUPERADMIN_EMAILS`, `SUPERADMIN_PASSWORD` | `ADMIN_PASSWORD` guards `/admin`, which has direct table access. It defaults to `admin`. |

Everything else in `backend/.env.example` is optional — Google sign-in, Gmail
sending, Groq for the AI features, and the payment gateways. Each one is
inactive until configured and says so plainly rather than failing.

## How it starts

`railway.json` sets the start command and points the healthcheck at
`/api/health`, which reports both process and database health:

```
python -m uvicorn main:app --host 0.0.0.0 --port $PORT --app-dir backend
```

`requirements.txt` at the repository root is what makes Nixpacks recognise
this as a Python app; it installs from `backend/requirements.txt`.
`.python-version` and `runtime.txt` pin Python 3.12.

## The database

Tables are created on first boot and missing columns are added on every boot,
so a fresh deploy needs no migration step and an existing one upgrades itself.

Nothing is seeded. A newly deployed instance has no clients, no employees and
no data of any kind — the first person to register creates the first tenancy.
`backend/seed_demo.py` exists for local demonstration only and is never run
automatically; do not run it against production.

## Checking a deploy

```bash
curl https://your-app.up.railway.app/api/health
```

`{"status":"ok","database":"ok"}` means the process is up and the database
answered. Anything else, read the deploy logs: both start-up refusals above
print exactly what is missing and where to set it.
