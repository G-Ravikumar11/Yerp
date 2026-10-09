"""Dealing with whatever points at a row, before the row is deleted.

SQLite lets a pointer to a deleted row stand; Postgres, which the live site runs on, refuses the delete ("still
referenced from table ..."). A handler that listed the tables to clear by hand missed some, and the delete then failed
only on the live site. This reads the pointers from the models instead, so a table added later is covered too.
"""
from sqlalchemy import delete, update

from app import models


def release_references(db, parent_table: str, parent_id: int):
    """Everything that points at row `parent_id` of `parent_table` lets go of it.

    A record that is only ever about that row (a person's payslips, their leave, their site assignments) goes with it.
    A record that merely names it (the bill they submitted, the job they managed, the manager of a team) keeps its
    place and loses the name: the history stays, with nobody against it.
    """
    # Children before parents, so a record about the row is gone before the records it in turn is referenced by.
    for table in reversed(models.Base.metadata.sorted_tables):
        for column in table.columns:
            for key in column.foreign_keys:
                if key.column.table.name != parent_table:
                    continue
                if column.nullable:
                    db.execute(update(table).where(column == parent_id).values({column.name: None}))
                else:
                    db.execute(delete(table).where(column == parent_id))
