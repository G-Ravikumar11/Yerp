# Y ERP — new interface (React)

The Y ERP front end. It talks to the FastAPI backend and is served by it at
**`/next/`**. It replaced the earlier plain-JavaScript app, which has been
removed; its old addresses forward here.

Stack: Vite, React 19, TypeScript (strict), Tailwind v4, Radix primitives,
TanStack Query, Zustand, Framer Motion, Recharts, and a `vite-plugin-pwa`
service worker.

## Commands

Run these from `frontend-react/`.

| Command | What it does |
| --- | --- |
| `npm install` | Install dependencies. |
| `npm run dev` | Dev server with hot reload. `/api` is proxied to the backend on port 8931. |
| `npm test` | Unit and component tests (vitest, jsdom). |
| `npm run lint` | oxlint. |
| `npm run build` | Type-check, then build into `../frontend-next/`. |
| `npm run e2e` | Every browser suite in `e2e/`, in a real Edge. See below. |

## Shipping a change

The server does not build the UI. It serves `frontend-next/`, which is built
output **committed to the repository**. After any change under `frontend-react/`:

```
npm run build
git add frontend-react frontend-next
```

Commit both together, or the site keeps serving the old bundle. Only the app
shell is cached by the service worker, so a new build reaches devices as a
"new version is ready — Reload" prompt rather than a surprise refresh.

## What is here

```
src/
  api/          one file per backend area (orders, mb, subbills, items, vendors, ...)
  components/
    ui/         design system: button, input, modal, select, tabs, toast, ...
    grid/       the Excel-style data grid (see below)
    data/       DataTable and its filter bar
    layout/     shell, sidebar, top bar, sync indicator
  features/     one folder per screen family (orders, measurement, subbills, ...)
  lib/          api client, session, query cache + persistence, formatting
  stores/       Zustand: ui, toast, offline queue
  pages/        Command Center, design-system page, grid playground
  routes.tsx    which paths are ported; the rest link to the current app
e2e/            puppeteer suites (one file per area) and run-all.mjs
```

### The data grid

`src/components/grid/` is a controlled `DataGrid<T>`: type to replace, F2 or
double-click to edit, arrows / Tab / Enter to move, Shift for ranges, Ctrl+C / X / V
as tab-separated text (paste from Excel works), Ctrl+Z / Y for undo and redo, fill
handle, arithmetic in number cells (`=12*3.5`), virtualised rows, per-cell
validation, and sums for the selection in the status bar. Its logic is plain
functions in `values.ts` and `model.ts`, covered by unit tests.

Open **`/next/design/grid`** to try it (the design system itself is at `/next/design`).

### Working with no signal

- Reads are kept on the device (IndexedDB) and shown first. Signing out clears them.
- A change made offline joins a queue (`stores/offline.ts`) and is sent in order
  when the connection returns. Only a true network failure queues; a refusal from
  the server is shown to the person, never queued.
- The top bar shows Offline / Syncing / Unsent so it is never a guess.

## Browser tests

The suites drive a real browser against a real backend, so they need a running
server with the demo data.

1. Start the backend on a **copy** of the demo database (the tests create and
   change records), for example on port 8940.
2. Build once (`npm run build`) so `/next/` exists.
3. Run:

```
BASE_URL=http://127.0.0.1:8940 npm run e2e
```

`BASE_URL` defaults to `http://127.0.0.1:8940`. The browser is Microsoft Edge;
set `BROWSER` to the path of Edge or Chrome if it is not in the usual place. The tests sign in as the demo
owner from `backend/seed_demo.py`.

## Not ported yet

Screens still on the current app show a placeholder with a link to it: client-side
work orders and measurement, supplier bills and goods receipt matching, stores,
people and the rest. `src/routes.tsx` is the list; moving a screen is adding it
there.
