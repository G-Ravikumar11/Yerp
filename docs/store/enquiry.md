# P1 - Stock enquiry

Backend: `routers/store_enquiry.py`. Frontend: `features/store/enquiry/`. Tests: `backend/tests/store/test_enquiry.py`.
Migration `store_002_foundation`: adds no tables. This repo has no Alembic, so the name only labels the change.

Right: `store.enquiry.view`. Staff see only the stores they are assigned to (everything with `store.admin`; the account holder sees every store); a named `store_id` they cannot reach is 403.

## Enquiry - `/api/store/enquiry`
- `GET /stock` - one row per store and item (`store_id`, `q`, `below_reorder`, `include_zero`, paged), with the total value.
- `GET /ledger` - movements newest first (`store_id`, `item_id`, `movement_type`, `from_date`, `to_date`, `project_id`, paged).
  Reversals are their own rows, flagged by `reversal_of_id`.
- `GET /items/{id}` - one item across the person's stores, last ten movements, and use in the last 30 days.

`GET /api/store/masters` and `GET /api/store/enquiry` still return the skeleton's `{"slice", "items": []}` so the
skeleton smoke test holds; the real data is on the routes above.


## Not applicable
Enquiry is read-only, so there is no lifecycle and no printable form; stock exports are the reports slice's.
