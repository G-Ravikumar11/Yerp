# Y ERP

An ERP for a civil contracting business. Built around the way a site actually
runs — an order is placed, material arrives at the gate, work is measured in
the book, bills follow the measurements, and somebody has to know at the end of
it whether the job made money.

Single company, single owner, staff underneath with only the rights the owner
gives them.

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

**Measurement book** — what has actually been built. Entries accumulate; a
correction is a negative entry, never an edit, because a book that can be
rubbed out is not a record.

**Variations** — when the site builds past the order, the book already knows.
The variation drafts itself from that flag: lines, quantities, rates and money.
Approving it raises the order so the extra work becomes billable.

**RA bills** — each bill claims the difference between what has been measured
and what earlier bills already claimed. Retention off the work, tax on the
remainder, TDS off the whole claim. Draft → submitted → certified → paid, and
the person who measured cannot be the one who certifies.

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

```bash
cd backend
pip install -r requirements.txt
python -m uvicorn main:app --reload
```

Then open http://localhost:8000. With no `DATABASE_URL` set it uses a local
SQLite file; set one to point at Postgres.

A seeded demo with sample data:

```bash
python backend/run_demo.py
```

## Tests

```bash
cd backend
python -m pytest -q
```

Around 1,390 of them, roughly eight minutes. They are written as statements
about how the business works rather than about how the code is arranged — the
name of a failing test should tell you which rule broke.

## Deploying

See [DEPLOY.md](DEPLOY.md). `DATABASE_URL` and `SECRET_KEY` are required in any
deployed environment and the app refuses to start without them rather than
silently falling back to a local file that vanishes on the next deploy.

## A note for whoever changes the models

Adding a column to an existing table is **three** edits, not one:

1. the model in `backend/models.py`
2. the Postgres list in `ensure_columns()` in `backend/database.py`
3. the SQLite list in `migrate_sqlite()` in the same file

Miss 2 or 3 and the tests still pass — they build their database fresh — while
every existing database returns a 500 on any query naming that column. It has
happened three times. Check the table name too: the item table is `erp_items`,
not `items`.
