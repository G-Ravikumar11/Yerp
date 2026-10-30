"""A project's own budget: what the work will cost us, line by line, against what the client's BOQ pays.

The client's BOQ gives a rate for every line. The budget gives ours: for each BOQ line the material, the labour and
anything else that goes into one unit of it (a cubic metre of M25 needs so many bags of cement and so many man-days).
The difference is the profit - per line, per section and for the project - before any of the work is bought or done.
"""
from datetime import datetime

from sqlalchemy import Column, Float, ForeignKey, Integer, String, Text, UniqueConstraint

from app.db.session import Base


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class DBBoqBudget(Base):
    """The budget's settings for one project: the overheads and contingency added on top of the direct cost."""
    __tablename__ = "boq_budgets"
    __table_args__ = (UniqueConstraint("client_id", "job_id", name="uq_boq_budget"),)

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    overhead_percent = Column(Float, default=0.0)             # site and head-office overheads, as a share of direct cost
    contingency_percent = Column(Float, default=0.0)          # kept back for what is not foreseen, the same way
    note = Column(Text, default="")
    updated_by_name = Column(String, default="")
    updated_at = Column(String, default=_now)


class DBBoqBudgetItem(Base):
    """One thing that goes into one unit of a BOQ line: a material, a kind of labour, a machine, a sub-contract.

    `coefficient` is how much of it one unit of the BOQ line takes, `rate` is what one unit of it costs us; the line
    cost per unit is the sum of coefficient x rate over its items. Tied to the BOQ line by its `key`, which stays the
    same through every revision of the BOQ, so a new revision does not lose the budget.
    """
    __tablename__ = "boq_budget_items"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    boq_key = Column(String, nullable=False, index=True)
    kind = Column(String, default="MATERIAL")                 # MATERIAL | LABOUR | OTHER
    description = Column(String, default="")
    uom = Column(String, default="")
    coefficient = Column(Float, default=0.0)
    rate = Column(Float, default=0.0)
    item_code = Column(String, default="")                    # the item master's code, when a material came from it
    display_order = Column(Integer, default=0)
    updated_by_name = Column(String, default="")
    updated_at = Column(String, default=_now)
