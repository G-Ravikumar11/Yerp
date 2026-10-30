"""Dealing with whatever points at a row, before the row is deleted.

SQLite lets a pointer to a deleted row stand; Postgres, which the live site runs on, refuses the delete ("still
referenced from table ..."). A handler that listed the tables to clear by hand missed some, and the delete then failed
only on the live site. This reads the pointers from the models instead, so a table added later is covered too.
"""
from sqlalchemy import delete, update

from app import models
from app.core.queries import execute_together


def release_references(db, parent_table: str, parent_id: int, *, then=()):
    """Everything that points at row `parent_id` of `parent_table` lets go of it.

    A record that is only ever about that row (a person's payslips, their leave, their site assignments) goes with it.
    A record that merely names it (the bill they submitted, the job they managed, the manager of a team) keeps its
    place and loses the name: the history stays, with nobody against it.

    The statements - forty of them for an employee - go to the database together, followed by any in `then` (the
    delete of the row itself): one round trip rather than one each, which made deleting somebody take many seconds.
    """
    statements = []
    # Children before parents, so a record about the row is gone before the records it in turn is referenced by.
    for table in reversed(models.Base.metadata.sorted_tables):
        for column in table.columns:
            for key in column.foreign_keys:
                if key.column.table.name != parent_table:
                    continue
                if column.nullable:
                    statements.append(update(table).where(column == parent_id).values({column.name: None}))
                else:
                    statements.append(delete(table).where(column == parent_id))
    execute_together(db, [*statements, *then])
