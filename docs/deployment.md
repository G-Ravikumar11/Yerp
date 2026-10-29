# Deploying to Railway

The app is one FastAPI service serving its own frontend, with no separate worker.

Railway builds it in two steps (see `nixpacks.toml` at the repository root):

1. Python: installs `backend/requirements.txt`.
2. Node: compiles the React app in `frontend/` into `frontend/dist/` (`npm ci && npm run build`).

`frontend/dist/` is never committed - push source only. If the frontend fails to type-check or build, the
deploy fails and Railway keeps the previous version running.

The React app holds both the company's public front page, served at `/`, and the ERP under `/next/`
(sign-in, onboarding, the partner portal, the platform console, careers and the application form, meetings,
and every ERP screen). The old `*.html` addresses (`/login.html`, `/portal.html`, `/app.html`, ...) are
forwarded to their React pages by `backend/app/core/static.py`, so links already sent in emails keep
working. `backend/app/static/` holds the two files phones that installed the old app still ask for.

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
| `ADMIN_PASSWORD`, `SUPERADMIN_EMAILS`, `SUPERADMIN_PASSWORD` | `ADMIN_PASSWORD` guards `/admin`, which has direct table access; unset or `admin` keeps the panel shut. `SUPERADMIN_EMAILS` names who may enter the platform console (nobody is let in by default); `SUPERADMIN_PASSWORD` sets their password when it is first given or changed - a password changed in the console afterwards is kept. |

Everything else in `backend/.env.example` is optional — Google sign-in, Gmail
sending, Groq for the AI features, and the payment gateways. Each one is
inactive until configured and says so plainly rather than failing.

### Sign in with Google

The "Continue with Google" button appears on `/next/login` (the Master, team
members, staff) and `/next/portal` (partners) once two variables are set. It
signs in only addresses that already have a login here - it never creates one.

1. Google Cloud Console → APIs & Services → OAuth consent screen: External,
   app name, support email; add the scopes `openid`, `email`, `profile`
   (and `gmail.send` if mail should go out through Gmail). Publish the app
   (or add each person as a test user while it is in testing).
2. Credentials → Create credentials → OAuth client ID → Web application.
   Authorised redirect URIs, both:
   `https://<your-app>/api/auth/google/callback` (sign-in) and
   `https://<your-app>/api/auth/callback` (Gmail sending).
3. Railway → Variables: `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` from
   that client. Redeploy.

The platform console's Google sign-in admits only addresses listed in
`SUPERADMIN_EMAILS`.

## Many users (about a thousand)

Measured with 100 simulated users clicking about four times faster than people do (roughly 400 people at once), one
server process serves about 100 requests a second. What decides speed is how far the database is from the server:
with it 0.3 s away, even 20 users waited ten seconds or more for a page, because every request makes several round
trips and only about 15 database connections are open at a time.

1. **Same region, near the users.** The server and the database in one region, Mumbai if the users are in India.
2. **A database that does not sleep**, with a pooler in front (on Neon: a paid plan, autosuspend off, the `-pooler` address).
3. **`API_FLOOD_PER_MINUTE`** is 6000 a minute per address, so a site office of a few dozen people sharing one connection is
   not stopped. Lower it only if a script is hammering the server.
4. **Three more limits keep a few people from slowing everyone** (each is a variable; 0 turns it off):
   `LOGIN_PER_MINUTE` (60) sign-ins a minute from one address, so a site office that signs in together is not turned away;
   `HEAVY_PER_MINUTE` (30) exports, PDFs and printed documents a minute for each signed-in person; `AI_PER_MINUTE` (20)
   AI requests a minute for each signed-in person. Wrong passwords are limited separately and harder (a CAPTCHA after
   three, a lock on that address after ten).
5. **More than one process (`WEB_CONCURRENCY=3` or `4`) needs two things first.** Each process then holds its own copy
   of the sign-in lock counts, the CAPTCHA tokens already used, the request limits and `core/cache.py`'s heavy-page cache,
   so the limits become that many times looser and the approvals inbox and project profit page can be 30 to 60 seconds
   out of date on another process. Move those into the database or Redis first. Then raise `DB_POOL_SIZE` and
   `DB_MAX_OVERFLOW` so processes x (pool + overflow) stays below what the database allows.
6. **Uploaded files are stored in the database** (`files.data`). With many users, move them to object storage (S3 or
   Cloudflare R2): the database grows quickly, and every download holds a connection.

## How it starts

`railway.json` sets the start command and points the healthcheck at
`/api/health`, which reports both process and database health:

```
python -m uvicorn main:app --host 0.0.0.0 --port $PORT --app-dir backend
```

`requirements.txt` at the repository root is what makes Nixpacks recognise
this as a Python app; it installs from `backend/requirements.txt`.
`.python-version` pins Python 3.12. `nixpacks.toml` adds Node 24 for the frontend build, from a newer Nix
snapshot than the one Nixpacks uses for Python: that one only has Node 22.10, and Vite needs 22.12 or newer.

## The database

Tables are created on first boot and missing columns are added on every boot,
so a fresh deploy needs no migration step and an existing one upgrades itself.

Nothing is seeded. A newly deployed instance has no clients, no employees and
no data of any kind — the first person to register creates the first tenancy.
`backend/scripts/seed_demo.py` exists for local demonstration only and is never run
automatically; do not run it against production.

## Checking a deploy

```bash
curl https://your-app.up.railway.app/api/health
```

`{"status":"ok","database":"ok"}` means the process is up and the database
answered. Anything else, read the deploy logs: both start-up refusals above
print exactly what is missing and where to set it.

## After a deploy: how devices get the new version

Nobody has to clear anything or press reload:

- Pages are always asked of the server first (the offline copy is used only with no signal), and the script files
  are named by their contents, so a page opened after a deploy is the new build.
- Every answer from `/api` carries `X-App-Build`, the stamp of the build being served (`frontend/dist/build.json`,
  written by `npm run build`). An app left open that sees a newer stamp loads the new build at the next change of
  screen - never in the middle of a form - and only once.
- Data kept on the device by an older build is thrown away by the newer one.

If a device still shows something wrong:

- **One device:** open `/next/reset`. It clears the saved copy of the app, its service worker, the kept data and the
  browser's own cache for the site, then goes back into the app. The person stays signed in, and saves made offline
  that are not yet sent are kept. The same link is offered on the "This page hit a problem" screen.
- **Every device:** set the Railway variable `CLIENT_RESET` to any new value (today's date will do). Each device does
  the same reset once, the next time it talks to the server. Change the value again to repeat it; leave it alone
  otherwise.
