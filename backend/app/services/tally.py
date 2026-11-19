"""The books, for Tally.

The ERP does the accounts office's day; the company's books - the trial balance, the P&L, the balance sheet the
auditor signs - are kept in Tally by the CA. This writes what happened in a period as Tally Prime reads it: an XML of
masters (the ledgers and the projects as cost centres) and an XML of vouchers, imported in that order through Gateway
of Tally > Import > Masters, then Transactions.

What goes across
    Receipts and payments (against a bill, on account), expense vouchers and sundry receipts, transfers between our own
    accounts (contra), client RA bills (sales, with output GST, TDS deducted by the client, retention held and advance
    recovered), tax invoices (sales), supplier bills (purchases with input GST, split CGST/SGST or IGST by the
    supplier's state; a bill still waiting for approval is left out), contractor RA bills (a journal: their work and its
    GST against what is owed them, the TDS and labour cess we deduct, retention we hold and advance we recover), credit
    notes (to a client, a Credit Note; from a contractor's bill, a Debit Note), and the fixed assets' depreciation for
    each closed year and their sale (journals), retention released (a journal moving it from the retention ledger to
    the party), and the payroll of each approved month (a journal, then a payment when the month is paid). Every line of
    income or cost carries its project as a cost centre, so Tally can show each site's P&L too.

    An asset's purchase is not sent: it reaches Tally through the supplier's bill, which is not linked to the asset,
    and a second voucher would double it. The CA books that bill to the asset's ledger.

Voided entries
    An entry voided before any export took it is simply left out. One voided after an export took it goes across as a
    cancellation of the voucher already in Tally (ACTION="Cancel", found by its voucher number), so the books there
    follow.

How the sums are kept honest
    A bill's own deductions are each put on their own ledger; whatever else came off it - back-charges, debit notes,
    LD, material recovered - is one line, worked out as what makes the voucher balance to the rupee, so a voucher that
    Tally refuses for not balancing cannot be written. Each voucher carries a REMOTEID and GUID made from our own
    record's id, so the same one imported twice is recognised by Tally rather than doubled.

The ledger names are the company's to set (Settings, Tally), to match the ledgers already in their Tally company.
"""
import json
import re
from xml.sax.saxutils import escape, quoteattr

from app import models
from app.constants.money import LOAN_INTEREST_HEAD as INTEREST_HEAD
from app.core.currency import money
from app.core.gst import GST_STATES, our_state, state_from_gstin, supply_state_for_job
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
    "fixed_assets": ("Fixed Assets", "Fixed Assets", False),
    "depreciation": ("Depreciation", "Indirect Expenses", False),
    "asset_sale_gain": ("Profit or Loss on Sale of Fixed Assets", "Indirect Incomes", False),
    "asset_sale_proceeds": ("Fixed Assets Sold - Proceeds Receivable", "Current Assets", False),
    "subcontract": ("Subcontract Charges", "Direct Expenses", True),
    "tds_payable": ("TDS Payable - Contractors", "Duties & Taxes", False),
    "labour_cess": ("Labour Cess Payable", "Duties & Taxes", False),
    "retention_payable": ("Retention Money Payable", "Current Liabilities", False),
    "contractor_advance": ("Mobilisation Advance to Contractors", "Loans & Advances (Asset)", False),
    "contractor_recoveries": ("Recoveries from Contractors", "Direct Incomes", True),
    "salaries": ("Salaries & Wages", "Indirect Expenses", False),
    "employer_contribution": ("Employer PF & ESI", "Indirect Expenses", False),
    "salaries_payable": ("Salaries Payable", "Current Liabilities", False),
    "salary_tds": ("TDS Payable - Salaries", "Duties & Taxes", False),
    "pf_payable": ("PF Payable", "Current Liabilities", False),
    "esi_payable": ("ESI Payable", "Current Liabilities", False),
    "pt_payable": ("Professional Tax Payable", "Duties & Taxes", False),
    "salary_deductions": ("Other Salary Deductions", "Current Liabilities", False),
    "unassigned_bank": ("Bank (account not recorded)", "Bank Accounts", False),
    "cash": ("Cash", "Cash-in-Hand", False),
    "inter_site_material": ("Material Transferred Between Sites", "Direct Expenses", True),
    "opening_balances": ("Opening Balance Adjustment", "Suspense A/c", False),
    "suspense": ("Suspense A/c", "Suspense A/c", False),
}
LABELS = {
    "sales": "Work billed to clients (RA bills)", "output_cgst": "Output CGST", "output_sgst": "Output SGST",
    "output_igst": "Output IGST", "tds_receivable": "TDS deducted by clients", "retention_receivable": "Retention held by clients",
    "client_advance": "Mobilisation advance from clients", "client_deductions": "Other deductions by clients",
    "purchases": "Supplier bills", "input_gst": "GST on supplier bills (supplier's state not known)",
    "input_cgst": "Input CGST", "input_sgst": "Input SGST", "input_igst": "Input IGST", "subcontract": "Contractors' work",
    "tds_payable": "TDS deducted from contractors", "labour_cess": "Labour cess deducted", "retention_payable": "Retention held from contractors",
    "contractor_advance": "Mobilisation advance to contractors", "contractor_recoveries": "Other recoveries from contractors",
    "unassigned_bank": "Payments with no bank account recorded", "cash": "Cash paid with no cash box recorded",
    "fixed_assets": "Fixed assets (book value)", "depreciation": "Depreciation on fixed assets",
    "asset_sale_gain": "Profit or loss on selling an asset", "asset_sale_proceeds": "What a sold asset fetched",
    "salaries": "Salaries (gross)", "employer_contribution": "Employer's PF and ESI", "salaries_payable": "Net salaries owed",
    "salary_tds": "TDS on salaries", "pf_payable": "PF owed", "esi_payable": "ESI owed", "pt_payable": "Professional tax owed",
    "salary_deductions": "Other deductions from salaries",
    "inter_site_material": "Material moved from one site to another",
    "opening_balances": "The other side of parties' opening balances",
    "suspense": "The difference of a journal whose debit and credit are not equal",
}
# GST ledgers carry their duty head in Tally, so its GST reports pick them up.
GST_HEADS = {"output_cgst": "Central Tax", "output_sgst": "State Tax", "output_igst": "Integrated Tax",
             "input_cgst": "Central Tax", "input_sgst": "State Tax", "input_igst": "Integrated Tax", "input_gst": ""}
# Heads that are the site's own cost (Direct Expenses in Tally); the rest are overheads.
DIRECT_HEADS = {"Site expenses", "Diesel & fuel", "Machinery hire", "Transport & freight", "Repairs & maintenance"}
PARTY_GROUP = {"client": "Sundry Debtors", "supplier": "Sundry Creditors", "contractor": "Sundry Creditors", "staff": "Loans & Advances (Asset)", "other": "Sundry Creditors"}
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


def export_windows(db, client_id):
    """Every earlier export of vouchers: (when, period from, period to). An export is the XML the ERP wrote for a period; it is recorded when the
    file is made, so this says what was put in a file, not what Tally did with it (a file import gives nothing back)."""
    out = []
    for at, details in db.query(models.DBAuditLog.created_at, models.DBAuditLog.details).filter(
            models.DBAuditLog.client_id == client_id, models.DBAuditLog.action == "tally_export",
            models.DBAuditLog.entity_name == "vouchers").all():
        m = re.search(r"(\S+) to (\S+)\s*$", details or "")
        f, t = (m.group(1), m.group(2)) if m else ("start", "today")
        at = at or ""
        out.append((at, "0000-00-00" if f == "start" else f, at[:10] if t == "today" else t))
    return out


def cross_charge_exports(db, client_id, charges):
    """{cross-charge id: {"original", "reversal", "error"}} - where each journal of a cross-charge stands in the exports made so far.
    original: NOT_ADJUSTED | PENDING_EXPORT | EXPORTED. reversal: NONE | NEEDS_DATE | INVALID_DATE | PENDING_EXPORT | EXPORTED.
    EXPORTED means an export file made after the journal existed covered its date; the voucher carries its own id, so an export made again
    gives Tally the same voucher to recognise, not a second one. A journal that cannot be exported says why in `error`."""
    windows = export_windows(db, client_id)
    ids = [c.id for c in charges]
    adjusted_at = {}
    for eid, at in db.query(models.DBAuditLog.entity_id, models.DBAuditLog.created_at).filter(
            models.DBAuditLog.client_id == client_id, models.DBAuditLog.action == "store_cross_charge_adjusted", models.DBAuditLog.entity_id.in_(ids or [0])).all():
        adjusted_at[eid] = min(adjusted_at.get(eid, at or ""), at or "")

    def taken(on, since):
        # Times are kept to the second, so an export in the very second a journal came to be is not taken to have held it: when unsure, pending.
        return any(at > since and f <= on <= t for at, f, t in windows)
    out = {}
    for c in charges:
        adj = c.adjusted_on.isoformat() if c.adjusted_on else ""
        state = {"original": "NOT_ADJUSTED", "reversal": "NONE", "error": ""}
        if adj:
            state["original"] = "EXPORTED" if taken(adj, adjusted_at.get(c.id) or adj) else "PENDING_EXPORT"
        reversed_ = bool(adj) and (c.status == "REVERSE" or (c.status == "VOID" and c.reversed_on is not None))
        if reversed_:
            if c.reversed_on is None:
                state["reversal"], state["error"] = "NEEDS_DATE", "This adjustment was reversed before the reversal date was kept. Give the date it was reversed, so its reversing journal can be sent to Tally."
            elif c.reversed_on.date().isoformat() < adj:
                state["reversal"], state["error"] = "INVALID_DATE", "The reversal is dated before the adjustment (%s), so its reversing journal is not sent." % adj
            else:
                on = c.reversed_on.date().isoformat()
                state["reversal"] = "EXPORTED" if taken(on, c.reversed_on.strftime("%Y-%m-%d %H:%M:%S")) else "PENDING_EXPORT"
        out[c.id] = state
    return out


class Books:
    """The period's vouchers, as balanced lists of ledger lines, and every ledger and cost centre they name."""

    def __init__(self, db, client, date_from, date_to):
        self.db, self.client, self.date_from, self.date_to = db, client, date_from or "0000-00-00", date_to or "9999-12-31"
        self.names = ledger_names(db, client.id)
        self.vouchers = []
        self.ledgers = {}               # name -> (group, takes cost centre)
        self.gst_ledgers = {}           # name -> GST duty head ("" for an unsplit GST ledger)
        self.party_info = {}            # name -> {"gstin", "state"}
        self.cost_centres = set()
        self.warnings = []
        self.our_state = our_state(db, client.id)
        self.jobs = {j.id: j for j in db.query(models.DBJob).filter(models.DBJob.client_id == client.id).all()}
        self.accounts = {a.id: a for a in db.query(models.DBBankAccount).filter(models.DBBankAccount.client_id == client.id).all()}
        self.contractors = {c.id: c for c in db.query(models.DBContractor).filter(models.DBContractor.client_id == client.id).all()}
        self._money()
        self._client_bills()
        self._invoices()
        self._supplier_bills()
        self._contractor_bills()
        self._credit_notes()
        self._fixed_assets()
        self._retention_releases()
        self._payroll()
        self._journals()
        self._debit_notes()
        self._cross_charges()
        self._claims()
        self._party_openings()
        self._loans()
        self.vouchers.sort(key=lambda v: (v["date"], v["type"], v["number"]))

    # --- naming ---
    def std(self, key):
        name = self.names[key]
        _, group, cc = LEDGERS[key]
        self.ledgers.setdefault(name, (group, cc))
        if key in GST_HEADS:
            self.gst_ledgers.setdefault(name, GST_HEADS[key])
        return name

    def party(self, name, kind, gstin="", state=""):
        name = (name or "").strip() or "Unnamed party"
        self.ledgers.setdefault(name, (PARTY_GROUP.get(kind, "Sundry Creditors"), False))
        gstin = (gstin or "").strip().upper()
        code = (state or "").strip() or state_from_gstin(gstin)
        if gstin or code:
            info = self.party_info.setdefault(name, {"gstin": "", "state": ""})
            info["gstin"] = info["gstin"] or gstin
            info["state"] = info["state"] or GST_STATES.get(code, "")
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

    def loan_ledger(self, loan):
        """The loan's own ledger, under Secured Loans or Unsecured Loans."""
        from app.services.loans import ledger_group, ledger_name
        name = ledger_name(loan)
        self.ledgers.setdefault(name, (ledger_group(loan), False))
        return name

    def _loan_rows(self):
        if not hasattr(self, "_loan_cache"):
            from app.models.loans import DBLoan, DBLoanInstalment
            self._loan_cache = ({l.id: l for l in self.db.query(DBLoan).filter(DBLoan.client_id == self.client.id).all()},
                                {i.id: i for i in self.db.query(DBLoanInstalment).filter(DBLoanInstalment.client_id == self.client.id).all()})
        return self._loan_cache

    def centre(self, job_id):
        j = self.jobs.get(job_id)
        if j is None:
            return ""
        name = ("%s %s" % (j.number or "", j.name or "")).strip()[:100]
        self.cost_centres.add(name)
        return name

    def add(self, vtype, number, on, narration, lines, remote, job_id=None):
        """lines: [(ledger, amount, bill_ref, ref_type, cost centre)], amount positive for a debit, negative for a credit; a
        line's own cost centre (a journal moving cost between sites) over the voucher's project."""
        lines = [(l, money(a), *rest) for l, a, *rest in lines if abs(money(a)) >= 0.005]
        total = money(sum(a for _, a, *_ in lines))
        if abs(total) >= 0.01:            # cannot happen by construction; refused rather than written wrong
            self.warnings.append("%s %s did not balance by %s and was left out." % (vtype, number, total))
            return
        self.vouchers.append({"type": vtype, "number": number, "date": on[:10], "narration": narration,
                              "lines": lines, "remote": remote, "centre": self.centre(job_id), "action": "Create"})

    def cancel(self, vtype, number, on, narration, remote):
        """A voucher already sent to Tally, cancelled there: found by its type, date and number."""
        self.vouchers.append({"type": vtype, "number": number, "date": on[:10], "narration": narration,
                              "lines": [], "remote": remote, "centre": "", "action": "Cancel"})

    # --- what has already gone across ---
    def _exports(self):
        """Every earlier export of vouchers: (when, period from, period to)."""
        if not hasattr(self, "_export_log"):
            self._export_log = export_windows(self.db, self.client.id)
        return self._export_log

    def _voided_at(self, numbers):
        rows = [at for (at,) in self.db.query(models.DBAuditLog.created_at).filter(
            models.DBAuditLog.client_id == self.client.id, models.DBAuditLog.action == "money_voided",
            models.DBAuditLog.entity_name.in_([n for n in numbers if n])).all() if at]
        return min(rows) if rows else "9999-12-31 23:59:59"

    def was_exported(self, e, numbers):
        """Did an export of vouchers take this entry before it was voided?"""
        if not self._exports():
            return False
        gone = self._voided_at(numbers)
        made = e.created_at or ""
        return any(made <= at < gone and f <= (e.paid_on or "")[:10] <= t for at, f, t in self._exports())

    # --- what goes across ---
    def _money(self):
        legs = {e.id: e for e in self.db.query(models.DBMoneyEntry).filter(
            models.DBMoneyEntry.client_id == self.client.id, models.DBMoneyEntry.doc_type == "contra").all()}
        q = self.db.query(models.DBMoneyEntry).filter(
            models.DBMoneyEntry.client_id == self.client.id,
            models.DBMoneyEntry.paid_on >= self.date_from, models.DBMoneyEntry.paid_on <= self.date_to)
        for e in q.order_by(models.DBMoneyEntry.paid_on, models.DBMoneyEntry.id).all():
            remote = "yerp-%d-money-%d" % (self.client.id, e.id)
            if e.voided:
                if e.doc_type == "contra" and e.direction != "OUT":
                    continue
                other = legs.get(e.pair_id) if e.doc_type == "contra" else None
                if self.was_exported(e, [e.number, other.number if other else ""]):
                    vtype = ("Contra" if e.doc_type == "contra" else "Receipt" if e.direction == "IN" else "Payment")
                    self.cancel(vtype, e.number, e.paid_on, "Voided: %s" % (e.void_reason or ""), remote)
                continue
            amt = money(e.amount)
            here = self.account(e.account_id, e.mode)
            ref = " (%s %s)" % (e.mode, e.reference) if e.reference else (" (%s)" % e.mode if e.mode else "")
            if e.doc_type == "contra":
                if e.direction != "OUT":
                    continue                                  # one voucher for the two entries
                other = legs.get(e.pair_id)
                there = self.account(other.account_id if other else None, e.mode)
                self.add("Contra", e.number, e.paid_on, "Transfer%s%s" % (ref, (". " + e.note) if e.note else ""),
                         [(there, amt), (here, -amt)], remote)
                continue
            if e.doc_type in ("loan_instalment", "loan_disbursal"):
                loans, instalments = self._loan_rows()
                inst = instalments.get(e.doc_id) if e.doc_type == "loan_instalment" else None
                loan = loans.get(inst.loan_id if inst else e.doc_id)
                if loan is None:
                    self.warnings.append("%s was paid against a loan that is no longer on the books and was left out." % e.number)
                    continue
                if inst is None:           # the money received: the bank on one side, the loan on the other
                    self.add("Receipt", e.number, e.paid_on, "Loan received - %s%s" % (loan.lender, ref), [(here, amt), (self.loan_ledger(loan), -amt)], remote)
                else:                      # an EMI leaves the bank whole, and is split in the books: principal to the loan, the rest is interest
                    principal = min(amt, money(inst.principal))
                    self.add("Payment", e.number, e.paid_on, "EMI %s - %s%s" % (inst.number, loan.lender, ref),
                             [(self.loan_ledger(loan), principal), (self.head(INTEREST_HEAD), money(amt - principal)), (here, -amt)], remote)
                continue
            if e.doc_type in ("expense", "income"):
                ledger = self.head(e.head, income=e.doc_type == "income")
                to = (" To %s A/c %s IFSC %s." % (e.payee_bank or "bank", e.payee_account or "-", e.payee_ifsc or "-")) if (e.payee_account or e.payee_ifsc or e.payee_bank) else ""
                say = "%s - %s%s%s%s" % (e.head, e.party_name or "", ref, to, (". " + e.note) if e.note else "")
            else:
                # A mobilisation advance goes to its own ledger: that is the one the RA bills take it back from.
                ledger = self.std("contractor_advance") if e.doc_type == "sub_advance" else self.party(e.party_name, e.party_type)
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
        suppliers = {}
        for sup in self.db.query(models.DBSupplier).filter(models.DBSupplier.client_id == self.client.id).all():
            suppliers.setdefault((sup.name or "").strip().lower(), sup)
        q = self.db.query(models.DBBill).filter(models.DBBill.client_id == self.client.id)
        for b in q.all():
            if (b.status or "") in ("Draft", "Cancelled", "Rejected", "Awaiting Approval") \
                    or (b.approval_status or "none") in ("rejected", "pending"):
                continue                                   # not the company's debt until it is approved
            on = (b.issue_date or b.created_at or "")[:10]
            if not (self.date_from <= on <= self.date_to):
                continue
            total = money(b.total or b.amount or 0)
            tax = money(b.tax_amount or 0)
            sup = suppliers.get((b.vendor_name or "").strip().lower())
            gstin = (sup.gstin or "") if sup else ""
            theirs = ((sup.state_code or "").strip() if sup else "") or state_from_gstin(gstin)
            party = self.party(b.vendor_name, "supplier", gstin, theirs)
            if theirs and self.our_state and tax:
                if theirs == self.our_state:
                    half = money(tax / 2.0)
                    gst = [(self.std("input_cgst"), half), (self.std("input_sgst"), money(tax - half))]
                else:
                    gst = [(self.std("input_igst"), tax)]
            else:
                gst = [(self.std("input_gst"), tax)]       # whose state it is is not known: left for the CA to split
            self.add("Purchase", b.number or "Bill %d" % b.id, on,
                     "Bill %s from %s%s" % (b.number or "", b.vendor_name or "", (" - " + b.notes) if b.notes else ""),
                     [(self.std("purchases"), money(total - tax))] + gst + [(party, -total, b.number or "", "New Ref")],
                     "yerp-%d-bill-%d" % (self.client.id, b.id), b.job_id)

    def _invoices(self):
        """Tax invoices raised outside the RA bills: sales, with output GST split by where the work is."""
        from app.core.currency import compute_invoice_totals
        q = self.db.query(models.DBInvoice).filter(models.DBInvoice.client_id == self.client.id)
        for inv in q.all():
            if (inv.status or "Draft") in ("Draft", "Void") or (inv.approval_status or "none") in ("pending", "rejected"):
                continue
            on = (inv.issue_date or "")[:10]
            if not (self.date_from <= on <= self.date_to):
                continue
            taxable, tax, total = compute_invoice_totals(inv.line_items, inv.tax_type)
            if total <= 0:
                continue
            party = self.party(inv.to_contact, "client")
            where = supply_state_for_job(self.db, inv.job_id)
            if where and self.our_state and where == self.our_state:
                half = money(tax / 2.0)
                gst = [(self.std("output_cgst"), -half), (self.std("output_sgst"), -money(tax - half))]
            else:
                gst = [(self.std("output_igst"), -tax)]
            self.add("Sales", inv.number or "Invoice %d" % inv.id, on,
                     "Invoice %s to %s" % (inv.number or "", inv.to_contact or ""),
                     [(party, total, inv.number or "", "New Ref"), (self.std("sales"), -taxable)] + gst,
                     "yerp-%d-invoice-%d" % (self.client.id, inv.id), inv.job_id)

    def _contractor_bills(self):
        contractors = self.contractors
        q = self.db.query(models.DBSubBill).filter(models.DBSubBill.client_id == self.client.id,
                                                   models.DBSubBill.status.in_(("CERTIFIED", "PAID")))
        for b in q.all():
            on = (b.certified_at or b.bill_date or b.created_at or "")[:10]
            if not (self.date_from <= on <= self.date_to):
                continue
            con = contractors.get(b.contractor_id)
            party = self.party(con.company_name if con else "", "contractor", con.gst_number if con else "")
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

    def _credit_notes(self):
        """Work taken back off a certified bill. To a client it is a Credit Note against our sale; on a contractor's
        bill it is a Debit Note against what we owe them. Each undoes its bill's lines."""
        ra = {b.id: b for b in self.db.query(models.DBRABill).filter(models.DBRABill.client_id == self.client.id).all()}
        sub = {b.id: b for b in self.db.query(models.DBSubBill).filter(models.DBSubBill.client_id == self.client.id).all()}
        for n in self.db.query(models.DBCreditNote).filter(models.DBCreditNote.client_id == self.client.id,
                                                           models.DBCreditNote.status == "ISSUED").all():
            on = (n.note_date or n.created_at or "")[:10]
            if not (self.date_from <= on <= self.date_to):
                continue
            taxable, net = money(n.taxable), money(n.net_amount)
            cgst, sgst, igst = money(n.cgst_amount), money(n.sgst_amount), money(n.igst_amount)
            ret, tds, cess = money(n.retention_amount), money(n.tds_amount), money(n.cess_amount)
            remote = "yerp-%d-creditnote-%d" % (self.client.id, n.id)
            why = (" - " + n.reason) if n.reason else ""
            if (n.side or "client") == "client":
                bill = ra.get(n.ra_bill_id)
                job = self.jobs.get(n.job_id)
                party = self.party(job.customer_name if job else "", "client")
                other = money(taxable + cgst + sgst + igst - net - ret - tds)
                lines = [(self.std("sales"), taxable), (self.std("output_cgst"), cgst), (self.std("output_sgst"), sgst),
                         (self.std("output_igst"), igst), (party, -net, bill.number if bill else n.number, "Agst Ref"),
                         (self.std("tds_receivable"), -tds), (self.std("retention_receivable"), -ret),
                         (self.std("client_deductions"), -other)]
                self.add("Credit Note", n.number, on, "Credit note %s%s" % (n.number, why), lines, remote, n.job_id)
            else:
                bill = sub.get(n.sub_bill_id)
                con = self.contractors.get(n.contractor_id)
                party = self.party(con.company_name if con else "", "contractor", con.gst_number if con else "")
                other = money(taxable + cgst + sgst + igst - net - ret - tds - cess)
                lines = [(self.std("subcontract"), -taxable), (self.std("input_cgst"), -cgst), (self.std("input_sgst"), -sgst),
                         (self.std("input_igst"), -igst), (party, net, bill.number if bill else n.number, "Agst Ref"),
                         (self.std("tds_payable"), tds), (self.std("labour_cess"), cess),
                         (self.std("retention_payable"), ret), (self.std("contractor_recoveries"), other)]
                self.add("Debit Note", n.number, on, "Debit note %s on the contractor's bill%s" % (n.number, why), lines,
                         remote, n.job_id)

    def _journals(self):
        """Journal vouchers the Master has approved, line by line, each line under its own project."""
        from app.constants.money import INCOME_HEADS
        from app.services.journals import DBJournal, lines_of
        js = [j for j in self.db.query(DBJournal).filter(DBJournal.client_id == self.client.id, DBJournal.status == "APPROVED").all()
              if self.date_from <= (j.voucher_date or "")[:10] <= self.date_to]
        lines = lines_of(self.db, [j.id for j in js])
        for j in js:
            out = []
            for l in lines.get(j.id, []):
                if l.kind == "party":
                    ledger = self.party(l.party_name, l.party_type)
                elif l.kind == "head":
                    ledger = self.head(l.head, income=l.head in INCOME_HEADS)
                elif l.kind == "account":
                    ledger = self.account(l.account_id, "")
                else:
                    ledger = self.std(l.ledger_key)
                out.append((ledger, money((l.debit or 0) - (l.credit or 0)), "", "", self.centre(l.job_id)))
            # Tally refuses a voucher that does not balance, and a journal that is out is not left out of the export for that: the
            # difference goes to Suspense A/c, so the voucher is sent whole and the books stay balanced until someone clears it.
            narration = j.narration
            off = money(sum(a for _, a, *_ in out))
            if abs(off) >= 0.005:
                out.append((self.std("suspense"), -off, "", "", ""))
                narration = "%s [Debit and credit differ by %s; the difference is posted to Suspense A/c]" % (j.narration, "{:,.2f}".format(abs(off)))
                self.warnings.append("%s: debit and credit differ by %s. The difference is posted to Suspense A/c in Tally; clear it there once the journal is put right." % (
                    j.number, "{:,.2f}".format(abs(off))))
            self.add("Journal", j.number, j.voucher_date, narration, out, "yerp-%d-journal-%d" % (self.client.id, j.id))

    def _debit_notes(self):
        """Debit notes to suppliers: what we owe them comes down, and so do the purchases and the input GST."""
        from app.services.journals import DBSupplierDebitNote
        bills = {b.id: b for b in self.db.query(models.DBBill).filter(models.DBBill.client_id == self.client.id).all()}
        suppliers = {}
        for sup in self.db.query(models.DBSupplier).filter(models.DBSupplier.client_id == self.client.id).all():
            suppliers.setdefault((sup.name or "").strip().lower(), sup)
        for n in self.db.query(DBSupplierDebitNote).filter(DBSupplierDebitNote.client_id == self.client.id,
                                                           DBSupplierDebitNote.status == "ISSUED").all():
            if not (self.date_from <= (n.note_date or "")[:10] <= self.date_to):
                continue
            sup = suppliers.get((n.supplier_name or "").strip().lower())
            gstin = (sup.gstin or "") if sup else ""
            theirs = ((sup.state_code or "").strip() if sup else "") or state_from_gstin(gstin)
            party = self.party(n.supplier_name, "supplier", gstin, theirs)
            tax, total = money(n.tax), money(n.total)
            if theirs and self.our_state and tax:
                if theirs == self.our_state:
                    half = money(tax / 2.0)
                    gst = [(self.std("input_cgst"), -half), (self.std("input_sgst"), -money(tax - half))]
                else:
                    gst = [(self.std("input_igst"), -tax)]
            else:
                gst = [(self.std("input_gst"), -tax)]
            bill = bills.get(n.bill_id)
            ref = [(party, total, bill.number or "", "Agst Ref")] if bill and bill.number else [(party, total)]
            self.add("Debit Note", n.number, n.note_date, "Debit note %s to %s - %s" % (n.number, n.supplier_name, n.reason),
                     ref + [(self.std("purchases"), -money(n.taxable))] + gst, "yerp-%d-debitnote-%d" % (self.client.id, n.id), n.job_id)

    def _cross_charges(self):
        """Material one site's store sent another's, once accounts have adjusted it: the cost moves from the sending
        project's cost centre to the receiving one's. An adjustment that was reversed (the transfer was cancelled afterwards) keeps that
        journal, dated the day it was adjusted, and adds its exact opposite, dated the day it was reversed and with a voucher identity of its own -
        so Tally holds both, nets to nothing, and an export made again gives it the same two vouchers to recognise, not more."""
        from app.core.config import logger
        from app.models.store_control import DBStoreTransfer
        from app.models.store_extras import DBStoreCrossCharge
        for c, t in (self.db.query(DBStoreCrossCharge, DBStoreTransfer).join(DBStoreTransfer, DBStoreTransfer.id == DBStoreCrossCharge.transfer_id)
                     .filter(DBStoreCrossCharge.client_id == self.client.id, DBStoreCrossCharge.status.in_(("ADJUSTED", "REVERSE", "VOID")),
                             DBStoreCrossCharge.adjusted_on.isnot(None)).order_by(DBStoreCrossCharge.id).all()):
            status, reversed_on = c.status, c.reversed_on
            if status == "ADJUSTED" and not (t.status == "POSTED" and t.receipt_status == "RECEIVED"):
                # Its transfer was cancelled and nobody has opened the accounts list since, which is where the row is brought up to date: seen
                # as the reversal it is, dated when the transfer was cancelled. Read here, not written - an export changes nothing.
                from app.services.store_accounts import _cancelled_at
                status, reversed_on = "REVERSE", _cancelled_at(self.db, t.id, c)
            on = c.adjusted_on.isoformat() if c.adjusted_on else ""
            amt, ledger = money(float(c.amount or 0)), self.std("inter_site_material")
            frm, to = self.jobs.get(c.from_project_id), self.jobs.get(c.to_project_id)
            sent ="Material sent by transfer %s from %s to %s" % (t.number, frm.name if frm else "the central store", to.name if to else "the central store")
            number = "XC-%s" % t.number
            if on and self.date_from <= on <= self.date_to:
                self.add("Journal", number, on, sent,
                         [(ledger, amt, "", "", self.centre(c.to_project_id)), (ledger, -amt, "", "", self.centre(c.from_project_id))],
                         "yerp-%d-crosscharge-%d" % (self.client.id, c.id))
            if not (status == "REVERSE" or (status == "VOID" and reversed_on is not None)):
                continue
            # The reversing journal: dated the day the reversal happened - never the adjustment's day - and refused rather than guessed when that
            # day is not known or does not make sense.
            if reversed_on is None:
                why = "Cross-charge %s was reversed but has no reversal date, so its reversing journal was left out. Set the date under Store > Reports > For accounts > Between projects." % number
                self.warnings.append(why)
                logger.warning("Tally export: %s (cross-charge id %s)", why, c.id)
                continue
            back = reversed_on.date().isoformat()
            if back < on:
                why = "Cross-charge %s is reversed on %s, before it was adjusted on %s, so its reversing journal was left out." % (number, back, on)
                self.warnings.append(why)
                logger.warning("Tally export: %s (cross-charge id %s)", why, c.id)
                continue
            if self.date_from <= back <= self.date_to:
                # Every amount and ledger of the original, turned round: what was debited to the receiving project is credited to it again.
                self.add("Journal", "XCR-%s" % t.number, back, "Reversal of %s (adjusted %s): %s, transfer cancelled" % (number, on, sent.lower()),
                         [(ledger, amt, "", "", self.centre(c.from_project_id)), (ledger, -amt, "", "", self.centre(c.to_project_id))],
                         "yerp-%d-crosscharge-%d-reversal" % (self.client.id, c.id))

    def _party_openings(self):
        """A party's balance on the day the books begin, as a journal against one offset ledger: how a ledger's opening is
        carried into a new set of books. A client owing us, or a supplier we paid ahead, is a debit to the party; a client's
        advance, or a supplier we owe, a credit. The bill reference opens it in the party's bill-wise outstanding, where it
        is paid off like any bill."""
        from app.models.party_openings import DBPartyOpening
        from app.services.party_openings import number_of, wording
        for o in self.db.query(DBPartyOpening).filter(DBPartyOpening.client_id == self.client.id).order_by(DBPartyOpening.as_on, DBPartyOpening.id).all():
            if not (self.date_from <= o.as_on <= self.date_to):
                continue
            amt = money(o.amount)
            debit_party = (o.party_type == "client") == (o.side == "owed")
            ref = ("Opening balance", "New Ref") if o.side == "owed" else ("Opening advance", "Advance")
            party = self.party(o.party_name, o.party_type)
            offset = self.std("opening_balances")
            self.add("Journal", number_of(o), o.as_on, "Opening balance - %s: %s%s" % (o.party_name, wording(o.party_type, o.side), (". " + o.note) if o.note else ""),
                     [(party, amt if debit_party else -amt, *ref), (offset, -amt if debit_party else amt)],
                     "yerp-%d-opening-%d" % (self.client.id, o.id), o.job_id)

    def _loans(self):
        """A loan that was already running when these books began: what was left of it, as an opening journal against the one offset
        ledger. (A loan taken in these books has its money received as an ordinary receipt, and its instalments as payments.)"""
        from app.services.loans import ledger_name
        for loan in self._loan_rows()[0].values():
            if not loan.opening or not (self.date_from <= loan.taken_on <= self.date_to):
                continue
            amt = money(loan.principal)
            self.add("Journal", "%s/OPEN" % loan.number, loan.taken_on, "Opening balance of loan %s - %s" % (loan.number, ledger_name(loan)[7:]),
                     [(self.std("opening_balances"), amt), (self.loan_ledger(loan), -amt)], "yerp-%d-loanopen-%d" % (self.client.id, loan.id))

    def _claims(self):
        """Staff expense claims, once approved: the expense on its project, owed to the member of staff."""
        from app.services.payouts import DBExpenseClaim, LIVE_CLAIMS
        for c in self.db.query(DBExpenseClaim).filter(DBExpenseClaim.client_id == self.client.id, DBExpenseClaim.status.in_(LIVE_CLAIMS)).all():
            if not (self.date_from <= (c.spent_on or "")[:10] <= self.date_to):
                continue
            amt = money(c.amount)
            self.add("Journal", c.number, c.spent_on, "Expense claim %s - %s: %s" % (c.number, c.employee_name, (c.description or "")[:200]),
                     [(self.head(c.head), amt), (self.party(c.employee_name, "staff"), -amt, c.number, "New Ref")],
                     "yerp-%d-claim-%d" % (self.client.id, c.id), c.job_id)

    def _fixed_assets(self):
        """Each owned asset's depreciation for every financial year that has ended (booked on 31 March), and its sale.
        The year still running is booked when it closes."""
        from datetime import date
        from app.services.assets import book_schedule, fy_start_year
        today = date.today().isoformat()
        assets = {a.id: a for a in self.db.query(models.DBAsset).filter(models.DBAsset.client_id == self.client.id).all()}
        for b in self.db.query(models.DBAssetBook).filter(models.DBAssetBook.client_id == self.client.id).all():
            a = assets.get(b.asset_id)
            if a is None or (a.ownership or "Owned") != "Owned":
                continue
            label = ("%s %s" % (a.code or "", a.name or "")).strip()
            for row in book_schedule(b, fy_start_year(today)):
                y = int(row["fy"][:4])
                on = (b.disposed_on or "")[:10] if row["disposed"] else "%d-03-31" % (y + 1)
                if on > today or not (self.date_from <= on <= self.date_to):
                    continue
                dep = money(row["depreciation"])
                self.add("Journal", "DEP/%s/%s" % (row["fy"], a.code or a.id), on,
                         "Depreciation on %s for %s (%s)" % (label, row["fy"], b.method or "WDV"),
                         [(self.std("depreciation"), dep), (self.std("fixed_assets"), -dep)],
                         "yerp-%d-assetdep-%d-%d" % (self.client.id, b.id, y))
                if row["disposed"]:
                    value, book = money(row["disposal_value"]), money(row.get("book_value_at_sale", 0))
                    self.add("Journal", "SALE/%s" % (a.code or a.id), on,
                             "%s sold or scrapped for %s against a book value of %s%s" % (
                                 label, value, book, (" - " + b.disposal_note) if b.disposal_note else ""),
                             [(self.std("asset_sale_proceeds"), value), (self.std("fixed_assets"), -book),
                              (self.std("asset_sale_gain"), money(book - value))],
                             "yerp-%d-assetsale-%d" % (self.client.id, b.id))

    def _retention_releases(self):
        """Retention given back. Held on its own ledger since the bill, it moves to the party the day it is released: a
        claim on the client, or a sum owed to the contractor. Whatever else came off the release is one balancing line."""
        from app.services.subcontract_billing import release_party
        for r in self.db.query(models.DBRetentionRelease).filter(models.DBRetentionRelease.client_id == self.client.id,
                                                                 models.DBRetentionRelease.status.in_(("CERTIFIED", "PAID"))).all():
            on = (r.release_on or r.created_at or "")[:10]
            if not (self.date_from <= on <= self.date_to):
                continue
            party_type, name, _ = release_party(self.db, r)
            party = self.party(name, party_type)
            amount, net = money(r.amount), money(r.net_amount)
            cgst, sgst, igst = money(r.cgst_amount), money(r.sgst_amount), money(r.igst_amount)
            other = money(amount + cgst + sgst + igst - net)
            if (r.side or "client") == "client":
                lines = [(party, net, r.number, "New Ref"), (self.std("client_deductions"), other),
                         (self.std("retention_receivable"), -amount), (self.std("output_cgst"), -cgst),
                         (self.std("output_sgst"), -sgst), (self.std("output_igst"), -igst)]
            else:
                lines = [(self.std("retention_payable"), amount), (self.std("input_cgst"), cgst), (self.std("input_sgst"), sgst),
                         (self.std("input_igst"), igst), (party, -net, r.number, "New Ref"),
                         (self.std("contractor_recoveries"), -other)]
            self.add("Journal", r.number, on, "Retention released: %s%s" % (name, (" - " + r.stage) if r.stage else ""),
                     lines, "yerp-%d-retention-%d" % (self.client.id, r.id), r.job_id)

    def _payslips_by_month(self):
        from app.services.payroll_month import month_of
        out = {}
        for p in self.db.query(models.DBPayslip).filter(models.DBPayslip.client_id == self.client.id).all():
            out.setdefault(month_of(p.period_end, p.period_start, p.pay_date), []).append(p)
        out.pop("", None)
        return out

    def _payroll(self):
        """Each approved month as one journal on its last day: the gross and the employer's PF and ESI as cost, against
        what is owed to the staff, the tax office, PF and ESI. Once the month is paid, a payment clears what the staff
        were owed. Payroll keeps no bank account, so it goes across on the unrecorded bank ledger for the CA to point."""
        import calendar
        from app.services.payroll_month import RELEASED_MONTHS
        months = {m.month: m for m in self.db.query(models.DBPayrollMonth).filter(
            models.DBPayrollMonth.client_id == self.client.id, models.DBPayrollMonth.status.in_(RELEASED_MONTHS)).all()}
        for month, slips in sorted(self._payslips_by_month().items()):
            row = months.get(month)
            if row is None:
                continue

            def total(field):
                return money(sum(getattr(p, field) or 0 for p in slips))
            gross, net, tds, pt = total("gross_pay"), total("net_pay"), total("tax_amount"), total("professional_tax")
            pf, esi, er_pf, er_esi = total("retirement"), total("insurance"), total("employer_pf"), total("employer_esi")
            other = money(gross - net - tds - pt - pf - esi)
            year, mon = int(month[:4]), int(month[5:7])
            end = "%s-%02d" % (month, calendar.monthrange(year, mon)[1])
            if self.date_from <= end <= self.date_to:
                self.add("Journal", "PAY/%s" % month, end, "Payroll for %s: %d payslip%s" % (month, len(slips), "" if len(slips) == 1 else "s"),
                         [(self.std("salaries"), gross), (self.std("employer_contribution"), money(er_pf + er_esi)),
                          (self.std("salaries_payable"), -net), (self.std("salary_tds"), -tds), (self.std("pt_payable"), -pt),
                          (self.std("pf_payable"), -money(pf + er_pf)), (self.std("esi_payable"), -money(esi + er_esi)),
                          (self.std("salary_deductions"), -other)],
                         "yerp-%d-payroll-%s" % (self.client.id, month))
            paid = (row.paid_at or "")[:10]
            if paid and self.date_from <= paid <= self.date_to:
                self.add("Payment", "PAY/%s/PAID" % month, paid, "Salaries paid for %s" % month,
                         [(self.std("salaries_payable"), net), (self.std("unassigned_bank"), -net)],
                         "yerp-%d-payrollpaid-%s" % (self.client.id, month))

    def left_out(self):
        """What the company has recorded in the period that is not in this export, and why - so a short list of vouchers
        can be read for what it is. Nothing here is a voucher until the step named has been taken."""
        out = []

        def note(what, amounts, why, where):
            if amounts:
                out.append({"what": what, "count": len(amounts), "amount": money(sum(amounts)), "why": why, "where": where})

        def inside(on):
            return self.date_from <= (on or "")[:10] <= self.date_to
        c = self.client.id
        gone = ("CERTIFIED", "PAID", "CANCELLED", "REJECTED")
        note("Client RA bills", [b.this_bill or 0 for b in self.db.query(models.DBRABill).filter(
            models.DBRABill.client_id == c, models.DBRABill.status.notin_(gone)).all() if inside(b.created_at)],
            "Not certified yet. A bill goes across on the day it is certified.", "/clients/measurement")
        note("Contractor RA bills", [b.this_bill or 0 for b in self.db.query(models.DBSubBill).filter(
            models.DBSubBill.client_id == c, models.DBSubBill.status.notin_(gone)).all() if inside(b.bill_date or b.created_at)],
            "Not certified yet. A bill goes across on the day it is certified.", "/subcontractors/ra-bills")
        note("Supplier bills", [b.total or b.amount or 0 for b in self.db.query(models.DBBill).filter(models.DBBill.client_id == c).all()
                                if ((b.status or "") in ("Draft", "Awaiting Approval") or (b.approval_status or "none") == "pending")
                                and inside(b.issue_date or b.created_at)],
             "Still a draft or waiting for approval.", "/money/supplier-bills")
        note("Site cash spends", [x.amount or 0 for x in self.db.query(models.DBSiteCashExpense).filter(
            models.DBSiteCashExpense.client_id == c, models.DBSiteCashExpense.status == "SUBMITTED").all() if inside(x.spent_on)],
            "Waiting for accounts to check them against the bill.", "/money/expenses?tab=cash")
        from app.services.journals import DBJournal, lines_of
        pending = [j for j in self.db.query(DBJournal).filter(DBJournal.client_id == c, DBJournal.status == "PENDING").all() if inside(j.voucher_date)]
        pl = lines_of(self.db, [j.id for j in pending])
        note("Journal vouchers", [sum(l.debit or 0 for l in pl.get(j.id, [])) for j in pending],
             "Waiting for the Master to approve them.", "/money/adjustments")
        from app.services.payouts import DBExpenseClaim
        note("Staff expense claims", [x.amount or 0 for x in self.db.query(DBExpenseClaim).filter(
            DBExpenseClaim.client_id == c, DBExpenseClaim.status == "SUBMITTED").all() if inside(x.spent_on)],
            "Not approved yet.", "/money/expenses?tab=claims")
        from app.models.store_extras import DBStoreCrossCharge
        note("Material moved between sites", [float(x.amount or 0) for x in self.db.query(DBStoreCrossCharge).filter(
            DBStoreCrossCharge.client_id == c, DBStoreCrossCharge.status == "PENDING").all()],
            "Accounts have not marked the cross-charge adjusted in the store yet.", "/store/hub/reports/accounts")
        note("Payment requests", [r.amount or 0 for r in self.db.query(models.DBPaymentRequest).filter(
            models.DBPaymentRequest.client_id == c, models.DBPaymentRequest.status.in_(("PENDING", "AWAITING_MD", "APPROVED"))).all()
            if inside(r.requested_at)], "Not paid yet. A payment goes across when it is made.", "/money/approvals")
        from app.services.payroll_month import RELEASED_MONTHS
        released = {m for (m,) in self.db.query(models.DBPayrollMonth.month).filter(
            models.DBPayrollMonth.client_id == c, models.DBPayrollMonth.status.in_(RELEASED_MONTHS)).all()}
        note("Payslips", [p.gross_pay or 0 for month, slips in self._payslips_by_month().items() if month not in released
                          for p in slips if inside(month + "-28")],
             "Their month has not been approved in Payroll.", "/people/payroll")
        plant = [x.amount or 0 for x in self.db.query(models.DBPlantFuel).filter(models.DBPlantFuel.client_id == c).all() if inside(x.filled_at)]
        plant += [x.amount or 0 for x in self.db.query(models.DBPlantExpense).filter(models.DBPlantExpense.client_id == c).all()
                  if inside(x.spent_on)]
        plant += [x.amount or 0 for x in self.db.query(models.DBPlantRentalInvoice).filter(models.DBPlantRentalInvoice.client_id == c).all() if inside(x.invoice_date)]
        note("Plant fuel, hire and running costs", plant,
             "Project costs kept in the plant registers. Not sent: the supplier's bill for them is what goes across, so they are not counted twice.",
             "/projects/equipment")
        return out

    def rows(self):
        """Every voucher as the page lists it, oldest first."""
        return [{"date": v["date"], "type": v["type"], "number": v["number"], "narration": v["narration"], "project": v["centre"],
                 "amount": money(sum(a for _, a, *_ in v["lines"] if a > 0)), "cancelled": v.get("action") == "Cancel",
                 "lines": [{"ledger": l, "debit": a if a > 0 else 0, "credit": -a if a < 0 else 0} for l, a, *_ in v["lines"]]}
                for v in self.vouchers]

    def summary(self):
        by = {}
        for v in self.vouchers:
            kind = v["type"] if v.get("action") != "Cancel" else "%s (cancelled)" % v["type"]
            s = by.setdefault(kind, {"type": kind, "count": 0, "amount": 0.0})
            s["count"] += 1
            s["amount"] = money(s["amount"] + sum(a for _, a, *_ in v["lines"] if a > 0))
        return {"vouchers": sorted(by.values(), key=lambda s: s["type"]), "ledgers": len(self.ledgers),
                "cost_centres": len(self.cost_centres), "warnings": self.warnings, "left_out": self.left_out()}


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
        extra = ""
        if name in books.gst_ledgers:
            head = books.gst_ledgers[name]
            extra = "<TAXTYPE>GST</TAXTYPE>" + ("<GSTDUTYHEAD>%s</GSTDUTYHEAD>" % head if head else "")
        info = books.party_info.get(name)
        if info:
            if info["state"]:
                extra += "<LEDSTATENAME>%s</LEDSTATENAME><COUNTRYNAME>India</COUNTRYNAME>" % _x(info["state"])
            if info["gstin"]:
                extra += ("<GSTREGISTRATIONTYPE>Regular</GSTREGISTRATIONTYPE><PARTYGSTIN>%s</PARTYGSTIN>"
                          % _x(info["gstin"]))
            else:
                extra += "<GSTREGISTRATIONTYPE>Unregistered</GSTREGISTRATIONTYPE>"
        msgs.append('<TALLYMESSAGE xmlns:UDF="TallyUDF"><LEDGER NAME=%s ACTION="Create"><NAME.LIST><NAME>%s</NAME></NAME.LIST>'
                    '<PARENT>%s</PARENT><ISBILLWISEON>%s</ISBILLWISEON><ISCOSTCENTRESON>%s</ISCOSTCENTRESON>%s</LEDGER></TALLYMESSAGE>\n'
                    % (quoteattr(name), _x(name), _x(group), billwise, "Yes" if cc and books.cost_centres else "No", extra))
    return _envelope("All Masters", company, msgs)


def vouchers_xml(books, company=""):
    msgs = []
    for v in books.vouchers:
        if v.get("action") == "Cancel":
            # Tally finds the voucher to cancel by its date, type and number.
            msgs.append('<TALLYMESSAGE xmlns:UDF="TallyUDF"><VOUCHER REMOTEID=%s DATE=%s TAGNAME="Voucher Number" TAGVALUE=%s '
                        'VCHTYPE=%s ACTION="Cancel"><DATE>%s</DATE><GUID>%s</GUID><VOUCHERTYPENAME>%s</VOUCHERTYPENAME>'
                        "<VOUCHERNUMBER>%s</VOUCHERNUMBER><NARRATION>%s</NARRATION></VOUCHER></TALLYMESSAGE>\n"
                        % (quoteattr(v["remote"]), quoteattr(_tdate(v["date"])), quoteattr(v["number"]), quoteattr(v["type"]),
                           _tdate(v["date"]), _x(v["remote"]), _x(v["type"]), _x(v["number"]), _x(v["narration"][:500])))
            continue
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
            where = (line[4] if len(line) > 4 else "") or v["centre"]
            if where and books.ledgers.get(ledger, ("", False))[1]:
                centre = ("<CATEGORYALLOCATIONS.LIST><CATEGORY>%s</CATEGORY><ISDEEMEDPOSITIVE>%s</ISDEEMEDPOSITIVE>"
                          "<COSTCENTREALLOCATIONS.LIST><NAME>%s</NAME><AMOUNT>%s</AMOUNT></COSTCENTREALLOCATIONS.LIST>"
                          "</CATEGORYALLOCATIONS.LIST>" % (COST_CATEGORY, "Yes" if amt > 0 else "No", _x(where), tally_amt))
            rows.append("<ALLLEDGERENTRIES.LIST><LEDGERNAME>%s</LEDGERNAME><ISDEEMEDPOSITIVE>%s</ISDEEMEDPOSITIVE>"
                        "<AMOUNT>%s</AMOUNT>%s%s</ALLLEDGERENTRIES.LIST>"
                        % (_x(ledger), "Yes" if amt > 0 else "No", tally_amt, alloc, centre))
        msgs.append('<TALLYMESSAGE xmlns:UDF="TallyUDF"><VOUCHER REMOTEID=%s VCHTYPE=%s ACTION="Create">'
                    "<DATE>%s</DATE><GUID>%s</GUID><VOUCHERTYPENAME>%s</VOUCHERTYPENAME><VOUCHERNUMBER>%s</VOUCHERNUMBER>"
                    "<NARRATION>%s</NARRATION>%s</VOUCHER></TALLYMESSAGE>\n"
                    % (quoteattr(v["remote"]), quoteattr(v["type"]), _tdate(v["date"]), _x(v["remote"]), _x(v["type"]),
                       _x(v["number"]), _x(v["narration"][:500]), "".join(rows)))
    return _envelope("Vouchers", company, msgs)
