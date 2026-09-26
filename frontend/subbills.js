/* ===========================================================================
   subbills.js - the gangs' measurement book and the bills we pay them.

   The other side of the ledger from measurement.js. Same shape on purpose:
   measurements accumulate, a bill claims the difference, and the deductions
   come off in the order they are actually made. What differs is who holds
   the retention. Here it is us.
   =========================================================================== */

var SUB = { order: null, lines: [], entries: [], summary: {} };
var SUB_TONE = { DRAFT: 'calm', SUBMITTED: 'wait', CERTIFIED: 'good',
                 PAID: 'good', CANCELLED: 'bad' };

async function loadSubBills() {
    var pick = document.getElementById('sub-order');
    if (!pick) return;
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
        statCard('Items over the order', String(s.lines_over_measured || 0));

    document.getElementById('sub-mb-body').innerHTML = SUB.lines.length ? SUB.lines.map(function (l) {
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
            '<td>' + (dimsSummary(e.dimensions) ||
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
    ['sub-measure-dims-total', 'sub-measure-ref', 'sub-measure-remarks'].forEach(function (id) {
        document.getElementById(id).value = '';
    });
    document.getElementById('sub-measure-date').value = localDate(new Date());
    dimsInit('sub-measure-dims', l.uom);
    openModal('sub-measure-modal');
    var first = document.querySelector('#sub-measure-dims .dimcell');
    if (first) first.focus();
}
window.showSubMeasure = showSubMeasure;

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
    document.getElementById('sub-bill-stats').innerHTML =
        statCard('Claimed by the gang', formatCurrency(s.claimed || 0)) +
        statCard('Awaiting certification', String(s.awaiting_certification || 0)) +
        statCard('Certified, unpaid', formatCurrency(s.certified_unpaid || 0)) +
        statCard('Retention we hold', formatCurrency(s.retention_held || 0)) +
        statCard('Paid out', formatCurrency(s.paid || 0));

    document.getElementById('sub-bill-body').innerHTML = bills.length ? bills.map(function (b) {
        var act = '';
        if (b.actions.indexOf('SUBMIT') >= 0)
            act = '<button class="btn btn-sm btn-primary" onclick="subBillAct(' + b.id + ',\'submit\')">Submit</button>';
        else if (b.actions.indexOf('CERTIFY') >= 0)
            act = '<button class="btn btn-sm btn-primary" onclick="subBillAct(' + b.id + ',\'certify\')">Certify</button> ' +
                  '<button class="btn btn-sm btn-outline" onclick="subBillAct(' + b.id + ',\'reject\',true)">Send back</button>';
        else if (b.actions.indexOf('PAY') >= 0)
            act = '<button class="btn btn-sm btn-primary" onclick="openPayBox(\'sub_bill\',' + b.id + ',function(){if(typeof loadSubBills===\'function\')loadSubBills();})">Pay</button>';
        return '<tr>' +
            '<td style="font-family:monospace;font-weight:600;">' + esc(b.number) + '</td>' +
            '<td>' + esc(b.contractor) + '<div style="font-size:0.75rem;color:var(--text-secondary);">' +
                esc(b.project) + '</div></td>' +
            '<td class="text-right">' + formatCurrency(b.this_bill) + '</td>' +
            '<td class="text-right">' + formatCurrency(b.retention_amount) + '</td>' +
            '<td class="text-right">' + formatCurrency(b.tds_amount) + '</td>' +
            '<td class="text-right" style="font-weight:700;">' + formatCurrency(b.net_payable) + '</td>' +
            '<td>' + statusPill(b.status, SUB_TONE[b.status] || 'calm') +
                (b.paid_reference ? '<div style="font-size:0.72rem;color:var(--text-secondary);">' +
                 esc(b.paid_reference) + '</div>' : '') + '</td>' +
            '<td class="text-right" style="white-space:nowrap;">' + act +
                ' <button class="btn btn-sm btn-outline" onclick="openDocument(\'sub-bill\',' + b.id + ')" ' +
                'title="The bill as it prints">View bill</button>' +
                ' <a class="btn btn-sm btn-outline" href="/api/sub-bills/' + b.id +
                '/document.pdf" target="_blank" rel="noopener" title="The bill in the ruled form it is signed on">PDF</a>' +
                ' <a class="btn btn-sm btn-outline" href="/api/sub-bills/' +
                b.id + '/export.xlsx" title="As a workbook">Excel</a></td></tr>';
    }).join('') : '<tr><td colspan="8" style="text-align:center;padding:24px;' +
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
    openSubBook(SUB.order.id);
}
window.newSubBill = newSubBill;

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
