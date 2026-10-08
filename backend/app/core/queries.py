"""Reading rows in bulk, without a query per row."""
from app import models


def on_job(db, model, client_id, job_id):
    """A project's rows of one kind. A list of every project sets db.info["by_job"], and then each table is read
    once and grouped, rather than queried again for every project on the list."""
    pre = db.info.get("by_job")
    if pre is None:
        return db.query(model).filter(model.client_id == client_id, model.job_id == job_id).all()
    if model not in pre:
        groups = {}
        for r in db.query(model).filter(model.client_id == client_id).all():
            groups.setdefault(r.job_id, []).append(r)
        pre[model] = groups
    return pre[model].get(job_id, [])


def by_id(db, model, ident):
    """One row by its key. The session's own copy when this request has
    already loaded it - a list of forty bills on three orders asks for three
    orders, not forty - and one query when it has not."""
    if not ident:
        return None
    # The session's own map holds rows only while something else does, so a list that asks for the same
    # contractor forty times went to the database forty times. Keep what this request has read.
    held = db.info.setdefault("by_id", {})
    key = (model, ident)
    if key not in held:
        held[key] = db.get(model, ident)
    return held[key]


def prime(db, model, ids):
    """Read many rows by key in one query, into the store by_id answers from - for a list that would otherwise
    fetch the contractor, the project and the unit of every row one at a time (one round trip to the database
    each, which on a hosted database is what made long lists slow)."""
    held = db.info.setdefault("by_id", {})
    want = sorted({i for i in ids if i and (model, i) not in held})
    for at in range(0, len(want), 500):
        part = want[at:at + 500]
        for row in db.query(model).filter(model.id.in_(part)).all():
            held[(model, row.id)] = row
        for i in part:
            held.setdefault((model, i), None)


def prime_chains(db, entity_type, ids):
    """The approval routes of many documents in one query, for a list that shows each one's route."""
    store = db.info.setdefault("chains", {})
    want = [i for i in set(ids) if i and (entity_type, i) not in store]
    for i in want:
        store[(entity_type, i)] = []
    for at in range(0, len(want), 500):
        for row in db.query(models.DBApprovalChain).filter(
                models.DBApprovalChain.entity_type == entity_type,
                models.DBApprovalChain.entity_id.in_(want[at:at + 500])).order_by(models.DBApprovalChain.step).all():
            store[(entity_type, row.entity_id)].append(row)


def chain_rows(db, entity_type, entity_id):
    store = db.info.get("chains")
    if store is not None and (entity_type, entity_id) in store:
        return store[(entity_type, entity_id)]
    return db.query(models.DBApprovalChain).filter(
        models.DBApprovalChain.entity_type == entity_type,
        models.DBApprovalChain.entity_id == entity_id).order_by(models.DBApprovalChain.step).all()


def forget_chain(db, entity_type, entity_id):
    (db.info.get("chains") or {}).pop((entity_type, entity_id), None)
