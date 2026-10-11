# Y ERP

An ERP for a civil contracting business. Built around the way a site actually
runs — an order is placed, material arrives at the gate, work is measured in
the book, bills follow the measurements, and somebody has to know at the end of
it whether the job made money.

Single company, single owner, staff underneath with only the rights the owner
gives them.

## Where everything is

```
backend/            the server: Python, FastAPI, SQLAlchemy        -> "How the backend is arranged" below
  app/              all the server code
  tests/            pytest suite
  scripts/          run_demo.py, seed_demo.py
  requirements.txt  what the server needs; requirements-dev.txt adds the test tools
frontend/           the web app: React, TypeScript, Vite            -> frontend/README.md
  src/              all the screens and the company website
  public/           icons and the website's photos, copied into the build as-is
  e2e/              browser tests
docs/               deployment.md (Railway)
nixpacks.toml       how Railway builds it: Python, then the React app into frontend/dist
railway.json        how Railway starts it and checks it is healthy
requirements.txt    one line pointing at backend/requirements.txt (Railway needs a file here to spot Python)
```

`frontend/dist/` is the compiled web app. It is made by `npm run build`, never committed, and served
by the backend at `/next/` (the website at `/`).

## The chain it follows

Every screen below is one link, and each one feeds the next. Nothing is typed
twice.

```
 Item master ─┬─> Work order ──> Measurement book ──> RA bill ──> Payment
              │        │                │                 │
              │        │                └──> Variation    └──> Retention held
              │        │
              │        └──> BOM (what it should take)
              │                        │
              └─> Purchase order ──> Goods receipt ──> Stock ──> Issue to site
                            │                                        │
                            └──> Three-way match          Material used vs costed
                                                                     │
 Site diary (labour + plant) ────────────────────────────────> Project profit
```

## What each screen is for

**Item master** — every code the business is allowed to reference. RM is stock
you reuse; FG is one deliverable on one contract, so a duplicate FG code is an
error rather than a merge. Imports your existing spreadsheets.

**Work order** — what has been sold, line by line, with the BOM of raw material
underneath it. Import from a spreadsheet or build it on screen. A statement
page reconciles ordered → varied → measured → billed → certified → paid.

**Measurement book** — what has actually been built, written the way a book
is written: particulars, No × L × B × D, deductions for openings, the total
being what the lines come to. Entries accumulate; a correction is a deduction,
never an edit, because a book that can be rubbed out is not a record. The
app is the book — there is no sheet beside it.

**Every document has a page.** The client's RA bill (abstract of cost,
deductions in the order they are made, the figure in words, the certification
block), the subcontractor's bill, the purchase order and the goods receipt
each open as the sheet of paper they become and print from the browser. The
workbook download still exists for whoever asks for one; it is no longer the
only way to see a bill.

**Every table is a sheet.** Click a heading to sort, type to filter, tick
Totals. The three things a list used to be downloaded for.

**Registers** — TDS by quarter in both directions (what we withheld under
194C and must deposit and file; what our clients withheld and we must match
to the 26AS), bank guarantees and when each lapses, mobilisation advances and
what has come back.

**No spreadsheets.** That is the point of the app. Grids take a pasted block
and walk with Enter, Tab and the arrows, so a two-hundred-line schedule is
typed here. The import paths exist to bring in the sheets the business already
had, once, and are folded away. Downloads are outputs, like the print button,
and are labelled as such.

**Variations** — when the site builds past the order, the book already knows.
The variation drafts itself from that flag: lines, quantities, rates and money.
Approving it raises the order so the extra work becomes billable.

**RA bills** — each bill claims the difference between what has been measured
and what earlier bills already claimed. Retention off the work, tax on the
remainder, TDS off the whole claim. Draft → submitted → certified → paid, and
the person who measured cannot be the one who certifies.

**Subcontract work orders** — work issued out to a gang, as the letter that
gets signed. A schedule with heading rows and a tolerance on each item (the
book cannot be measured past order-plus-tolerance without an amendment), the
billing terms laid out head by head (CGST/SGST or IGST by the contractor's
state against the site's, mobilisation advance, retention, TDS, labour welfare
cess), payment terms written into a clause, a copy-as-new, the last rate paid
for a code offered beside the cell, and every edit to the head written into the
history. Their measurement book and RA bills follow the client-side shape,
with the retention held by us.

**Subcontractor register** — every gang with its vendor code (IV0001 onwards)
and its Sub Contractor Registration Form, box for box: personal details, PAN,
GST, Aadhaar, bank, the documents collected and the declaration. A gang
registered by somebody on site waits in Approvals, and no order is approved for
a gang whose form has not been signed off. The form prints and downloads in the
office's layout; the old vendor-codes workbook (a form per sheet) imports once.

**The gang's bill is the three sheets it was always signed on** — the Top
Sheet (certificate of payment), AB-1 (abstract: up to previous, this bill, up to
this bill) and MB-1 (the book: No's × NoM × Length × Width × Height, headings,
deductions, a block measured once and counted for every block built). GST is
charged on the gross; retention and TDS come off the value of the work; every
figure after the work is whole rupees. The MB sheet imports from Excel, or its
lines paste straight into the book. Certifying climbs the hierarchy — prepared
by the QS, certified by the Head QS, approved by the site incharge — and the
gang signs "Accepted for Sub Contractor" from the partner portal.

**Purchase orders and goods receipt** — what was ordered against what arrived.
Received and accepted are separate numbers, so material that turns up broken is
recorded, returned and credited rather than quietly absorbed.

**Three-way match** — order against delivery against bill. Anything that
disagrees is money.

**Stock** — every movement is a signed row and the balance is their sum.
Receipts come from posting a goods receipt, never by hand. Issues are priced at
what the store actually paid, using a weighted average.

**Material used vs costed** — the BOM against the issues. The gap is waste,
theft, or a BOM nobody updated after a variation.

**Site diary** — the daily record: who turned up by trade and by gang, what
plant stood idle, what the weather did, what got built and what stopped it.
One diary per site per day, and a signed-off day cannot be rewritten. It is
also where the labour cost comes from.

**Project profit** — what each job earned against what it truly cost, with
material, labour and plant included. Worst margin first.

## Running it

The backend:

```bash
cd backend
pip install -r requirements-dev.txt
python -m uvicorn main:app --reload
```

The API is then on http://localhost:8000. With no `DATABASE_URL` set it uses a local
SQLite file; set one to point at Postgres. Copy `backend/.env.example` to `backend/.env` for the optional keys.

The web app, while working on it (hot reload, `/api` proxied to the backend):

```bash
cd frontend
npm install
npm run dev
```

To have the backend serve the app itself, as it does in production, run `npm run build` in `frontend/` once.

A seeded demo with sample data:

```bash
python backend/scripts/run_demo.py
```

## How the backend is arranged

`backend/main.py` is only the entry point (`uvicorn main:app`). Everything else is the `app` package:

```
backend/
  main.py          entry point; also lets scripts and tests say main.<name> for anything in app
  app/
    bootstrap.py   builds the application, in the order it has to happen in
    core/          what every part relies on: configuration, security, who is calling, money,
                   dates, files, notifications, the scheduler, the middleware
    models/        every table, one file per area (accounts, invoicing, hr, subcontracts ...)
    db/            the connection (session.py) and keeping older databases current (migrations.py)
    schemas/       what each endpoint is sent, one file per area
    services/      the rules and workings behind the endpoints, one file per area
    routers/       the endpoints themselves, one file per area
    validators/    checks on what people enter
    constants/     the fixed lists, limits and statuses each area works to
    documents/     printed and Excel documents: letterhead, forms, the PDF drawing code
    ai/            everything that calls an AI model, one file per feature (see ai/__init__.py)
    static/        the two files the old phone app still asks for at the root of the site
  scripts/         seed_demo.py and run_demo.py
  tests/
```

An area has the same name in `routers/`, `services/`, `schemas/` and `constants/`, so the code
behind an endpoint is easy to find: `/api/sub-bills` is in `routers/subcontract_billing.py`,
and what it calls is in `services/subcontract_billing.py`.

Some services call each other (an order needs its approvals, approvals need the order). Where two
modules need each other, the names one of them only uses while running are imported at the bottom
of its file, under a comment saying so, so the file can still be read from the top. Everything else
imports at the top as usual. Importing any part of the package builds the whole application first,
in the same order the server uses, so a script can import a single service and get it fully wired.

## Tests

```bash
cd backend
python -m pytest -q
```

Around 2,500 of them, roughly ten minutes. The few that load the compiled web app skip
unless `npm run build` has been run in `frontend/`. They are written as statements
about how the business works rather than about how the code is arranged — the
name of a failing test should tell you which rule broke.

## Deploying

See [docs/deployment.md](docs/deployment.md). `DATABASE_URL` and `SECRET_KEY` are required in any
deployed environment and the app refuses to start without them rather than
silently falling back to a local file that vanishes on the next deploy.

## A note for whoever changes the models

Adding a column to an existing table is **three** edits, not one:

1. the model, in its area's file under `backend/app/models/`
2. the Postgres list in `ensure_columns()` in `backend/app/db/migrations.py`
3. the SQLite list in `migrate_sqlite()` in the same file

Miss 2 or 3 and the tests still pass — they build their database fresh — while
every existing database returns a 500 on any query naming that column. It has
happened three times. Check the table name too: the item table is `erp_items`,
not `items`.
