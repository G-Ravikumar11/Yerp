"""Money, tax and currency arithmetic and the way amounts are written."""
import html as html_mod
import os
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from fastapi import HTTPException

from app import models


def esc(val) -> str:
    """HTML-escape a value for safe insertion into HTML."""
    if val is None:
        return ""
    return html_mod.escape(str(val))


# Line items carry a human-readable tax label ("20% VAT", "5% VAT",
# "0% Zero Rated", "No Tax"). Everything downstream must derive the rate from
# that label rather than assuming a single blanket rate.
DEFAULT_TAX_RATE = 0.20
_TAX_PCT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")


def parse_tax_rate(label, default: float = DEFAULT_TAX_RATE) -> float:
    """Turn a tax label into a decimal rate. '5% VAT' -> 0.05, 'No Tax' -> 0.0."""
    s = str(label or "").strip()
    if not s:
        return default
    m = _TAX_PCT_RE.search(s)
    if m:
        try:
            return max(0.0, float(m.group(1))) / 100.0
        except ValueError:
            return default
    low = s.lower()
    if any(w in low for w in ("no tax", "none", "zero", "exempt", "outside")):
        return 0.0
    return default


def money(val) -> float:
    """Round to 2dp using banker's-free half-up, which is what invoices expect."""
    try:
        d = Decimal(str(val or 0))
    except (InvalidOperation, ValueError, TypeError):
        return 0.0
    return float(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def qty_text(value) -> str:
    """A quantity as it is written in a sentence: 100, 117.6, 0.125 - not the
    float repr, which put "100.0 ordered" in front of the site engineer."""
    return ("%.3f" % float(value or 0)).rstrip("0").rstrip(".") or "0"


def inr(value) -> str:
    """A rupee figure the way it is read aloud here: 12,34,567.00.

    Indian grouping puts the first comma three from the right and every one
    after it two apart. The web formatter does this already; the server did
    not have one, so any figure the server wrote into a sentence came out as a
    bare float - "400000.0 the customer should already have paid" - which is
    the kind of thing that makes a screen look unfinished at a glance.
    """
    v = money(value)
    neg = v < 0
    whole, frac = divmod(abs(v), 1)
    digits = str(int(whole))
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        pairs = []
        while len(head) > 2:
            pairs.insert(0, head[-2:])
            head = head[:-2]
        if head:
            pairs.insert(0, head)
        digits = ",".join(pairs + [tail])
    return "%s₹%s.%02d" % ("-" if neg else "", digits, int(round(frac * 100)))


def unit_rate(val) -> float:
    """A rate per unit, kept to four places.

    Two is enough for a sum of money and not enough for a multiplier. This
    trade quotes wire at 12.222 the metre; rounded to 12.22 and taken across
    the twelve thousand metres actually being laid, the budget walks away from
    the spreadsheet it was copied from - by six thousand rupees over one
    project, on lines that each looked right to the paisa.

    Only the multiplier is held this wide. Amounts, totals and anything that
    reaches an invoice are still money(), because those are sums of money and
    a bill cannot ask for a fraction of a paisa.
    """
    try:
        d = Decimal(str(val or 0))
    except (InvalidOperation, ValueError, TypeError):
        return 0.0
    return float(d.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def line_net_amount(qty, price, disc) -> float:
    """Amount for a single line after its percentage discount."""
    amount = float(qty or 0) * float(price or 0)
    d = float(disc or 0)
    if d:
        amount *= (1 - d / 100.0)
    return amount


def compute_invoice_totals(line_items, tax_type: str):
    """Subtotal / tax / total for a set of line items, honouring each line's own
    tax rate. `tax_type` is 'exclusive' (tax added on top), 'inclusive' (prices
    already contain tax) or anything else for no tax."""
    subtotal = 0.0
    tax = 0.0
    for item in line_items or []:
        amount = line_net_amount(
            getattr(item, "qty", None), getattr(item, "price", None), getattr(item, "disc", None)
        )
        rate = parse_tax_rate(getattr(item, "tax_rate", None))
        if tax_type == "exclusive":
            subtotal += amount
            tax += amount * rate
        elif tax_type == "inclusive":
            net = amount / (1 + rate) if rate else amount
            subtotal += net
            tax += amount - net
        else:
            subtotal += amount
    subtotal = money(subtotal)
    tax = money(tax)
    return subtotal, tax, money(subtotal + tax)


CURRENCY_SYMBOLS = {
    "AED": "د.إ", "AFN": "؋", "ALL": "L", "AMD": "֏", "ANG": "ƒ", "AOA": "Kz", "ARS": "$",
    "AUD": "A$", "AWG": "ƒ", "AZN": "₼", "BAM": "KM", "BBD": "$", "BDT": "৳", "BGN": "лв",
    "BHD": "ب.د", "BIF": "FBu", "BMD": "$", "BND": "$", "BOB": "Bs", "BRL": "R$", "BSD": "$",
    "BTN": "Nu.", "BWP": "P", "BYN": "Br", "BZD": "$", "CAD": "C$", "CDF": "FC", "CHF": "CHF",
    "CLP": "$", "CNY": "¥", "COP": "$", "CRC": "₡", "CUP": "$", "CVE": "Esc", "CZK": "Kč",
    "DJF": "Fdj", "DKK": "kr", "DOP": "RD$", "DZD": "دج", "EGP": "£", "ERN": "Nfk", "ETB": "Br",
    "EUR": "€", "FJD": "FJ$", "FKP": "£", "GBP": "£", "GEL": "₾", "GHS": "₵", "GIP": "£",
    "GMD": "D", "GNF": "FG", "GTQ": "Q", "GYD": "$", "HKD": "HK$", "HNL": "L", "HRK": "kn",
    "HTG": "G", "HUF": "Ft", "IDR": "Rp", "ILS": "₪", "INR": "₹", "IQD": "ع.د", "IRR": "﷼",
    "ISK": "kr", "JMD": "J$", "JOD": "د.ا", "JPY": "¥", "KES": "KSh", "KGS": "с", "KHR": "៛",
    "KMF": "CF", "KPW": "₩", "KRW": "₩", "KWD": "د.ك", "KYD": "CI$", "KZT": "₸", "LAK": "₭",
    "LBP": "ل.ل", "LKR": "₨", "LRD": "$", "LSL": "L", "LYD": "ل.د", "MAD": "د.م.", "MDL": "L",
    "MGA": "Ar", "MKD": "ден", "MMK": "K", "MNT": "₮", "MOP": "MOP$", "MRU": "UM", "MUR": "₨",
    "MVR": "Rf", "MWK": "MK", "MXN": "$", "MYR": "RM", "MZN": "MT", "NAD": "$", "NGN": "₦",
    "NIO": "C$", "NOK": "kr", "NPR": "₨", "NZD": "NZ$", "OMR": "ر.ع.", "PAB": "B/.", "PEN": "S/",
    "PGK": "K", "PHP": "₱", "PKR": "₨", "PLN": "zł", "PYG": "₲", "QAR": "ر.ق", "RON": "lei",
    "RSD": "дин", "RUB": "₽", "RWF": "FRw", "SAR": "﷼", "SBD": "SI$", "SCR": "₨", "SDG": "ج.س",
    "SEK": "kr", "SGD": "S$", "SHP": "£", "SLL": "Le", "SOS": "Sh", "SRD": "$", "SSP": "£",
    "STN": "Db", "SVC": "$", "SYP": "£", "SZL": "L", "THB": "฿", "TJS": "SM", "TMT": "m",
    "TND": "د.ت", "TOP": "T$", "TRY": "₺", "TTD": "TT$", "TWD": "NT$", "TZS": "Sh", "UAH": "₴",
    "UGX": "USh", "USD": "$", "UYU": "$U", "UZS": "so'm", "VES": "Bs", "VND": "₫", "VUV": "VT",
    "WST": "T", "XAF": "FCFA", "XCD": "EC$", "XOF": "CFA", "XPF": "₣", "YER": "﷼", "ZAR": "R",
    "ZMW": "ZK", "ZWL": "Z$",
}
# The books are kept in rupees unless a tenant says otherwise. One
# constant so a default never has to be hunted down in twelve places.
DEFAULT_CURRENCY = "INR"


def currency_symbol(code):
    code = (code or "").upper()
    return CURRENCY_SYMBOLS.get(code, code or "£")


def formatted_money(db, client_id, amount) -> str:
    """An amount in the tenant's own currency, for messages people read."""
    client = db.query(models.DBClient).filter(models.DBClient.id == client_id).first()
    code = (client.currency if client else "") or DEFAULT_CURRENCY
    return f"{currency_symbol(code)}{money(amount):,.2f}"


# SALES PIPELINE - quotes and invoices as one flow instead of two lists
def totals_by_currency(cards, field="total", fallback=DEFAULT_CURRENCY):
    """Sum per currency and return the biggest first.

    Deliberately not one number: adding GBP to INR needs an exchange rate, and
    guessing one would put a made-up figure in front of somebody making
    decisions with it.
    """
    buckets = {}
    for c in cards:
        code = (c.get("currency") or fallback or "").upper() or fallback
        buckets[code] = buckets.get(code, 0) + (c.get(field) or 0)
    return [{"currency": code, "value": money(v)}
            for code, v in sorted(buckets.items(), key=lambda kv: -abs(kv[1]))]


def lines_money(body):
    """What the schedule on an order comes to, when it has one.

    A purchase order may carry a total and no schedule - a committed cost
    against a project that nobody has itemised - and that is allowed. What
    is not allowed is a schedule that disagrees with the total printed above
    it: the lines are what the storekeeper counts off the lorry and what the
    bill is matched against, so where there are lines they are the order.
    """
    lines = body.get("line_items") or []
    if not lines:
        return None
    amount, tax = 0.0, 0.0
    for li in lines:
        try:
            qty = float(li.get("qty") or 0)
            price = float(li.get("price") or 0)
        except (TypeError, ValueError):
            raise HTTPException(400, "Every line needs a quantity and a price.")
        if qty < 0 or price < 0:
            raise HTTPException(400, "A quantity or a price cannot be negative.")
        value = qty * price
        amount += value
        tax += value * tax_percent_of(li.get("tax_rate")) / 100.0
    return money(amount), money(tax), money(amount + tax)


def tax_percent_of(rate):
    """"18%" -> 18.0. Anything unreadable is no tax rather than a guess."""
    try:
        return float(re.sub(r"[^0-9.]", "", str(rate or "")) or 0)
    except ValueError:
        return 0.0


# WALLET & METERED BILLING
# Tenants hold a prepaid balance. Actions that cost the platform real money
# (sending mail, WhatsApp, AI calls, payroll processing) are metered against
# it. The operator sets the prices; tenants can only top up and spend.
#
# All arithmetic is in integer minor units. A running balance must reconcile
# exactly, and repeated float addition drifts.
CURRENCY_MINOR_UNITS = {"JPY": 1, "KRW": 1, "VND": 1, "CLP": 1, "ISK": 1}


def minor_units(currency):
    """How many minor units make one major unit. Most currencies are 100."""
    return CURRENCY_MINOR_UNITS.get((currency or DEFAULT_CURRENCY).upper(), 100)


def to_minor(amount, currency="GBP"):
    """Decimal amount -> integer minor units, rounded half-up."""
    try:
        d = Decimal(str(amount or 0))
    except (InvalidOperation, ValueError, TypeError):
        return 0
    return int((d * minor_units(currency)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def to_major(amount_minor, currency="GBP"):
    """Integer minor units -> decimal amount for display."""
    return round((amount_minor or 0) / minor_units(currency), 2)


PLATFORM_CURRENCY = os.getenv("PLATFORM_CURRENCY", "GBP").upper()


def amount_in_words(value):
    """Rupees in words, because a legal document states the figure twice.

    Indian grouping - crore, lakh, thousand - since that is the reading the
    signatories will check it against.
    """
    units = ("", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight",
             "Nine", "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen",
             "Sixteen", "Seventeen", "Eighteen", "Nineteen")
    tens = ("", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy",
            "Eighty", "Ninety")

    def under_hundred(n):
        if n < 20:
            return units[n]
        return (tens[n // 10] + (" " + units[n % 10] if n % 10 else "")).strip()

    def under_thousand(n):
        if n < 100:
            return under_hundred(n)
        rest = n % 100
        return (units[n // 100] + " Hundred" +
                (" and " + under_hundred(rest) if rest else ""))

    def natural(n):
        """Indian grouping. The crore figure is itself grouped, so a hundred
        crore reads as one and not as an index error."""
        parts = []
        for divisor, label in ((10000000, "Crore"), (100000, "Lakh"), (1000, "Thousand")):
            if n >= divisor:
                count = n // divisor
                parts.append((natural(count) if count >= 1000 else under_thousand(count))
                             + " " + label)
                n %= divisor
        if n:
            parts.append(under_thousand(n))
        return " ".join(parts)

    # A bill can come to less than nothing - an advance recovered against a
    # small month's work - and the words have to say so rather than fail.
    amount = money(value)
    negative = amount < 0
    amount = abs(amount)
    whole = int(amount)
    paise = int(round((amount - whole) * 100))
    if paise == 100:
        whole, paise = whole + 1, 0
    words = natural(whole) if whole else "Zero"
    out = ("Minus " if negative else "") + "Rupees " + words
    if paise:
        out += " and " + under_hundred(paise) + " Paise"
    return out + " Only"


def format_money_plain(value):
    """12,34,567.00 - Indian grouping, because that is how the figure is read."""
    from app.documents import wo_pdf
    return "Rs. " + wo_pdf.inr(value)


def sheet_number(value):
    """A number as a sheet writes one.

    money() and unit_rate() take a bare numeral; a cell exported from Excel
    or typed by a person carries the grouping, the currency and sometimes the
    brackets that mean a negative. Read strictly, "12,34,567.50" is not a
    number at all and comes back as nought - which on a rate column is a line
    that silently prices at zero.
    """
    text = str(value if value is not None else "").strip()
    if not text:
        return 0.0
    negative = text.startswith("(") and text.endswith(")")
    text = re.sub(r"[^0-9.\-]", "", text)
    if text in ("", "-", ".", "-."):
        return 0.0
    try:
        number = float(text)
    except ValueError:
        return 0.0
    return -number if negative and number > 0 else number


def rupees(val) -> float:
    """Whole rupees, a half rounded up - Excel's ROUND(x, 0), which is how the
    certificate of payment has always rounded its figures."""
    try:
        d = Decimal(str(val or 0))
    except (InvalidOperation, ValueError):
        return 0.0
    return float(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
