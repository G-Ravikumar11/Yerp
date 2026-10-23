"""The books, for Tally.

The ERP does the accounts office's day; the company's books - the trial balance, the P&L, the balance sheet the
auditor signs - are kept in Tally by the CA. This writes what happened in a period as Tally Prime reads it: an XML of
masters (the ledgers and the projects as cost centres) and an XML of vouchers, imported in that order through Gateway
of Tally > Import > Masters, then Transactions.

What goes across
    Receipts and payments (against a bill, on account), expense vouchers and sundry receipts, transfers between our own
    accounts (contra), client RA bills (sales, with output GST, TDS deducted by the client, retention held and advance
    recovered), supplier bills (purchases with input GST) and contractor RA bills (a journal: their work and its GST
    against what is owed them, the TDS and labour cess we deduct, retention we hold and advance we recover). Every line
    of income or cost carries its project as a cost centre, so Tally can show each site's P&L too.

How the sums are kept honest
    A bill's own deductions are each put on their own ledger; whatever else came off it - back-charges, debit notes,
    LD, material recovered - is one line, worked out as what makes the voucher balance to the rupee, so a voucher that
    Tally refuses for not balancing cannot be written. Each voucher carries a REMOTEID, so the same one imported twice
    is recognised by Tally rather than doubled.

The ledger names are the company's to set (Settings, Tally), to match the ledgers already in their Tally company.
"""
import json
import re
from xml.sax.saxutils import escape, quoteattr

from app import models
from app.core.currency import money
from app.core.tenant_settings import tenant_setting

SETTING = "tally_ledgers"

# key: (default ledger name, Tally group it is created under, takes a cost centre)
LEDGERS = {
    "sales": ("Sales - Works Contract", "Sales Accounts", True),
    "output_cgst": ("Output CGST", "Duties & Taxes", False),
    "output_sgst": ("Output SGST", "Duties & Taxes", False),
    "output_igst": ("Output IGST", "Duties & Taxes", False),
    "tds_receivable": ("TDS Receivable", "Loans & Advances (Asset)", False),
    "retention_receivable": ("Retention Money Receivable", "Current Assets", False),
    "client_advance": ("Mobilisation Advance from Clients", "Current Liabilities", False),
    "client_deductions": ("Deductions by Clients", "Indirect Expenses", True),
    "purchases": ("Purchases - Materials", "Purchase Accounts", True),
    "input_gst": ("Input GST", "Duties & Taxes", False),
    "input_cgst": ("Input CGST", "Duties & Taxes", False),
    "input_sgst": ("Input SGST", "Duties & Taxes", False),
    "input_igst": ("Input IGST", "Duties & Taxes", False),
    "subcontract": ("Subcontract Charges", "Direct Expenses", True),
    "tds_payable": ("TDS Payable - Contractors", "Duties & Taxes", False),
    "labour_cess": ("Labour Cess Payable", "Duties & Taxes", False),
    "retention_payable": ("Retention Money Payable", "Current Liabilities", False),
    "contractor_advance": ("Mobilisation Advance to Contractors", "Loans & Advances (Asset)", False),
    "contractor_recoveries": ("Recoveries from Contractors", "Direct Incomes", True),
    "unassigned_bank": ("Bank (account not recorded)", "Bank Accounts", False),
    "cash": ("Cash", "Cash-in-Hand", False),
}
LABELS = {
    "sales": "Work billed to clients (RA bills)", "output_cgst": "Output CGST", "output_sgst": "Output SGST",
    "output_igst": "Output IGST", "tds_receivable": "TDS deducted by clients", "retention_receivable": "Retention held by clients",
    "client_advance": "Mobilisation advance from clients", "client_deductions": "Other deductions by clients",
    "purchases": "Supplier bills", "input_gst": "GST on supplier bills", "input_cgst": "Input CGST (contractors)",
    "input_sgst": "Input SGST (contractors)", "input_igst": "Input IGST (contractors)", "subcontract": "Contractors' work",
    "tds_payable": "TDS deducted from contractors", "labour_cess": "Labour cess deducted", "retention_payable": "Retention held from contractors",
    "contractor_advance": "Mobilisation advance to contractors", "contractor_recoveries": "Other recoveries from contractors",
    "unassigned_bank": "Payments with no bank account recorded", "cash": "Cash paid with no cash box recorded",
}
# Heads that are the site's own cost (Direct Expenses in Tally); the rest are overheads.
DIRECT_HEADS = {"Site expenses", "Diesel & fuel", "Machinery hire", "Transport & freight", "Repairs & maintenance"}
PARTY_GROUP = {"client": "Sundry Debtors", "supplier": "Sundry Creditors", "contractor": "Sundry Creditors", "other": "Sundry Creditors"}
COST_CATEGORY = "Primary Cost Category"


def ledger_names(db, client_id):
    """The ledger names in use: the company's own where set, the defaults otherwise."""
    try:
        mine = json.loads(tenant_setting(db, client_id, SETTING, "{}") or "{}")
    except ValueError:
        mine = {}
    return {k: (str(mine.get(k) or "").strip()[:100] or d) for k, (d, _, _) in LEDGERS.items()}


def save_ledger_names(db, client_id, names):
    clean = {k: re.sub(r"\s+", " ", str(v or "")).strip()[:100] for k, v in (names or {}).items() if k in LEDGERS}
    value = json.dumps({k: v for k, v in clean.items() if v and v != LEDGERS[k][0]})
    row = db.query(models.DBSettings).filter(models.DBSettings.client_id == client_id, models.DBSettings.key == SETTING).first()
    if row:
        row.value = value
    else:
        db.add(models.DBSettings(client_id=client_id, key=SETTING, value=value, description="Tally ledger names"))


def _x(text):
    """Text as Tally will take it: no control characters, & < > escaped."""
    return escape(re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(text or "")))


def _tdate(iso):
    return re.sub(r"\D", "", (iso or "")[:10])


class Books:
    """The period's vouchers, as balanced lists of ledger lines, and every ledger and cost centre they name."""

    def __init__(self, db, client, date_from, date_to):
        self.db, self.client, self.date_from, self.date_to = db, client, date_from or "0000-00-00", date_to or "9999-12-31"
        self.names = ledger_names(db, client.id)
        self.vouchers = []
        self.ledgers = {}               # name -> (group, takes cost centre)
        self.cost_centres = set()
        self.warnings = []
        self.jobs = {j.id: j for j in db.query(models.DBJob).filter(models.DBJob.client_id == client.id).all()}
        self.accounts = {a.id: a for a in db.query(models.DBBankAccount).filter(models.DBBankAccount.client_id == client.id).all()}
        self._money()
        self._client_bills()
        self._supplier_bills()
        self._contractor_bills()
        self.vouchers.sort(key=lambda v: (v["date"], v["type"], v["number"]))

    # --- naming ---
    def std(self, key):
        name = self.names[key]
        _, group, cc = LEDGERS[key]
        self.ledgers.setdefault(name, (group, cc))
        return name

    def party(self, name, kind):
        name = (name or "").strip() or "Unnamed party"
        self.ledgers.setdefault(name, (PARTY_GROUP.get(kind, "Sundry Creditors"), False))
        return name

    def account(self, account_id, mode):
        a = self.accounts.get(account_id)
        if a is None:
            return self.std("cash" if mode == "Cash" else "unassigned_bank")
        name = (a.name or "Bank").strip()
        self.ledgers.setdefault(name, ("Cash-in-Hand" if a.kind == "Cash" else "Bank Accounts", False))
        return name

    def head(self, head, income=False):
        name = head or ("Other income" if income else "Other expenses")
        group = "Indirect Incomes" if income else ("Direct Expenses" if name in DIRECT_HEADS else "Indirect Expenses")
        self.ledgers.setdefault(name, (group, True))
        return name

    def centre(self, job_id):
        j = self.jobs.get(job_id)
        if j is None:
            return ""
        name = ("%s %s" % (j.number or "", j.name or "")).strip()[:100]
        self.cost_centres.add(name)
        return name

    def add(self, vtype, number, on, narration, lines, remote, job_id=None):
        """lines: [(ledger, amount, bill_ref, ref_type)], amount positive for a debit, negative for a credit."""
        lines = [(l, money(a), *rest) for l, a, *rest in lines if abs(money(a)) >= 0.005]
        total = money(sum(a for _, a, *_ in lines))
        if abs(total) >= 0.01:            # cannot happen by construction; refused rather than written wrong
            self.warnings.append("%s %s did not balance by %s and was left out." % (vtype, number, total))
            return
        self.vouchers.append({"type": vtype, "number": number, "date": on[:10], "narration": narration,
                              "lines": lines, "remote": remote, "centre": self.centre(job_id)})

    # --- what goes across ---
    def _money(self):
        q = self.db.query(models.DBMoneyEntry).filter(
            models.DBMoneyEntry.client_id == self.client.id, models.DBMoneyEntry.voided.isnot(True),
            models.DBMoneyEntry.paid_on >= self.date_from, models.DBMoneyEntry.paid_on <= self.date_to)
        for e in q.order_by(models.DBMoneyEntry.paid_on, models.DBMoneyEntry.id).all():
            amt = money(e.amount)
            here = self.account(e.account_id, e.mode)
            ref = " (%s %s)" % (e.mode, e.reference) if e.reference else (" (%s)" % e.mode if e.mode else "")
            remote = "yerp-%d-money-%d" % (self.client.id, e.id)
            if e.doc_type == "contra":
                if e.direction != "OUT":
                    continue                                  # one voucher for the two entries
                other = self.db.query(models.DBMoneyEntry).filter(models.DBMoneyEntry.id == e.pair_id).first()
                there = self.account(other.account_id if other else None, e.mode)
                self.add("Contra", e.number, e.paid_on, "Transfer%s%s" % (ref, (". " + e.note) if e.note else ""),
                         [(there, amt), (here, -amt)], remote)
                continue
            if e.doc_type in ("expense", "income"):
                ledger = self.head(e.head, income=e.doc_type == "income")
                say = "%s - %s%s%s" % (e.head, e.party_name or "", ref, (". " + e.note) if e.note else "")
            else:
                ledger = self.party(e.party_name, e.party_type)
                say = "%s %s%s%s" % ("Received from" if e.direction == "IN" else "Paid to", e.party_name or "",
                                     (" against " + e.doc_number) if e.doc_number else " on account", ref)
            bill = (e.doc_number or "", "Agst Ref") if e.doc_number else (("%s on account" % e.number, "Advance")
                                                                         if e.doc_type == "on_account" else ("", ""))
            if e.direction == "IN":
                self.add("Receipt", e.number, e.paid_on, say, [(here, amt), (ledger, -amt, *bill)], remote, e.job_id)
            else:
                self.add("Payment", e.number, e.paid_on, say, [(ledger, amt, *bill), (here, -amt)], remote, e.job_id)

    def _client_bills(self):
        q = self.db.query(models.DBRABill).filter(models.DBRABill.client_id == self.client.id,
                                                  models.DBRABill.status.in_(("CERTIFIED", "PAID")))
        for b in q.all():
            on = (b.certified_at or b.created_at or "")[:10]
            if not (self.date_from <= on <= self.date_to):
                continue
            job = self.jobs.get(b.job_id)
            party = self.party(job.customer_name if job else "", "client")
            taxable, net = money(b.this_bill), money(b.net_payable)
            ret, adv, tds = money(b.retention_amount), money(b.advance_recovery), money(b.tds_amount)
            cgst, sgst, igst = money(b.cgst_amount), money(b.sgst_amount), money(b.igst_amount)
            other = money(taxable + cgst + sgst + igst - net - ret - adv - tds)
            lines = [(party, net, b.number, "New Ref"), (self.std("tds_receivable"), tds),
                     (self.std("retention_receivable"), ret), (self.std("client_advance"), adv),
                     (self.std("client_deductions"), other), (self.std("sales"), -taxable),
                     (self.std("output_cgst"), -cgst), (self.std("output_sgst"), -sgst), (self.std("output_igst"), -igst)]
            self.add("Sales", b.number, on, "RA bill %s certified%s" % (b.number, (" - " + b.deduction_notes) if b.deduction_notes else ""),
                     lines, "yerp-%d-rabill-%d" % (self.client.id, b.id), b.job_id)

    def _supplier_bills(self):
        q = self.db.query(models.DBBill).filter(models.DBBill.client_id == self.client.id)
        for b in q.all():
            if (b.status or "") in ("Draft", "Cancelled", "Rejected") or (b.approval_status or "none") == "rejected":
                continue
            on = (b.issue_date or b.created_at or "")[:10]
            if not (self.date_from <= on <= self.date_to):
                continue
            total = money(b.total or b.amount or 0)
            tax = money(b.tax_amount or 0)
            party = self.party(b.vendor_name, "supplier")
            self.add("Purchase", b.number or "Bill %d" % b.id, on,
                     "Bill %s from %s%s" % (b.number or "", b.vendor_name or "", (" - " + b.notes) if b.notes else ""),
                     [(self.std("purchases"), money(total - tax)), (self.std("input_gst"), tax),
                      (party, -total, b.number or "", "New Ref")],
                     "yerp-%d-bill-%d" % (self.client.id, b.id), b.job_id)

    def _contractor_bills(self):
        contractors = {c.id: c for c in self.db.query(models.DBContractor).filter(models.DBContractor.client_id == self.client.id).all()}
        q = self.db.query(models.DBSubBill).filter(models.DBSubBill.client_id == self.client.id,
                                                   models.DBSubBill.status.in_(("CERTIFIED", "PAID")))
        for b in q.all():
            on = (b.certified_at or b.bill_date or b.created_at or "")[:10]
            if not (self.date_from <= on <= self.date_to):
                continue
            con = contractors.get(b.contractor_id)
            party = self.party(con.company_name if con else "", "contractor")
            taxable, net = money(b.this_bill), money(b.net_payable)
            cgst, sgst, igst = money(b.cgst_amount), money(b.sgst_amount), money(b.igst_amount)
            ret, adv, tds, cess = (money(b.retention_amount), money(b.advance_recovery), money(b.tds_amount),
                                   money(b.labour_cess_amount))
            other = money(taxable + cgst + sgst + igst - net - ret - adv - tds - cess)
            lines = [(self.std("subcontract"), taxable), (self.std("input_cgst"), cgst), (self.std("input_sgst"), sgst),
                     (self.std("input_igst"), igst), (party, -net, b.number, "New Ref"), (self.std("tds_payable"), -tds),
                     (self.std("labour_cess"), -cess), (self.std("retention_payable"), -ret),
                     (self.std("contractor_advance"), -adv), (self.std("contractor_recoveries"), -other)]
            self.add("Journal", b.number, on, "Contractor's RA bill %s certified%s" % (b.number, (" - " + b.deduction_notes) if b.deduction_notes else ""),
                     lines, "yerp-%d-subbill-%d" % (self.client.id, b.id), b.job_id)

    def summary(self):
        by = {}
        for v in self.vouchers:
            s = by.setdefault(v["type"], {"type": v["type"], "count": 0, "amount": 0.0})
            s["count"] += 1
            s["amount"] = money(s["amount"] + sum(a for _, a, *_ in v["lines"] if a > 0))
        return {"vouchers": sorted(by.values(), key=lambda s: s["type"]), "ledgers": len(self.ledgers),
                "cost_centres": len(self.cost_centres), "warnings": self.warnings}


def _envelope(report, company, messages):
    company_xml = "<STATICVARIABLES><SVCURRENTCOMPANY>%s</SVCURRENTCOMPANY></STATICVARIABLES>" % _x(company) if company else ""
    return ("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<ENVELOPE>\n<HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER>\n"
            "<BODY>\n<IMPORTDATA>\n<REQUESTDESC><REPORTNAME>%s</REPORTNAME>%s</REQUESTDESC>\n<REQUESTDATA>\n%s</REQUESTDATA>\n"
            "</IMPORTDATA>\n</BODY>\n</ENVELOPE>\n") % (report, company_xml, "".join(messages))


def masters_xml(books, company=""):
    msgs = []
    for name in sorted(books.cost_centres):
        msgs.append('<TALLYMESSAGE xmlns:UDF="TallyUDF"><COSTCENTRE NAME=%s ACTION="Create"><NAME.LIST><NAME>%s</NAME></NAME.LIST>'
                    '<CATEGORY>%s</CATEGORY><PARENT/></COSTCENTRE></TALLYMESSAGE>\n' % (quoteattr(name), _x(name), COST_CATEGORY))
    for name, (group, cc) in sorted(books.ledgers.items()):
        billwise = "Yes" if group in ("Sundry Debtors", "Sundry Creditors") else "No"
        msgs.append('<TALLYMESSAGE xmlns:UDF="TallyUDF"><LEDGER NAME=%s ACTION="Create"><NAME.LIST><NAME>%s</NAME></NAME.LIST>'
                    '<PARENT>%s</PARENT><ISBILLWISEON>%s</ISBILLWISEON><ISCOSTCENTRESON>%s</ISCOSTCENTRESON></LEDGER></TALLYMESSAGE>\n'
                    % (quoteattr(name), _x(name), _x(group), billwise, "Yes" if cc and books.cost_centres else "No"))
    return _envelope("All Masters", company, msgs)


def vouchers_xml(books, company=""):
    msgs = []
    for v in books.vouchers:
        rows = []
        for line in v["lines"]:
            ledger, amt = line[0], line[1]
            bill, kind = (line[2], line[3]) if len(line) > 3 else ("", "")
            tally_amt = "%.2f" % (-amt)                  # Tally: debit negative and deemed positive; credit positive
            alloc = ""
            if bill:
                alloc = ("<BILLALLOCATIONS.LIST><NAME>%s</NAME><BILLTYPE>%s</BILLTYPE><AMOUNT>%s</AMOUNT></BILLALLOCATIONS.LIST>"
                         % (_x(bill), kind, tally_amt))
            centre = ""
            if v["centre"] and books.ledgers.get(ledger, ("", False))[1]:
                centre = ("<CATEGORYALLOCATIONS.LIST><CATEGORY>%s</CATEGORY><ISDEEMEDPOSITIVE>%s</ISDEEMEDPOSITIVE>"
                          "<COSTCENTREALLOCATIONS.LIST><NAME>%s</NAME><AMOUNT>%s</AMOUNT></COSTCENTREALLOCATIONS.LIST>"
                          "</CATEGORYALLOCATIONS.LIST>" % (COST_CATEGORY, "Yes" if amt > 0 else "No", _x(v["centre"]), tally_amt))
            rows.append("<ALLLEDGERENTRIES.LIST><LEDGERNAME>%s</LEDGERNAME><ISDEEMEDPOSITIVE>%s</ISDEEMEDPOSITIVE>"
                        "<AMOUNT>%s</AMOUNT>%s%s</ALLLEDGERENTRIES.LIST>"
                        % (_x(ledger), "Yes" if amt > 0 else "No", tally_amt, alloc, centre))
        msgs.append('<TALLYMESSAGE xmlns:UDF="TallyUDF"><VOUCHER REMOTEID=%s VCHTYPE=%s ACTION="Create">'
                    "<DATE>%s</DATE><VOUCHERTYPENAME>%s</VOUCHERTYPENAME><VOUCHERNUMBER>%s</VOUCHERNUMBER>"
                    "<NARRATION>%s</NARRATION>%s</VOUCHER></TALLYMESSAGE>\n"
                    % (quoteattr(v["remote"]), quoteattr(v["type"]), _tdate(v["date"]), _x(v["type"]), _x(v["number"]),
                       _x(v["narration"])[:500], "".join(rows)))
    return _envelope("Vouchers", company, msgs)
