# P1 - Masters

Backend: `routers/store_masters.py`. Frontend: `features/store/masters/`. Tests: `backend/tests/store/test_masters.py`.
Migration `store_002_foundation`: adds no tables; it works on the `store_core` tables (stores, bins, assignments, item settings, unit conversions, freezes). This repo has no Alembic, so the name only labels the change.

## Rights
| Right | Allows |
|---|---|
| `store.masters.view` | read stores, bins, staff, freezes, item settings |
| `store.masters.create` | add and edit stores, bins, item settings, unit conversions |
| `store.masters.approve` | assign or remove staff, freeze and unfreeze a store |
| `store.masters.cancel` | switch a store or bin off, remove a unit conversion |

Staff reach only the stores they are assigned to (all with `store.admin`; the account holder reaches every store).
A named `store_id` they cannot reach is 403; lists silently cover only their stores.

## Masters - `/api/store/masters`
- `GET /summary`
- `GET|POST /stores`, `PUT /stores/{id}` (the code never changes; a store holding stock cannot be switched off)
- `GET|POST /stores/{id}/bins`, `PUT /bins/{id}`
- `GET /employees`, `GET|POST /stores/{id}/assignments`, `DELETE /assignments/{id}` (switches it off)
- `GET /stores/{id}/freezes`, `POST /stores/{id}/freeze` (reason required), `POST /stores/{id}/unfreeze`
- `GET /items` (`q`, `configured`), `PUT /items/{id}/settings`, `POST /items/{id}/uoms`, `DELETE /uoms/{id}`

The base unit of an item cannot change once any store holds it. Adding a conversion for an existing unit replaces its factor.


## Not applicable
Masters hold no documents, so there is no DRAFT-to-POSTED lifecycle and no printable form.
