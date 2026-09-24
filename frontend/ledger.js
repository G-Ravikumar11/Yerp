/* ===========================================================================
   ledger.js - receipts, payments, party ledgers, the bank book, suppliers.

   One payment box, opened from wherever a bill is looked at - the RA bills,
   the gang's bills, the supplier bills, the money owed screen - so paying a
   bill is always the same three fields and never a trip to another screen.
   Part of a bill may be paid; the bill moves to paid on the last rupee.
   =========================================================================== */

var LEDGER = { tab: 'parties', accounts: [], suppliers: [], pay: null };

var LEDGER_KIND = { ra_bill: 'Receive against', sub_bill: 'Pay the gang for',
                    supplier_bill: 'Pay the supplier for' };

async function ledgerAccounts() {
    try {
        var d = await (await fetch('/api/bank-accounts', { credentials: 'include' })).json();
        LEDGER.accounts = d.accounts || [];
    } catch (e) { LEDGER.accounts = []; }
    return LEDGER.accounts;
}

function accountOptions(selected) {
    return '<option value="">Not recorded against an account</option>' +
        LEDGER.accounts.map(function (a) {
            return '<option value="' + a.id + '"' + (a.id === selected ? ' selected' : '') + '>' +
                esc(a.name) + ' (' + esc(a.kind) + ') &mdash; ' + formatCurrency(a.balance) + '</option>';
        }).join('');
}

/* --- The payment box ------------------------------------------------------ */

async function openPayBox(docType, docId, after) {
    await ledgerAccounts();
    var res = await fetch('/api/money/outstanding/' + docType + '/' + docId, { credentials: 'include' });
    var d = await res.json();
    if (!res.ok) { showToast(d.detail || 'Could not open that bill', 'error'); return; }
    if (d.outstanding <= 0) { showToast(d.number + ' is already settled in full.', 'success'); return; }
    LEDGER.pay = { doc_type: docType, doc_id: docId, after: after || null, outstanding: d.outstanding };
    document.getElementById('pay-title').textContent = (LEDGER_KIND[docType] || 'Settle') + ' ' + d.number;
    document.getElementById('pay-context').innerHTML =
        'Worth <strong>' + formatCurrency(d.worth) + '</strong> &middot; settled ' +
        formatCurrency(d.settled) + ' &middot; <strong>' + formatCurrency(d.outstanding) + ' left</strong>' +
        ((d.entries || []).length ? '<div style="margin-top:8px;font-size:0.76rem;">' +
            d.entries.map(function (e) {
                return '<div style="' + (e.voided ? 'text-decoration:line-through;opacity:.6;' : '') + '">' +
                    esc(e.paid_on) + ' &nbsp; ' + esc(e.number) + ' &nbsp; ' + formatCurrency(e.amount) +
                    ' &nbsp; ' + esc(e.mode) + (e.reference ? ' ' + esc(e.reference) : '') + '</div>';
            }).join('') + '</div>' : '');
    document.getElementById('pay-amount').value = d.outstanding;
    document.getElementById('pay-date').value = localDate(new Date());
    document.getElementById('pay-mode').value = 'Bank transfer';
    document.getElementById('pay-ref').value = '';
    document.getElementById('pay-note').value = '';
    document.getElementById('pay-account').innerHTML = accountOptions(
        LEDGER.accounts.length === 1 ? LEDGER.accounts[0].id : null);
    document.getElementById('pay-onaccount').style.display = 'none';
    openModal('pay-modal');
    document.getElementById('pay-amount').focus();
}
window.openPayBox = openPayBox;

async function openOnAccount(direction) {
    await ledgerAccounts();
    LEDGER.pay = { doc_type: 'on_account', direction: direction };
    document.getElementById('pay-title').textContent = direction === 'IN'
        ? 'Money received on account' : 'Advance or payment on account';
    document.getElementById('pay-context').innerHTML =
        'Against no bill yet. It sits in the party\'s ledger and the bank book until a bill arrives to set it against.';
    ['pay-amount', 'pay-ref', 'pay-note', 'pay-party'].forEach(function (id) {
        document.getElementById(id).value = ''; });
    document.getElementById('pay-date').value = localDate(new Date());
    document.getElementById('pay-account').innerHTML = accountOptions(
        LEDGER.accounts.length === 1 ? LEDGER.accounts[0].id : null);
    document.getElementById('pay-party-type').value = direction === 'IN' ? 'client' : 'supplier';
    document.getElementById('pay-onaccount').style.display = '';
    openModal('pay-modal');
    document.getElementById('pay-party').focus();
}
window.openOnAccount = openOnAccount;

function closePayBox() { closeModal('pay-modal'); }
window.closePayBox = closePayBox;

async function savePayment() {
    var p = LEDGER.pay || {};
    var val = function (id) { return document.getElementById(id).value; };
    var body = {
        doc_type: p.doc_type, doc_id: p.doc_id || null,
        amount: parseFloat(val('pay-amount')) || 0,
        paid_on: val('pay-date'), mode: val('pay-mode'), reference: val('pay-ref'),
        note: val('pay-note'), account_id: parseInt(val('pay-account')) || null,
    };
    if (p.doc_type === 'on_account') {
        body.direction = p.direction;
        body.party_type = val('pay-party-type');
        body.party_name = val('pay-party');
    }
    var res = await fetch('/api/money/entries', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not record it', 'error'); return; }
    closePayBox();
    showToast(out.message, 'success');
    if (p.after) p.after();
    if (document.getElementById('ledger-view') &&
        document.getElementById('ledger-view').style.display !== 'none') loadLedger();
}
window.savePayment = savePayment;

/* --- The screen ------------------------------------------------------------ */

function ledgerTab(tab) {
    LEDGER.tab = tab;
    document.querySelectorAll('#ledger-tabs button').forEach(function (b) {
        b.classList.toggle('active', b.dataset.tab === tab);
    });
    loadLedger();
}
window.ledgerTab = ledgerTab;

async function loadLedger() {
    var host = document.getElementById('ledger-body');
    if (!host) return;
    host.innerHTML = '<p style="padding:24px;text-align:center;color:var(--text-secondary);">Loading...</p>';
    if (LEDGER.tab === 'parties') return ledgerParties(host);
    if (LEDGER.tab === 'entries') return ledgerEntries(host);
    if (LEDGER.tab === 'bank') return ledgerBank(host);
    if (LEDGER.tab === 'suppliers') return ledgerSuppliers(host);
}
window.loadLedger = loadLedger;

var PARTY_LABEL = { client: 'Client', supplier: 'Supplier', contractor: 'Subcontractor', other: 'Other' };

async function ledgerParties(host) {
    var type = (document.getElementById('ledger-party-type') || {}).value || '';
    var d = await (await fetch('/api/ledger/parties' + (type ? '?party_type=' + type : ''),
                               { credentials: 'include' })).json();
    var s = d.summary || {};
    host.innerHTML =
        '<div class="stats-grid">' +
        statCard('Owed to us', formatCurrency(s.owed_to_us || 0)) +
        statCard('We owe', formatCurrency(s.we_owe || 0)) +
        statCard('Advances out', formatCurrency(s.advances_out || 0)) +
        statCard('Parties', String(s.parties || 0)) + '</div>' +
        '<div style="display:flex;gap:10px;align-items:center;margin:14px 0;flex-wrap:wrap;">' +
        '<select id="ledger-party-type" class="form-control" style="max-width:200px;" onchange="loadLedger()">' +
            '<option value="">Every party</option>' +
            ['client', 'supplier', 'contractor', 'other'].map(function (t) {
                return '<option value="' + t + '"' + (t === type ? ' selected' : '') + '>' +
                    PARTY_LABEL[t] + 's</option>'; }).join('') + '</select>' +
        '<button class="btn btn-outline btn-sm" onclick="openOnAccount(\'IN\')">+ Money in on account</button>' +
        '<button class="btn btn-outline btn-sm" onclick="openOnAccount(\'OUT\')">+ Advance / payment on account</button>' +
        '</div>' +
        '<div class="widget"><div class="table-responsive"><table class="data-table">' +
        '<thead><tr><th>Party</th><th>Type</th><th class="text-right">Billed ₹</th>' +
        '<th class="text-right">Received / paid ₹</th><th class="text-right">Balance ₹</th><th>Last</th><th></th></tr></thead><tbody>' +
        ((d.parties || []).length ? d.parties.map(function (p) {
            var owing = p.balance > 0, advance = p.balance < 0;
            var note = p.party_type === 'client'
                ? (owing ? 'they owe us' : advance ? 'paid ahead' : 'square')
                : (owing ? 'we owe them' : advance ? 'advance with them' : 'square');
            return '<tr><td style="font-weight:600;">' + esc(p.party) + '</td>' +
                '<td>' + esc(PARTY_LABEL[p.party_type] || p.party_type) + '</td>' +
                '<td class="text-right">' + formatCurrency(p.billed) + '</td>' +
                '<td class="text-right">' + formatCurrency(p.moved) + '</td>' +
                '<td class="text-right" style="font-weight:700;' +
                    (owing ? 'color:var(--warning-color);' : '') + '">' + formatCurrency(Math.abs(p.balance)) +
                    '<div style="font-size:0.68rem;font-weight:400;color:var(--text-secondary);">' + note + '</div></td>' +
                '<td>' + esc(p.last || '') + '</td>' +
                '<td class="text-right"><button class="btn btn-sm btn-outline" ' +
                    'onclick="openStatement(\'' + p.party_type + '\',' + JSON.stringify(p.party).replace(/"/g, '&quot;') + ')">' +
                    'Statement</button></td></tr>';
        }).join('') : '<tr><td colspan="7" style="text-align:center;padding:24px;color:var(--text-secondary);">' +
            'No bills and no money moved yet.</td></tr>') +
        '</tbody></table></div></div>';
}

async function ledgerEntries(host) {
    var d = await (await fetch('/api/money/entries', { credentials: 'include' })).json();
    var s = d.summary || {};
    host.innerHTML =
        '<div class="stats-grid">' +
        statCard('Received', formatCurrency(s.received || 0)) +
        statCard('Paid out', formatCurrency(s.paid || 0)) +
        statCard('Net', formatCurrency((s.received || 0) - (s.paid || 0))) +
        statCard('Entries', String(s.entries || 0)) + '</div>' +
        '<div class="widget" style="margin-top:14px;"><div class="table-responsive"><table class="data-table">' +
        '<thead><tr><th>Date</th><th>No.</th><th>Party</th><th>Against</th><th>Mode</th>' +
        '<th class="text-right">In ₹</th><th class="text-right">Out ₹</th><th></th></tr></thead><tbody>' +
        ((d.entries || []).length ? d.entries.map(function (e) {
            var strike = e.voided ? 'text-decoration:line-through;opacity:.55;' : '';
            return '<tr style="' + strike + '"><td>' + esc(e.paid_on) + '</td>' +
                '<td style="font-family:monospace;">' + esc(e.number) + '</td>' +
                '<td>' + esc(e.party_name) + '<div style="font-size:0.7rem;color:var(--text-secondary);">' +
                    esc(PARTY_LABEL[e.party_type] || '') + '</div></td>' +
                '<td>' + esc(e.doc_number || 'on account') + '</td>' +
                '<td>' + esc(e.mode) + (e.reference ? '<div style="font-size:0.7rem;color:var(--text-secondary);">' +
                    esc(e.reference) + '</div>' : '') + (e.account ? '<div style="font-size:0.7rem;color:var(--text-secondary);">' +
                    esc(e.account) + '</div>' : '') + '</td>' +
                '<td class="text-right">' + (e.direction === 'IN' ? formatCurrency(e.amount) : '') + '</td>' +
                '<td class="text-right">' + (e.direction === 'OUT' ? formatCurrency(e.amount) : '') + '</td>' +
                '<td class="text-right">' + (e.voided
                    ? '<span style="font-size:0.7rem;" title="' + esc(e.void_reason) + '">void</span>'
                    : '<button class="btn btn-sm btn-outline" onclick="voidEntry(' + e.id + ',\'' + esc(e.number) + '\')">Void</button>') +
                '</td></tr>';
        }).join('') : '<tr><td colspan="8" style="text-align:center;padding:24px;color:var(--text-secondary);">' +
            'Nothing received or paid yet. Record it from a bill, or on account from the Parties tab.</td></tr>') +
        '</tbody></table></div></div>';
}

async function voidEntry(id, number) {
    var reason = prompt('Why is ' + number + ' being voided? (It is kept, struck through, and the bill goes back to owing.)');
    if (reason === null) return;
    if (!reason.trim()) { showToast('A reason is required', 'error'); return; }
    var res = await fetch('/api/money/entries/' + id + '/void', {
        method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: reason }) });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not void it', 'error'); return; }
    showToast(out.message, 'success');
    loadLedger();
}
window.voidEntry = voidEntry;

async function ledgerBank(host) {
    await ledgerAccounts();
    var chosen = LEDGER.bankAccount || (LEDGER.accounts[0] || {}).id || 0;
    var book = chosen
        ? await (await fetch('/api/money/book?account_id=' + chosen, { credentials: 'include' })).json()
        : null;
    host.innerHTML =
        '<div style="display:flex;gap:10px;align-items:end;flex-wrap:wrap;margin-bottom:14px;">' +
        (LEDGER.accounts.length
            ? '<div class="form-group" style="margin:0;"><label>Account</label>' +
              '<select class="form-control" onchange="LEDGER.bankAccount=parseInt(this.value);loadLedger()">' +
              LEDGER.accounts.map(function (a) {
                  return '<option value="' + a.id + '"' + (a.id === chosen ? ' selected' : '') + '>' +
                      esc(a.name) + ' (' + esc(a.kind) + ')</option>'; }).join('') + '</select></div>'
            : '') +
        '<button class="btn btn-outline btn-sm" onclick="openAccountBox()">+ Bank account or cash box</button></div>' +
        (!LEDGER.accounts.length
            ? '<div class="widget"><div style="padding:24px;color:var(--text-secondary);">No accounts yet. Add the bank ' +
              'account payments go through, and a cash box for each site that keeps petty cash.</div></div>'
            : '<div class="stats-grid">' +
              statCard('Opening', formatCurrency(book.opening)) +
              statCard('Received', formatCurrency(book.received)) +
              statCard('Paid out', formatCurrency(book.paid)) +
              statCard('Balance', formatCurrency(book.closing)) + '</div>' +
              '<div class="widget" style="margin-top:14px;"><div class="table-responsive"><table class="data-table">' +
              '<thead><tr><th>Date</th><th>No.</th><th>Party</th><th>Against</th><th>Mode</th>' +
              '<th class="text-right">In ₹</th><th class="text-right">Out ₹</th><th class="text-right">Balance ₹</th></tr></thead><tbody>' +
              (book.rows.length ? book.rows.map(function (r) {
                  return '<tr><td>' + esc(r.date) + '</td><td style="font-family:monospace;">' + esc(r.number) + '</td>' +
                      '<td>' + esc(r.party) + '</td><td>' + esc(r.against) + '</td>' +
                      '<td>' + esc(r.mode) + (r.reference ? ' ' + esc(r.reference) : '') + '</td>' +
                      '<td class="text-right">' + (r.received ? formatCurrency(r.received) : '') + '</td>' +
                      '<td class="text-right">' + (r.paid ? formatCurrency(r.paid) : '') + '</td>' +
                      '<td class="text-right" style="font-weight:600;">' + formatCurrency(r.balance) + '</td></tr>';
              }).join('') : '<tr><td colspan="8" style="text-align:center;padding:24px;color:var(--text-secondary);">' +
                  'Nothing through this account yet.</td></tr>') +
              '</tbody></table></div></div>');
}

function openAccountBox() {
    ['acc-name', 'acc-bank', 'acc-no', 'acc-ifsc', 'acc-opening'].forEach(function (id) {
        document.getElementById(id).value = ''; });
    document.getElementById('acc-kind').value = 'Bank';
    document.getElementById('acc-date').value = localDate(new Date());
    openModal('account-modal');
    document.getElementById('acc-name').focus();
}
window.openAccountBox = openAccountBox;

async function saveAccount() {
    var val = function (id) { return document.getElementById(id).value; };
    var res = await fetch('/api/bank-accounts', {
        method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: val('acc-name'), kind: val('acc-kind'), bank_name: val('acc-bank'),
            account_no: val('acc-no'), ifsc: val('acc-ifsc'),
            opening_balance: parseFloat(val('acc-opening')) || 0, opening_date: val('acc-date') }) });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not add it', 'error'); return; }
    closeModal('account-modal');
    showToast(out.name + ' added', 'success');
    LEDGER.bankAccount = out.id;
    loadLedger();
}
window.saveAccount = saveAccount;

async function ledgerSuppliers(host) {
    var d = await (await fetch('/api/suppliers', { credentials: 'include' })).json();
    LEDGER.suppliers = d.suppliers || [];
    host.innerHTML =
        '<div style="display:flex;gap:10px;align-items:center;margin-bottom:14px;flex-wrap:wrap;">' +
        '<button class="btn btn-primary btn-sm" onclick="openSupplierBox()">+ Supplier</button>' +
        ((d.unregistered || []).length
            ? '<div style="font-size:0.8rem;padding:8px 12px;border:1px solid var(--warning-color);border-radius:8px;">' +
              '<strong>' + d.unregistered.length + '</strong> supplier name' + (d.unregistered.length === 1 ? '' : 's') +
              ' on orders and bills are not in the master yet (' + d.unregistered.slice(0, 4).map(esc).join(', ') +
              (d.unregistered.length > 4 ? '&hellip;' : '') + '). ' +
              '<a href="#" onclick="event.preventDefault();adoptSuppliers()">Add them all</a></div>' : '') +
        '</div>' +
        '<div class="widget"><div class="table-responsive"><table class="data-table">' +
        '<thead><tr><th>Code</th><th>Supplier</th><th>Supplies</th><th>GSTIN</th><th>State</th>' +
        '<th>Phone</th><th class="text-right">Pays in</th><th></th></tr></thead><tbody>' +
        (LEDGER.suppliers.length ? LEDGER.suppliers.map(function (s, i) {
            return '<tr' + (s.is_active ? '' : ' style="opacity:.55;"') + '>' +
                '<td style="font-family:monospace;">' + esc(s.code) + '</td>' +
                '<td style="font-weight:600;">' + esc(s.name) +
                    (s.contact_person ? '<div style="font-size:0.72rem;font-weight:400;color:var(--text-secondary);">' +
                    esc(s.contact_person) + '</div>' : '') + '</td>' +
                '<td>' + esc(s.supplies || '') + '</td>' +
                '<td style="font-family:monospace;font-size:0.8rem;">' + (esc(s.gstin) ||
                    '<span style="color:var(--warning-color);font-family:inherit;">none - input credit at risk</span>') + '</td>' +
                '<td>' + esc(s.state || '') + '</td><td>' + esc(s.phone || '') + '</td>' +
                '<td class="text-right">' + (s.payment_days || 0) + ' days</td>' +
                '<td class="text-right" style="white-space:nowrap;">' +
                    '<button class="btn btn-sm btn-outline" onclick="openStatement(\'supplier\',' +
                    JSON.stringify(s.name).replace(/"/g, '&quot;') + ')">Statement</button> ' +
                    '<button class="btn btn-sm btn-outline" onclick="openSupplierBox(' + i + ')">Edit</button></td></tr>';
        }).join('') : '<tr><td colspan="8" style="text-align:center;padding:24px;color:var(--text-secondary);">' +
            'No suppliers on file yet.</td></tr>') +
        '</tbody></table></div></div>';
}

function openSupplierBox(i) {
    var s = (i !== undefined && LEDGER.suppliers[i]) || {};
    LEDGER.editingSupplier = s.id || null;
    var f = { 'sup-name': s.name, 'sup-contact': s.contact_person, 'sup-phone': s.phone,
              'sup-email': s.email, 'sup-gstin': s.gstin, 'sup-pan': s.pan, 'sup-address': s.address,
              'sup-bank': s.bank_name, 'sup-account': s.bank_account, 'sup-ifsc': s.bank_ifsc,
              'sup-days': s.payment_days !== undefined ? s.payment_days : 30, 'sup-supplies': s.supplies };
    Object.keys(f).forEach(function (id) { document.getElementById(id).value = f[id] === undefined ? '' : f[id]; });
    document.getElementById('sup-title').textContent = s.id ? 'Edit ' + s.name : 'New supplier';
    openModal('supplier-modal');
    document.getElementById('sup-name').focus();
}
window.openSupplierBox = openSupplierBox;

async function saveSupplier() {
    var val = function (id) { return document.getElementById(id).value; };
    var id = LEDGER.editingSupplier;
    var res = await fetch('/api/suppliers' + (id ? '/' + id : ''), {
        method: id ? 'PUT' : 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: val('sup-name'), contact_person: val('sup-contact'),
            phone: val('sup-phone'), email: val('sup-email'), gstin: val('sup-gstin'), pan: val('sup-pan'),
            address: val('sup-address'), bank_name: val('sup-bank'), bank_account: val('sup-account'),
            bank_ifsc: val('sup-ifsc'), payment_days: parseInt(val('sup-days')) || 0,
            supplies: val('sup-supplies') }) });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not save it', 'error'); return; }
    closeModal('supplier-modal');
    showToast(out.code + ' ' + out.name + ' saved', 'success');
    loadLedger();
}
window.saveSupplier = saveSupplier;

async function adoptSuppliers() {
    var res = await fetch('/api/suppliers/adopt', { method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' }, body: '{}' });
    var out = await res.json();
    showToast(out.message || 'Done', res.ok ? 'success' : 'error');
    loadLedger();
}
window.adoptSuppliers = adoptSuppliers;

/* --- A statement of account, as the page it is sent as --------------------- */

async function openStatement(type, party) {
    var host = document.getElementById('document-body');
    if (!host) return;
    DOC.back = (typeof currentView === 'string' && currentView) || 'ledger-view';
    showView('document-view');
    document.getElementById('document-title').textContent = 'Statement of account';
    host.innerHTML = '<p style="text-align:center;padding:40px;color:var(--text-secondary);">Drawing up the statement...</p>';
    var d = await (await fetch('/api/ledger/statement?party_type=' + encodeURIComponent(type) +
                               '&party=' + encodeURIComponent(party), { credentials: 'include' })).json();
    var m = d.master || {};
    var weOwe = type !== 'client';
    host.innerHTML = '<div class="wo-sheet">' +
        docHead(d.our || {}, 'STATEMENT OF ACCOUNT', localDate(new Date()).split('-').reverse().join('/')) +
        '<div class="wo-cols" style="margin-top:14px;"><div><span class="wo-label">' +
            (weOwe ? 'With' : 'To') + '</span>' +
            '<div style="font-weight:700;margin-top:2px;">' + esc(d.party) + '</div>' +
            (m.address ? '<div class="wo-muted">' + docNl(m.address) + '</div>' : '') +
            ((m.gstin || m.pan) ? '<div class="wo-muted" style="font-size:0.72rem;">' +
                [m.gstin ? 'GSTIN: ' + esc(m.gstin) : '', m.pan ? 'PAN: ' + esc(m.pan) : '']
                .filter(Boolean).join(' &nbsp;|&nbsp; ') + '</div>' : '') +
        '</div><div>' + docFacts([['Account', esc(PARTY_LABEL[type] || type)],
            ['Opening', formatCurrency(d.opening)], ['Closing', formatCurrency(d.closing)]]) + '</div></div>' +
        '<table class="wo-table" style="margin-top:14px;font-size:0.76rem;"><thead><tr>' +
        '<th>Date</th><th>Particulars</th><th>No.</th><th class="num">' + (weOwe ? 'Their bills' : 'Our bills') + '</th>' +
        '<th class="num">' + (weOwe ? 'Paid by us' : 'Received') + '</th><th class="num">Balance</th></tr></thead><tbody>' +
        (d.opening ? '<tr><td></td><td><em>Opening balance</em></td><td></td><td></td><td></td>' +
            '<td class="num">' + formatCurrency(d.opening) + '</td></tr>' : '') +
        (d.rows || []).map(function (r) {
            return '<tr><td style="white-space:nowrap;">' + docDate(r.date) + '</td><td>' + esc(r.kind) +
                (r.against && r.against !== r.number ? ' <span class="wo-muted">against ' + esc(r.against) + '</span>' : '') +
                (r.reference ? ' <span class="wo-muted">' + esc(r.reference) + '</span>' : '') + '</td>' +
                '<td style="white-space:nowrap;font-family:monospace;font-size:0.7rem;">' + esc(r.number || '') + '</td>' +
                '<td class="num">' + (r.billed ? formatCurrency(r.billed) : '') + '</td>' +
                '<td class="num">' + (r.moved ? formatCurrency(r.moved) : '') + '</td>' +
                '<td class="num">' + formatCurrency(r.balance) + '</td></tr>';
        }).join('') +
        '</tbody><tfoot><tr style="font-weight:700;"><td colspan="3" style="text-align:right;">Totals</td>' +
        '<td class="num">' + formatCurrency(d.billed) + '</td><td class="num">' + formatCurrency(d.moved) + '</td>' +
        '<td class="num">' + formatCurrency(d.closing) + '</td></tr></tfoot></table>' +
        '<div class="wo-band" style="margin-top:12px;font-size:0.8rem;"><strong>' +
        (d.closing > 0 ? (weOwe ? 'Balance payable by us: ' : 'Balance due from you: ')
                       : d.closing < 0 ? (weOwe ? 'Advance with you: ' : 'Paid in advance: ') : 'Settled: ') +
        '</strong>' + formatCurrency(Math.abs(d.closing)) + ' &mdash; ' + esc(d.closing_words || '') + '</div>' +
        '<p class="wo-muted" style="margin-top:10px;font-size:0.72rem;">Please confirm this balance or let us have ' +
        'the differences within fifteen days. If we hear nothing it will be taken as agreed.</p>' +
        docSigns([['Prepared by', '', 'Accounts'], ['For ' + ((d.our || {}).name || ''), '', 'Authorised signatory'],
                  ['Confirmed by', '', 'For ' + d.party], ['Date', '', '']]) +
        '</div>';
    window.scrollTo(0, 0);
}
window.openStatement = openStatement;
