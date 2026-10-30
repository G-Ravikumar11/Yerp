"""Store module - the small checks and roundings every store document uses: reading a quantity, a date or a piece of
text from a request, and rounding to the unit's three decimals, a rate's four and a value's two. They lived, copied,
in the inward, outward and control slices; one copy now, which each of them still exposes under the same names."""
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Optional

from fastapi import HTTPException

ZERO = Decimal("0")
_Q, _R, _V = Decimal("0.001"), Decimal("0.0001"), Decimal("0.01")


def dec(value, what, *, minimum=ZERO, allow_zero=True, high=Decimal("999999999999")) -> Decimal:
    try:
        d = Decimal(str(value if value is not None else "").strip())
    except (InvalidOperation, ValueError):
        raise HTTPException(400, "%s is not a number." % what) from None
    if not d.is_finite():
        raise HTTPException(400, "%s is not a number." % what)
    if d < minimum or (d == minimum and not allow_zero):
        raise HTTPException(400, "%s must be %s." % (what, "more than zero" if not allow_zero else "zero or more"))
    if d > high:
        raise HTTPException(400, "%s is too large." % what)
    return d


def day(raw, what, *, allow_future=False, required=True) -> Optional[date]:
    if raw in (None, ""):
        if required:
            raise HTTPException(400, "Give the %s." % what)
        return None
    if isinstance(raw, date):
        out = raw
    else:
        try:
            out = datetime.strptime(str(raw).strip()[:10], "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(400, "%s is not a date (use YYYY-MM-DD)." % what) from None
    if not allow_future and out > date.today():
        raise HTTPException(400, "%s cannot be in the future." % what)
    if out.year < 2000 or out.year > 2100:
        raise HTTPException(400, "%s is not a sensible date." % what)
    return out


def text(value, what, limit, required=False) -> str:
    out = " ".join((value or "").split())
    if required and not out:
        raise HTTPException(400, "Give the %s." % what)
    if len(out) > limit:
        raise HTTPException(400, "Keep the %s to %d characters." % (what, limit))
    return out


def q3(x) -> Decimal:
    return Decimal(str(x)).quantize(_Q, rounding=ROUND_HALF_UP)


def r4(x) -> Decimal:
    return Decimal(str(x)).quantize(_R, rounding=ROUND_HALF_UP)


def v2(x) -> Decimal:
    return Decimal(str(x)).quantize(_V, rounding=ROUND_HALF_UP)


def s2(x) -> str:
    return format(v2(x if x is not None else 0), "f")


def s3(x) -> str:
    return format(q3(x if x is not None else 0), "f")


def s4(x) -> str:
    return format(r4(x if x is not None else 0), "f")
