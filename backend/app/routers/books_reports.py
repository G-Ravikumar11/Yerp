"""The trial balance and the day book: what accounts reads to check the books before they are sent to Tally."""
from datetime import date

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.auth import require_items_access
from app.core.sheets import sheet_response
from app.db import get_read_db
from app.services.books_reports import check_period, day_book, day_book_sheet, trial_balance, trial_balance_sheet

router = APIRouter()


def _day_period(day, date_from, date_to):
    """One day (`date`), or a run of days; with nothing asked for, today."""
    if day:
        date_from = date_to = day
    elif not date_from and not date_to:
        date_from = date_to = date.today().isoformat()
    f, t = check_period(date_from or date_to, date_to or date_from)
    return f, t


@router.get("/api/reports/trial-balance")
def trial_balance_report(request: Request, date_from: str = "", date_to: str = "", db: Session = Depends(get_read_db)):
    """Every ledger with its opening, the period's debits and credits, and its closing - read from the same balanced vouchers
    Tally is sent, so what is checked here is what goes across."""
    client = require_items_access(request, db, "bills.view_all")
    f, t = check_period(date_from, date_to)
    return trial_balance(db, client, f, t)


@router.get("/api/reports/trial-balance.xlsx")
def trial_balance_workbook(request: Request, date_from: str = "", date_to: str = "", db: Session = Depends(get_read_db)):
    client = require_items_access(request, db, "bills.view_all")
    f, t = check_period(date_from, date_to)
    headers, rows, preamble, closing = trial_balance_sheet(trial_balance(db, client, f, t), client.company_name)
    return sheet_response(headers, rows, "trial_balance_%s_%s.xlsx" % (f or "start", t or "today"), preamble=preamble, closing=closing)


@router.get("/api/reports/day-book")
def day_book_report(request: Request, date: str = "", date_from: str = "", date_to: str = "", db: Session = Depends(get_read_db)):
    """The vouchers of a day, each with its ledger lines, oldest first. `date` for one day; or `date_from` and `date_to`."""
    client = require_items_access(request, db, "bills.view_all")
    f, t = _day_period(date, date_from, date_to)
    return day_book(db, client, f, t)


@router.get("/api/reports/day-book.xlsx")
def day_book_workbook(request: Request, date: str = "", date_from: str = "", date_to: str = "", db: Session = Depends(get_read_db)):
    client = require_items_access(request, db, "bills.view_all")
    f, t = _day_period(date, date_from, date_to)
    headers, rows, preamble, closing = day_book_sheet(day_book(db, client, f, t), client.company_name)
    return sheet_response(headers, rows, "day_book_%s_%s.xlsx" % (f, t), preamble=preamble, closing=closing)
