/* ===========================================================================
   subbills.js - the gangs' measurement book and the bills we pay them.

   The other side of the ledger from measurement.js. Same shape on purpose:
   measurements accumulate, a bill claims the difference, and the deductions
   come off in the order they are actually made. What differs is who holds
   the retention. Here it is us.
   =========================================================================== */

var SUB = { order: null, lines: [], entries: [], summary: {}, bills: [], mbImport: null, tab: 'bills', nextTab: null };
var SUB_TONE = { DRAFT: 'calm', SUBMITTED: 'wait', CERTIFIED: 'good',
                 PAID: 'good', CANCELLED: 'bad' };

/* One screen, two tabs: the gang's measurement book, and the RA bills drawn
   from it. The menu and the strip across the top open either. */
function openSubTab(tab) {
    SUB.nextTab = tab;
    if ((typeof currentView === 'string' && currentView === 'subbills-view') ||
        (document.getElementById('subbills-view') || {}).style.display === 'block') {
        SUB.tab = tab;
        SUB.nextTab = null;
        applySubTab();
        return;
    }
    showView('subbills-view');
}
window.openSubTab = openSubTab;

function applySubTab() {
    var mb = SUB.tab === 'mb';
    document.getElementById('sub-pane-mb').style.display = mb ? '' : 'none';
    document.getElementById('sub-pane-bills').style.display = mb ? 'none' : '';
    document.querySelectorAll('#subbills-view .sub-only-mb').forEach(function (el) { el.style.display = mb ? '' : 'none'; });
    document.querySelectorAll('#subbills-view .sub-only-bills').forEach(function (el) { el.style.display = mb ? 'none' : ''; });
    document.getElementById('sub-title').textContent = mb ? 'Measurement Book' : 'RA Bills';
    document.getElementById('sub-subtitle').textContent = mb
        ? 'What the gang has built, measured line by line - No\'s × NoM × L × W × H, blocks alike counted once'
        : 'Certificate of payment, abstract and MB for each bill - prepared, certified, approved, paid';
    var mbNav = document.getElementById('nav-submb'), billNav = document.getElementById('nav-subbills');
    if (mbNav) mbNav.classList.toggle('active', mb);
    if (billNav) billNav.classList.toggle('active', !mb);
    if (typeof renderScFlow === 'function') renderScFlow(SUB.tab);
}
window.applySubTab = applySubTab;

async function loadSubBills() {
    var pick = document.getElementById('sub-order');
    if (!pick) return;
    SUB.tab = SUB.nextTab || 'bills';
    SUB.nextTab = null;
    applySubTab();
    var d = await (await fetch('/api/wo/orders', { credentials: 'include' })).json();
    // Only an approved order has anything a gang can be paid for.
    var live = (d.orders || []).filter(function (o) {
        return o.status === 'APPROVED' || o.status === 'EXECUTED';
    });
    pick.innerHTML = live.length
        ? live.map(function (o) {
            return '<option value="' + o.id + '">' + esc(o.wo_number) + ' — ' +
                esc(o.contractor || '') + (o.project ? ' · ' + esc(o.project) : '') + '</option>';
          }).join('')
        : '<option value="">No approved subcontract orders yet</option>';
    if (live.length) openSubBook(live[0].id);
    else {
        document.getElementById('sub-mb-body').innerHTML =
            '<tr><td colspan="8" style="text-align:center;padding:30px;color:var(--text-secondary);">' +
            'Approve a subcontract order first. A gang is measured against work that has been agreed.</td></tr>';
        renderSubBillList([]);
    }
}
window.loadSubBills = loadSubBills;

function subOrderChanged() {
    var pick = document.getElementById('sub-order');
    if (pick && pick.value) openSubBook(parseInt(pick.value));
}
window.subOrderChanged = subOrderChanged;

async function openSubBook(orderId) {
    var body = document.getElementById('sub-mb-body');
    if (!body) return;
    var res = await fetch('/api/sub-mb/' + orderId, { credentials: 'include' });
    if (!res.ok) { body.innerHTML = '<tr><td colspan="8">Could not open that order.</td></tr>'; return; }
    var d = await res.json();
    SUB = { order: d.order, lines: d.lines, entries: d.entries, summary: d.summary };
    renderSubBook();
    var bills = await (await fetch('/api/sub-bills?order_id=' + orderId,
                                   { credentials: 'include' })).json();
    renderSubBillList(bills.bills || [], bills.summary || {});
}
window.openSubBook = openSubBook;

function renderSubBook() {
    var s = SUB.summary;
    document.getElementById('sub-stats').innerHTML =
        statCard('Order value', formatCurrency(s.ordered_value || 0)) +
        statCard('Work measured', formatCurrency(s.measured_value || 0)) +
        statCard('Measured, not billed', formatCurrency(s.unbilled_value || 0)) +
        statCard('Items over the order', String(s.lines_over_measured || 0)) +
        (s.unbilled_value > 0 && can('billing.manage')
            ? '<div style="grid-column:1/-1;display:flex;justify-content:space-between;align-items:center;gap:12px;' +
              'padding:12px 16px;border:1px solid var(--primary-color);border-radius:10px;">' +
              '<span>' + formatCurrency(s.unbilled_value) + ' measured and not yet billed.</span>' +
              '<button class="btn btn-sm btn-primary" onclick="openSubTab(\'bills\');newSubBill()">Draw up the RA bill</button></div>'
            : '');

    document.getElementById('sub-mb-body').innerHTML = SUB.lines.length ? SUB.lines.map(function (l) {
        // A heading on the schedule ("Painting Works") groups the items under it and is never measured.
        if (l.is_header) return '<tr><td colspan="8" style="font-weight:700;padding-top:14px;">' +
            esc(l.activity_no ? l.activity_no + ' ' : '') + esc(l.description) + '</td></tr>';
        var pc = Math.max(0, Math.min(100, l.percent_measured));
        return '<tr>' +
            '<td style="font-family:monospace;font-weight:600;">' + esc(l.activity_no) +
                '<div style="font-size:0.75rem;font-family:inherit;font-weight:400;' +
                'color:var(--text-secondary);">' + esc(l.description) + '</div></td>' +
            '<td class="text-right">' + l.ordered_qty + ' ' + esc(l.uom) + '</td>' +
            '<td class="text-right">' + l.measured_to_date +
                '<div style="height:5px;background:var(--border-color);border-radius:3px;' +
                'margin-top:4px;overflow:hidden;"><div style="width:' + pc + '%;height:100%;' +
                'background:var(--primary-color);"></div></div></td>' +
            '<td class="text-right">' + (l.balance_to_measure >= 0 ? l.balance_to_measure
                : '<span style="color:var(--warning-color);">0</span>') +
                (l.over_measured > 0 ? '<div style="font-size:0.72rem;color:var(--warning-color);">' +
                 l.over_measured + ' over the order</div>' : '') + '</td>' +
            '<td class="text-right">' + l.billed_to_date + '</td>' +
            '<td class="text-right" style="font-weight:600;">' + l.unbilled + '</td>' +
            '<td class="text-right">' + formatCurrency(l.unbilled * l.rate) + '</td>' +
            '<td class="text-right"><button class="btn btn-sm btn-primary" onclick="showSubMeasure(' +
                l.item_id + ')">Measure</button></td></tr>';
    }).join('') : '<tr><td colspan="8" style="text-align:center;padding:24px;' +
        'color:var(--text-secondary);">This order has no items.</td></tr>';

    document.getElementById('sub-entries').innerHTML = SUB.entries.length ? SUB.entries.slice(0, 60).map(function (e) {
        return '<tr><td style="white-space:nowrap;">' + esc(e.measured_on) + '</td>' +
            '<td style="font-family:monospace;">' + esc(e.activity_no) + '</td>' +
            '<td>' + (e.location ? '<div style="font-weight:600;font-size:0.8rem;">' + esc(e.location) + '</div>' : '') +
                (e.multiplier && e.multiplier !== 1 ? '<div style="font-size:0.72rem;font-weight:600;">× ' + e.multiplier + ' blocks alike</div>' : '') +
                (dimsSummary(e.dimensions) ||
                '<span style="font-size:0.72rem;color:var(--text-secondary);">total only</span>') + '</td>' +
            '<td class="text-right" style="font-weight:600;' + (e.quantity < 0 ? 'color:var(--warning-color);' : '') +
                '">' + e.quantity + '</td>' +
            '<td>' + esc(e.mb_ref || '—') + '</td>' +
            '<td>' + esc(e.recorded_by_name || '') + '</td>' +
            '<td>' + esc(e.remarks || '') + '</td>' +
            '<td class="text-right no-print">' + (e.billed ? statusPill('billed', 'good')
                : '<button class="btn btn-sm btn-outline" onclick="removeSubEntry(' + e.id + ')">Remove</button>') +
            '</td></tr>';
    }).join('') : '<tr><td colspan="8" style="text-align:center;padding:24px;' +
        'color:var(--text-secondary);">Nothing measured yet.</td></tr>';
}

function showSubMeasure(itemId) {
    var l = SUB.lines.filter(function (x) { return x.item_id === itemId; })[0];
    if (!l) return;
    document.getElementById('sub-measure-item').value = itemId;
    document.getElementById('sub-measure-title').textContent = l.activity_no + ' — ' + l.description;
    document.getElementById('sub-measure-context').textContent =
        'Ordered ' + l.ordered_qty + ' ' + l.uom + ' · measured ' + l.measured_to_date + ' · ' +
        (l.balance_to_measure >= 0 ? l.balance_to_measure + ' still to do'
                                   : l.over_measured + ' already over the order');
    ['sub-measure-dims-total', 'sub-measure-ref', 'sub-measure-remarks', 'sub-measure-location'].forEach(function (id) {
        var el = document.getElementById(id);
        if (el) el.value = '';
    });
    var mult = document.getElementById('sub-measure-multiplier');
    if (mult) mult.value = '1';
    subMeasureTotalHint();
    document.getElementById('sub-measure-date').value = localDate(new Date());
    dimsInit('sub-measure-dims', l.uom);
    openModal('sub-measure-modal');
    var first = document.querySelector('#sub-measure-dims .dimcell');
    if (first) first.focus();
}
window.showSubMeasure = showSubMeasure;

function subMeasureBlocks() {
    var el = document.getElementById('sub-measure-multiplier');
    var n = el ? parseFloat(el.value) : 1;
    return n > 0 ? n : 1;
}

/* One block measured, several built alike: the book's "Total Quantity for 4
   Blocks", shown as the lines are typed. */
function subMeasureTotalHint() {
    var hint = document.getElementById('sub-measure-blocks');
    if (!hint) return;
    var n = subMeasureBlocks();
    var one = parseFloat((document.getElementById('sub-measure-dims-total') || {}).value);
    hint.textContent = n !== 1 && !isNaN(one)
        ? 'Total Quantity for ' + n + ' Blocks: ' + (Math.round(one * n * 1000) / 1000) + ' (' + one + ' for one block)'
        : '';
}
window.subMeasureTotalHint = subMeasureTotalHint;
document.addEventListener('input', function (e) {
    if (e.target && e.target.closest && e.target.closest('#sub-measure-dims')) setTimeout(subMeasureTotalHint, 0);
});

function closeSubMeasure() { closeModal('sub-measure-modal'); }
window.closeSubMeasure = closeSubMeasure;

async function saveSubMeasure() {
    var dims = dimsRows('sub-measure-dims');
    var qty = parseFloat(document.getElementById('sub-measure-dims-total').value);
    if (!dims.length && !qty) { showToast('A measurement of nothing is not a measurement', 'error'); return; }
    var res = await fetch('/api/sub-mb/' + SUB.order.id + '/entries', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            item_id: parseInt(document.getElementById('sub-measure-item').value),
            quantity: dims.length ? 0 : qty, dimensions: dims.length ? dims : null,
            multiplier: subMeasureBlocks(),
            location: (document.getElementById('sub-measure-location') || {}).value || '',
            measured_on: document.getElementById('sub-measure-date').value,
            mb_ref: document.getElementById('sub-measure-ref').value,
            remarks: document.getElementById('sub-measure-remarks').value,
        }),
    });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not record it', 'error'); return; }
    closeSubMeasure();
    showToast(out.message, out.over_measured ? 'warning' : 'success');
    openSubBook(SUB.order.id);
}
window.saveSubMeasure = saveSubMeasure;

async function removeSubEntry(id) {
    var res = await fetch('/api/sub-mb/entries/' + id, { method: 'DELETE', credentials: 'include' });
    var out = await res.json();
    showToast(res.ok ? out.message : (out.detail || 'Could not remove it'), res.ok ? 'success' : 'error');
    openSubBook(SUB.order.id);
}
window.removeSubEntry = removeSubEntry;

/* --- The bills we pay ----------------------------------------------------- */

function renderSubBillList(bills, summary) {
    var s = summary || {};
    var uptoDate = bills.filter(function (b) { return b.status !== 'CANCELLED'; })
        .reduce(function (m, b) { return Math.max(m, b.gross_to_date || 0); }, 0);
    document.getElementById('sub-bill-stats').innerHTML =
        statCard('Billed up to date', formatCurrency(uptoDate)) +
        statCard('Claimed by the gang', formatCurrency(s.claimed || 0)) +
        statCard('Awaiting certification', String(s.awaiting_certification || 0)) +
        statCard('Certified, unpaid', formatCurrency(s.certified_unpaid || 0)) +
        statCard('Retention we hold', formatCurrency(s.retention_held || 0)) +
        statCard('Paid out', formatCurrency(s.paid || 0));

    SUB.bills = bills;
    var cumulative = {};
    var running = 0;
    bills.slice().sort(function (a, b) { return (a.sequence || 0) - (b.sequence || 0) || a.id - b.id; })
        .forEach(function (b) {
            if (b.status !== 'CANCELLED') running += b.net_payable || 0;
            cumulative[b.id] = running;
        });
    document.getElementById('sub-bill-body').innerHTML = bills.length ? bills.map(function (b) {
        var act = '';
        var route = b.route || [];
        var waiting = route.filter(function (r) { return r.status === 'waiting'; })[0];
        var lastStep = !waiting || waiting.step === route.length;
        if (b.actions.indexOf('SUBMIT') >= 0 && can('billing.manage'))
            act = '<button class="btn btn-sm btn-outline" onclick="openSubBillEdit(' + b.id + ')" title="Bill date, period, type of work, SAC, recoveries">Edit</button> ' +
                  '<button class="btn btn-sm btn-primary" onclick="subBillAct(' + b.id + ',\'submit\')">Submit</button>';
        else if (b.actions.indexOf('CERTIFY') >= 0 && can('subcontracts.approve'))
            act = '<button class="btn btn-sm btn-primary" onclick="subBillAct(' + b.id + ',\'certify\')">' +
                  (lastStep ? 'Certify' : 'Sign and pass on') + '</button> ' +
                  '<button class="btn btn-sm btn-outline" onclick="subBillAct(' + b.id + ',\'reject\',true)">Send back</button>';
        else if (b.actions.indexOf('PAY') >= 0 && can('bills.pay'))
            act = '<button class="btn btn-sm btn-primary" onclick="openPayBox(\'sub_bill\',' + b.id + ',function(){if(typeof loadSubBills===\'function\')loadSubBills();})">Pay</button>';
        return '<tr>' +
            '<td><div style="font-family:monospace;font-weight:600;">' + esc(b.number) + '</div>' +
                '<div style="font-size:0.75rem;margin-top:4px;white-space:nowrap;">' +
                '<a href="#" onclick="event.preventDefault();openDocument(\'sub-bill\',' + b.id + ')" title="The bill as it prints">View</a> · ' +
                '<a href="/api/sub-bills/' + b.id + '/document.pdf" target="_blank" rel="noopener" ' +
                'title="Certificate of payment, abstract and measurement book, as they are signed">PDF</a> · ' +
                '<a href="/api/sub-bills/' + b.id + '/export.xlsx" title="Top Sheet, AB-1 and MB-1 as a workbook">Excel</a></div></td>' +
            '<td>' + esc(b.contractor) + '<div style="font-size:0.75rem;color:var(--text-secondary);">' +
                esc(b.project) + '</div></td>' +
            '<td class="text-right" style="color:var(--text-secondary);">' + formatCurrency(b.previously_billed) + '</td>' +
            '<td class="text-right">' + formatCurrency(b.this_bill) + '</td>' +
            '<td class="text-right" style="font-weight:600;">' + formatCurrency(b.gross_to_date) + '</td>' +
            '<td class="text-right">' + formatCurrency(b.retention_amount) + '</td>' +
            '<td class="text-right">' + formatCurrency(b.tds_amount) + '</td>' +
            '<td class="text-right" style="font-weight:700;">' + formatCurrency(b.net_payable) + '</td>' +
            '<td class="text-right" style="font-weight:600;">' + formatCurrency(cumulative[b.id]) + '</td>' +
            '<td>' + statusPill(b.status, SUB_TONE[b.status] || 'calm') + subBillSignatures(b) +
                (b.paid_reference ? '<div style="font-size:0.72rem;color:var(--text-secondary);">' +
                 esc(b.paid_reference) + '</div>' : '') + '</td>' +
            '<td class="text-right"><div style="display:flex;flex-wrap:wrap;gap:4px;justify-content:flex-end;min-width:170px;">' + act +
                (b.status !== 'DRAFT' && b.status !== 'CANCELLED' && !b.accepted_by_name && can('billing.manage')
                    ? ' <button class="btn btn-sm btn-outline" onclick="subBillAccept(' + b.id + ')" ' +
                      'title="Accepted for Sub Contractor - the gang has signed the certificate">Gang accepted</button>' : '') +
                '</div></td></tr>';
    }).join('') : '<tr><td colspan="11" style="text-align:center;padding:24px;' +
        'color:var(--text-secondary);">No bills yet. Measure the gang\'s work, then draw one up.</td></tr>';
}

async function newSubBill() {
    if (!SUB.order) { showToast('Choose an order first', 'error'); return; }
    var res = await fetch('/api/sub-bills', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ order_id: SUB.order.id }),
    });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not draw up a bill', 'error'); return; }
    showToast(out.message, 'success');
    await openSubBook(SUB.order.id);
    // The certificate's own boxes are filled in next: the dates, the SAC, the recoveries.
    if (out.bill) openSubBillEdit(out.bill.id, out.bill);
}
window.newSubBill = newSubBill;

/* Who has signed the certificate, and whose desk it is on. */
function subBillSignatures(b) {
    var lines = [];
    if (b.submitted_by_name) lines.push('Prepared by ' + esc(b.submitted_by_name));
    (b.route || []).forEach(function (r) {
        if (r.status === 'approved') lines.push('Signed: ' + esc(r.name));
        else if (r.status === 'waiting') lines.push('<strong>With ' + esc(r.name) +
            ((b.route || []).length > 1 ? ' (step ' + r.step + ' of ' + b.route.length + ')' : '') + '</strong>');
    });
    if (b.accepted_by_name) lines.push('Accepted by ' + esc(b.accepted_by_name));
    if (b.status === 'DRAFT' && b.remarks) lines.push('<span style="color:var(--warning-color);">Sent back: ' + esc(b.remarks) + '</span>');
    return lines.length ? '<div style="font-size:0.72rem;color:var(--text-secondary);margin-top:3px;line-height:1.35;">' +
        lines.join('<br>') + '</div>' : '';
}

async function openSubBillEdit(id, given) {
    // The full bill, which says how much of its recoveries is material issued.
    var b = given && given.material_recovered !== undefined ? given : null;
    if (!b) {
        var res = await fetch('/api/sub-bills/' + id, { credentials: 'include' });
        if (!res.ok) { showToast('Could not open that bill', 'error'); return; }
        b = await res.json();
    }
    var set = function (k, v) { var el = document.getElementById(k); if (el) el.value = v === null || v === undefined ? '' : v; };
    document.getElementById('sub-bill-edit-title').textContent = 'Certificate of payment - ' + b.number;
    set('sbe-id', b.id);
    set('sbe-date', b.bill_date);
    set('sbe-from', b.period_from);
    set('sbe-to', b.period_to);
    set('sbe-type', b.work_type);
    set('sbe-sac', b.hsn_sac);
    set('sbe-work', b.work_name);
    set('sbe-debit', b.debit_notes || '');
    set('sbe-advance', b.advance_recovery || '');
    var material = b.material_recovered || 0;
    set('sbe-other', Math.max(0, Math.round(((b.other_deductions || 0) - material) * 100) / 100) || '');
    set('sbe-notes', b.deduction_notes);
    document.getElementById('sbe-material').textContent = material
        ? 'Material issued to the gang, ' + formatCurrency(material) + ', is recovered on this bill as well and stays.' : '';
    openModal('sub-bill-edit-modal');
}
window.openSubBillEdit = openSubBillEdit;

async function saveSubBillEdit() {
    var v = function (id) { return document.getElementById(id).value; };
    var n = function (id) { var x = parseFloat(v(id)); return isNaN(x) ? 0 : x; };
    var id = parseInt(v('sbe-id'));
    var res = await fetch('/api/sub-bills/' + id, {
        method: 'PUT', credentials: 'include', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ bill_date: v('sbe-date'), period_from: v('sbe-from'), period_to: v('sbe-to'),
                               work_type: v('sbe-type'), hsn_sac: v('sbe-sac'), work_name: v('sbe-work'),
                               debit_notes: n('sbe-debit'), advance_recovery: n('sbe-advance'),
                               other_deductions: n('sbe-other'), deduction_notes: v('sbe-notes') }),
    });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Not saved', 'error'); return; }
    closeModal('sub-bill-edit-modal');
    showToast(out.message + ' Net payable ' + formatCurrency(out.bill.net_payable) + '.', 'success');
    if (SUB.order) openSubBook(SUB.order.id);
}
window.saveSubBillEdit = saveSubBillEdit;

async function subBillAccept(id) {
    var who = prompt('Who signed the certificate for the sub contractor?');
    if (who === null) return;
    var res = await fetch('/api/sub-bills/' + id + '/accept', {
        method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: who.trim() }) });
    var out = await res.json();
    showToast(res.ok ? out.message : (out.detail || 'Could not record it'), res.ok ? 'success' : 'error');
    if (SUB.order) openSubBook(SUB.order.id);
}
window.subBillAccept = subBillAccept;

/* --- The measurement book from its Excel sheet ------------------------------- */

function openSubMbImport() {
    if (!SUB.order) { showToast('Choose an order first', 'error'); return; }
    SUB.mbImport = null;
    document.getElementById('sub-mb-file').value = '';
    document.getElementById('sub-mb-date').value = '';
    document.getElementById('sub-mb-preview').innerHTML = '';
    document.getElementById('sub-mb-confirm').disabled = true;
    openModal('sub-mb-import-modal');
}
window.openSubMbImport = openSubMbImport;

function subMbForm(commit) {
    var fd = new FormData();
    fd.append('file', document.getElementById('sub-mb-file').files[0]);
    fd.append('commit', commit ? '1' : '0');
    var when = document.getElementById('sub-mb-date').value;
    if (when) fd.append('measured_on', when);
    var mapping = {};
    document.querySelectorAll('.sub-mb-map').forEach(function (sel) { if (sel.value) mapping[sel.dataset.i] = parseInt(sel.value); });
    fd.append('mapping', JSON.stringify(mapping));
    return fd;
}

async function previewSubMbImport() {
    var file = document.getElementById('sub-mb-file').files[0];
    var host = document.getElementById('sub-mb-preview');
    document.getElementById('sub-mb-confirm').disabled = true;
    if (!file) { host.innerHTML = ''; return; }
    host.innerHTML = '<p style="color:var(--text-secondary);">Reading the book...</p>';
    var res = await fetch('/api/sub-mb/' + SUB.order.id + '/import', { method: 'POST', credentials: 'include', body: subMbForm(false) });
    var out = await res.json();
    if (!res.ok) { host.innerHTML = '<p style="color:var(--danger-color);">' + esc(out.detail || 'Could not read it') + '</p>'; return; }
    SUB.mbImport = out;
    if (out.meta && out.meta.date && !document.getElementById('sub-mb-date').value)
        document.getElementById('sub-mb-date').value = out.meta.date;
    host.innerHTML = '<p style="font-size:0.82rem;margin-bottom:8px;">Sheet <strong>' + esc(out.sheet) + '</strong>' +
        (out.meta && out.meta.work_name ? ' - ' + esc(out.meta.work_name) : '') + '</p>' +
        '<div class="table-responsive"><table class="data-table"><thead><tr><th>In the book</th><th>Blocks and quantity</th><th>Item on the order</th></tr></thead><tbody>' +
        out.sections.map(function (s) {
            return '<tr><td><strong>' + esc(s.sno ? s.sno + '. ' : '') + esc(s.description) + '</strong></td>' +
                '<td style="font-size:0.8rem;">' + s.entries.map(function (e) {
                    return esc(e.location || 'Unheaded') + ': ' + e.lines + ' lines, ' +
                        (e.multiplier !== 1 ? e.one_block + ' × ' + e.multiplier + ' blocks = ' : '') + '<strong>' + e.quantity + '</strong>';
                }).join('<br>') + '<div style="font-weight:700;margin-top:3px;">' + s.quantity + ' ' + esc(s.uom || '') + '</div></td>' +
                '<td><select class="form-control sub-mb-map" data-i="' + s.index + '" onchange="subMbMapped()">' +
                    '<option value="">- which item? -</option>' + out.items.map(function (it) {
                        return '<option value="' + it.id + '"' + (it.id === s.item_id ? ' selected' : '') + '>' + esc(it.label) + '</option>';
                    }).join('') + '</select></td></tr>';
        }).join('') + '</tbody></table></div>' +
        (out.warnings && out.warnings.length ? '<ul style="font-size:0.78rem;color:var(--warning-color);margin:8px 0 0 18px;">' +
            out.warnings.map(function (w) { return '<li>' + esc(w) + '</li>'; }).join('') + '</ul>' : '');
    subMbMapped();
}
window.previewSubMbImport = previewSubMbImport;

function subMbMapped() {
    var all = Array.prototype.every.call(document.querySelectorAll('.sub-mb-map'), function (s) { return !!s.value; });
    document.getElementById('sub-mb-confirm').disabled = !all || !SUB.mbImport;
}
window.subMbMapped = subMbMapped;

async function commitSubMbImport() {
    var btn = document.getElementById('sub-mb-confirm');
    btn.disabled = true;
    var res = await fetch('/api/sub-mb/' + SUB.order.id + '/import', { method: 'POST', credentials: 'include', body: subMbForm(true) });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Nothing was recorded', 'error'); btn.disabled = false; return; }
    closeModal('sub-mb-import-modal');
    showToast(out.message, 'success');
    openSubBook(SUB.order.id);
}
window.commitSubMbImport = commitSubMbImport;

async function subBillAct(id, action, needsReason) {
    var body = {};
    if (needsReason) {
        var why = prompt('Why is this going back?');
        if (why === null) return;
        if (!why.trim()) { showToast('A reason is required', 'error'); return; }
        body.comments = why;
    }
    if (action === 'pay') {
        var ref = prompt('Payment reference (NEFT / cheque number)') || '';
        body.reference = ref;
    }
    var res = await fetch('/api/sub-bills/' + id + '/' + action, {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not do that', 'error'); return; }
    showToast(out.message, 'success');
    if (SUB.order) openSubBook(SUB.order.id);
}
window.subBillAct = subBillAct;
