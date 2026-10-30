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


def execute_together(db, statements):
    """Run these write statements in order, in one trip to the database.

    Each is still its own statement - checked, and failing, exactly as when sent one by one - but on Postgres they
    travel together, so thirty of them cost one round trip across the ocean instead of thirty. SQLite takes one
    statement at a time, so there they are sent in turn. An error comes back as SQLAlchemy's, as `db.execute`'s would.
    """
    statements = list(statements)
    if not statements:
        return
    if db.bind.dialect.name != "postgresql":
        for statement in statements:
            db.execute(statement)
        return
    conn = db.connection()
    raw = conn.connection.dbapi_connection
    cursor = raw.cursor()
    sql = None
    try:
        # psycopg2 quotes every value itself (mogrify), so the joined text carries no placeholders to fill.
        sql = ";\n".join(cursor.mogrify(str(c), c.params).decode()
                         for c in (s.compile(dialect=conn.dialect) for s in statements))
        cursor.execute(sql)
    except conn.dialect.loaded_dbapi.Error as error:
        from sqlalchemy import exc
        raise exc.DBAPIError.instance(sql, None, error, conn.dialect.loaded_dbapi.Error, dialect=conn.dialect) from error
    finally:
        cursor.close()


_LANES = None


def read_together(db, readers, max_lanes=4):
    """Run independent reads side by side, each on a connection of its own, and return their answers in order.

    From far away the time a read takes is the round trip to the database, so four reads at once cost one instead of
    four. Each reader is called with a session and must return plain values (numbers, strings, tuples, SQLAlchemy `Row`s),
    never ORM objects: an object belongs to the session that read it. The readers do not see this request's own
    uncommitted changes, so this is for reads made before anything is written.

    The first lane is this request's own session, the others take a connection each - and only as many as are idle in
    the pool, because a new connection costs seconds. Without enough, or on SQLite, they run one after another on `db`.
    """
    readers = list(readers)
    engine = db.get_bind()
    if len(readers) < 2 or engine.dialect.name != "postgresql":
        return [reader(db) for reader in readers]
    idle = getattr(engine.pool, "checkedin", lambda: 0)()
    lanes = max(1, min(max_lanes, len(readers), 1 + idle))
    if lanes == 1:
        return [reader(db) for reader in readers]
    from concurrent.futures import ThreadPoolExecutor
    from app.db.session import read_session
    global _LANES
    if _LANES is None:
        _LANES = ThreadPoolExecutor(max_workers=16, thread_name_prefix="db-lane")
    results = [None] * len(readers)

    def lane(i, session=None):
        def work(s):
            for at in range(i, len(readers), lanes):
                results[at] = readers[at](s)
        if session is not None:
            return work(session)
        with read_session() as own:
            work(own)

    others = [_LANES.submit(lane, i) for i in range(1, lanes)]
    failure = None
    try:
        lane(0, db)
    except BaseException as error:           # the others are waited for all the same, so no session is left open
        failure = error
    for future in others:
        try:
            future.result()
        except BaseException as error:
            failure = failure or error
    if failure is not None:
        raise failure
    return results


def insert_rows(table, rows):
    """An INSERT of several rows with the Python-side column defaults already filled in.

    A statement that is compiled by hand and sent with execute_together skips SQLAlchemy's defaults (a created_at set by
    a function, a flag that is False unless said otherwise), which are normally applied as the statement is executed.
    The rows here are completed first, so the statement carries every value itself. Server-side defaults and
    auto-numbered keys are left to the database."""
    from sqlalchemy import insert
    full = []
    for row in rows:
        row = dict(row)
        for column in table.columns:
            default = column.default
            if column.name in row or default is None:
                continue
            if default.is_scalar:
                row[column.name] = default.arg
            elif default.is_callable:
                row[column.name] = default.arg(None)     # SQLAlchemy wraps a function that takes nothing into one that takes the execution context
            elif default.is_clause_element:
                row[column.name] = default.arg
        full.append(row)
    return insert(table).values(full)
