/* ===========================================================================
   measurement.js - the measurement book, and the bills that follow from it.

   Work is measured on site, the measurements accumulate, and each bill claims
   the difference between what has been measured to date and what earlier
   bills already claimed. Nobody types a bill: that subtraction is exactly the
   arithmetic a site office gets wrong by hand every month.
   =========================================================================== */

var MB = { wo: null, lines: [], entries: [], summary: {} };
var RA = { bills: [], summary: {}, current: null };

var RA_TONE = {
    DRAFT: 'calm', SUBMITTED: 'wait', CERTIFIED: 'good',
    PAID: 'good', CANCELLED: 'bad',
};

/* --- Choosing the order to measure against ------------------------------- */

async function loadMeasurement() {
    var pick = document.getElementById('mb-order');
    if (!pick) return;
    var data = await (await fetch('/api/erp/work-orders', { credentials: 'include' })).json();
    // Only a placed order can be measured; a draft has not been committed to
    // anybody, so there is nothing on site to find.
    var open = (data.work_orders || []).filter(function (w) { return w.status !== 'Draft'; });
    pick.innerHTML = open.length
        ? open.map(function (w) {
            return '<option value="' + w.id + '">' + esc(w.number) + ' — ' +
                esc(w.job_name || '') + '</option>';
          }).join('')
        : '<option value="">No placed orders yet</option>';
    if (open.length) openMeasurementBook(open[0].id);
    else document.getElementById('mb-body').innerHTML =
        '<tr><td colspan="8" style="text-align:center;padding:30px;color:var(--text-secondary);">' +
        'Place a work order first. Measurement is against work that has been committed.</td></tr>';
    loadRaBills();
}
window.loadMeasurement = loadMeasurement;

async function openMeasurementBook(woId) {
    var body = document.getElementById('mb-body');
    if (!body) return;
    body.innerHTML = '<tr><td colspan="8" style="text-align:center;padding:24px;' +
        'color:var(--text-secondary);">Opening the book...</td></tr>';
    var res = await fetch('/api/mb/' + woId, { credentials: 'include' });
    if (!res.ok) {
        body.innerHTML = '<tr><td colspan="8" style="text-align:center;padding:24px;' +
            'color:var(--text-secondary);">Could not open that order.</td></tr>';
        return;
    }
    var d = await res.json();
    MB = { wo: d.work_order, lines: d.lines, entries: d.entries, summary: d.summary };
    renderMeasurementBook();
    loadRaBills(woId);
    offerVariation(woId);
    loadVariations(woId);
}
window.openMeasurementBook = openMeasurementBook;

function mbChanged() {
    var pick = document.getElementById('mb-order');
    if (pick && pick.value) openMeasurementBook(parseInt(pick.value));
}
window.mbChanged = mbChanged;

function renderMeasurementBook() {
    var stats = document.getElementById('mb-stats');
    if (stats) {
        var s = MB.summary;
        stats.innerHTML =
            statCard('Ordered', formatCurrency(s.ordered_value || 0)) +
            statCard('Measured', formatCurrency(s.measured_value || 0)) +
            statCard('Measured, not billed', formatCurrency(s.unbilled_value || 0)) +
            statCard('Lines over the order', String(s.lines_over_measured || 0));
    }

    var body = document.getElementById('mb-body');
    body.innerHTML = MB.lines.length ? MB.lines.map(function (l) {
        var pc = Math.max(0, Math.min(100, l.percent_measured));
        return '<tr>' +
            '<td style="font-family:monospace;font-weight:600;">' + esc(l.fg_code) +
                '<div style="font-size:0.75rem;font-family:inherit;font-weight:400;' +
                'color:var(--text-secondary);">' + esc(l.description) + '</div></td>' +
            '<td class="text-right">' + l.ordered_qty + ' ' + esc(l.uom) + '</td>' +
            '<td class="text-right">' + l.measured_to_date +
                '<div style="height:5px;background:var(--border-color);border-radius:3px;' +
                'margin-top:4px;overflow:hidden;"><div style="width:' + pc + '%;height:100%;' +
                'background:var(--primary-color);"></div></div></td>' +
            '<td class="text-right">' + (l.balance_to_measure >= 0
                ? l.balance_to_measure
                : '<span style="color:var(--warning-color);">0</span>') +
                (l.over_measured > 0
                    ? '<div style="font-size:0.72rem;color:var(--warning-color);">' +
                      l.over_measured + ' over the order</div>' : '') + '</td>' +
            '<td class="text-right">' + l.billed_to_date + '</td>' +
            '<td class="text-right" style="font-weight:600;">' + l.unbilled + '</td>' +
            '<td class="text-right">' + formatCurrency(l.unbilled * l.rate) + '</td>' +
            '<td class="text-right"><button class="btn btn-sm btn-primary" ' +
                'onclick="showMeasureModal(' + l.line_id + ')">Measure</button></td>' +
            '</tr>';
    }).join('') : '<tr><td colspan="8" style="text-align:center;padding:24px;' +
        'color:var(--text-secondary);">This order has no lines.</td></tr>';

    var log = document.getElementById('mb-entries');
    if (!log) return;
    log.innerHTML = MB.entries.length ? MB.entries.slice(0, 40).map(function (e) {
        return '<tr>' +
            '<td>' + esc(e.measured_on) + '</td>' +
            '<td style="font-family:monospace;">' + esc(e.fg_code) + '</td>' +
            '<td class="text-right"' + (e.quantity < 0 ? ' style="color:var(--warning-color);"' : '') +
                '>' + e.quantity + '</td>' +
            '<td>' + esc(e.mb_ref || '—') + '</td>' +
            '<td>' + esc(e.recorded_by_name || '') +
                (e.witnessed_by ? '<div style="font-size:0.72rem;color:var(--text-secondary);">' +
                 'witnessed: ' + esc(e.witnessed_by) + '</div>' : '') + '</td>' +
            '<td>' + esc(e.remarks || '') + '</td>' +
            '<td class="text-right">' + (e.billed
                ? statusPill('billed', 'good')
                : '<button class="btn btn-sm btn-outline" onclick="removeEntry(' + e.id + ')">Remove</button>') +
            '</td></tr>';
    }).join('') : '<tr><td colspan="7" style="text-align:center;padding:24px;' +
        'color:var(--text-secondary);">Nothing measured yet.</td></tr>';
}

/* --- Recording one measurement ------------------------------------------- */

function showMeasureModal(lineId) {
    var l = MB.lines.filter(function (x) { return x.line_id === lineId; })[0];
    if (!l) return;
    document.getElementById('measure-line-id').value = lineId;
    document.getElementById('measure-title').textContent = l.fg_code + ' — ' + l.description;
    document.getElementById('measure-context').textContent =
        'Ordered ' + l.ordered_qty + ' ' + l.uom + ' · measured ' + l.measured_to_date +
        ' · ' + (l.balance_to_measure >= 0 ? l.balance_to_measure + ' still to do'
                                           : l.over_measured + ' already over the order');
    ['measure-qty', 'measure-ref', 'measure-witness', 'measure-remarks'].forEach(function (id) {
        var e = document.getElementById(id); if (e) e.value = '';
    });
    var d = document.getElementById('measure-date');
    if (d) d.value = new Date().toISOString().slice(0, 10);
    document.getElementById('measure-modal').style.display = 'flex';
    document.getElementById('measure-qty').focus();
}
window.showMeasureModal = showMeasureModal;

function closeMeasureModal() {
    document.getElementById('measure-modal').style.display = 'none';
}
window.closeMeasureModal = closeMeasureModal;

async function saveMeasurement() {
    var qty = parseFloat(document.getElementById('measure-qty').value);
    if (!qty) { showToast('A measurement of nothing is not a measurement', 'error'); return; }
    var res = await fetch('/api/mb/' + MB.wo.id + '/entries', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            line_id: parseInt(document.getElementById('measure-line-id').value),
            quantity: qty,
            measured_on: document.getElementById('measure-date').value,
            mb_ref: document.getElementById('measure-ref').value,
            witnessed_by: document.getElementById('measure-witness').value,
            remarks: document.getElementById('measure-remarks').value,
        }),
    });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not record it', 'error'); return; }
    closeMeasureModal();
    showToast(out.message, out.over_measured ? 'warning' : 'success');
    openMeasurementBook(MB.wo.id);
}
window.saveMeasurement = saveMeasurement;

async function removeEntry(entryId) {
    var res = await fetch('/api/mb/entries/' + entryId,
                          { method: 'DELETE', credentials: 'include' });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not remove it', 'error'); return; }
    showToast(out.message, 'success');
    openMeasurementBook(MB.wo.id);
}
window.removeEntry = removeEntry;

/* --- The bills ------------------------------------------------------------ */

async function loadRaBills(woId) {
    var body = document.getElementById('ra-body');
    if (!body) return;
    var url = '/api/ra-bills' + (woId ? '?work_order_id=' + woId : '');
    var d = await (await fetch(url, { credentials: 'include' })).json();
    RA.bills = d.bills || [];
    RA.summary = d.summary || {};

    var stats = document.getElementById('ra-stats');
    if (stats) {
        var s = RA.summary;
        stats.innerHTML =
            statCard('Claimed', formatCurrency(s.claimed || 0)) +
            statCard('Awaiting certification', String(s.awaiting_certification || 0)) +
            statCard('Certified, unpaid', formatCurrency(s.certified_unpaid || 0)) +
            statCard('Retention held', formatCurrency(s.retention_held || 0)) +
            statCard('Paid', formatCurrency(s.paid || 0));
    }

    body.innerHTML = RA.bills.length ? RA.bills.map(function (b) {
        // Only the move the bill can actually make next.
        var act = '';
        if (b.actions.indexOf('SUBMIT') >= 0)
            act = '<button class="btn btn-sm btn-primary" onclick="raAct(' + b.id + ',\'submit\')">Submit</button>';
        else if (b.actions.indexOf('CERTIFY') >= 0)
            act = '<button class="btn btn-sm btn-primary" onclick="raAct(' + b.id + ',\'certify\')">Certify</button> ' +
                  '<button class="btn btn-sm btn-outline" onclick="raAct(' + b.id + ',\'reject\',true)">Send back</button>';
        else if (b.actions.indexOf('PAY') >= 0)
            act = '<button class="btn btn-sm btn-primary" onclick="raAct(' + b.id + ',\'pay\')">Mark paid</button>';
        return '<tr>' +
            '<td style="font-family:monospace;font-weight:600;">' + esc(b.number) + '</td>' +
            '<td>' + esc(b.work_order) +
                '<div style="font-size:0.75rem;color:var(--text-secondary);">' +
                esc(b.project) + '</div></td>' +
            '<td class="text-right">' + formatCurrency(b.this_bill) + '</td>' +
            '<td class="text-right">' + formatCurrency(b.retention_amount) + '</td>' +
            '<td class="text-right" style="font-weight:600;">' + formatCurrency(b.net_payable) + '</td>' +
            '<td>' + statusPill(b.status, RA_TONE[b.status] || 'calm') +
                (b.certified_by_name ? '<div style="font-size:0.72rem;color:var(--text-secondary);">' +
                 esc(b.certified_by_name) + '</div>' : '') + '</td>' +
            '<td class="text-right">' + act +
                ' <a class="btn btn-sm btn-outline" href="/api/ra-bills/' + b.id +
                '/export.xlsx">Excel</a></td>' +
            '</tr>';
    }).join('') : '<tr><td colspan="7" style="text-align:center;padding:24px;' +
        'color:var(--text-secondary);">No bills yet. Measure the work, then draw one up.</td></tr>';
}
window.loadRaBills = loadRaBills;

async function newRaBill() {
    if (!MB.wo) { showToast('Choose an order first', 'error'); return; }
    var res = await fetch('/api/ra-bills', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ work_order_id: MB.wo.id }),
    });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not draw up a bill', 'error'); return; }
    showToast(out.message, 'success');
    openMeasurementBook(MB.wo.id);
}
window.newRaBill = newRaBill;

async function raAct(billId, action, needsReason) {
    var comments = '';
    if (needsReason) {
        comments = prompt('Why is this going back?');
        if (comments === null) return;
        if (!comments.trim()) { showToast('A reason is required', 'error'); return; }
    }
    var res = await fetch('/api/ra-bills/' + billId + '/' + action, {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ comments: comments }),
    });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not do that', 'error'); return; }
    showToast(out.message, 'success');
    if (MB.wo) openMeasurementBook(MB.wo.id); else loadRaBills();
}
window.raAct = raAct;

/* --- Variations -----------------------------------------------------------
   The book already knows which lines ran past the order. This turns that flag
   into a priced, approved change without anybody retyping it.
   -------------------------------------------------------------------------- */

var VO_TONE = { DRAFT: 'calm', SUBMITTED: 'wait', APPROVED: 'good',
                REJECTED: 'bad', CANCELLED: 'bad' };

async function loadVariations(woId) {
    var body = document.getElementById('vo-body');
    if (!body) return;
    var d = await (await fetch('/api/variations' + (woId ? '?work_order_id=' + woId : ''),
                               { credentials: 'include' })).json();
    var s = d.summary || {};
    var stats = document.getElementById('vo-stats');
    if (stats) stats.innerHTML =
        statCard('Variations raised', String(s.raised || 0)) +
        statCard('Awaiting approval', String(s.awaiting_approval || 0)) +
        statCard('Agreed', formatCurrency(s.approved_value || 0)) +
        statCard('Asked for, not agreed', formatCurrency(s.pending_value || 0));

    body.innerHTML = (d.variations || []).length ? d.variations.map(function (v) {
        // Only the move this variation can actually make next.
        var act = '';
        if (v.actions.indexOf('SUBMIT') >= 0)
            act = '<button class="btn btn-sm btn-primary" onclick="voAct(' + v.id + ',\'submit\')">Submit</button>';
        else if (v.actions.indexOf('APPROVE') >= 0)
            act = '<button class="btn btn-sm btn-primary" onclick="voAct(' + v.id + ',\'approve\')">Approve</button> ' +
                  '<button class="btn btn-sm btn-outline" onclick="voAct(' + v.id + ',\'reject\',true)">Send back</button>';
        return '<tr>' +
            '<td style="font-family:monospace;font-weight:600;">' + esc(v.number) +
                (v.origin === 'measured'
                    ? '<div style="font-size:0.7rem;color:var(--text-secondary);' +
                      'font-family:inherit;font-weight:400;">from the book</div>' : '') + '</td>' +
            '<td>' + esc(v.reason || '—') + '</td>' +
            '<td class="text-right" style="font-weight:600;">' + formatCurrency(v.value) + '</td>' +
            '<td class="text-right">' + formatCurrency(v.order_value_before) +
                ' → ' + formatCurrency(v.order_value_after) + '</td>' +
            '<td>' + statusPill(v.status, VO_TONE[v.status] || 'calm') +
                (v.rejection_reason ? '<div style="font-size:0.72rem;color:var(--danger-color);">' +
                 esc(v.rejection_reason) + '</div>' : '') + '</td>' +
            '<td class="text-right">' + act + '</td></tr>';
    }).join('') : '<tr><td colspan="6" style="text-align:center;padding:24px;' +
        'color:var(--text-secondary);">No variations on this order.</td></tr>';
}
window.loadVariations = loadVariations;

async function offerVariation(woId) {
    // Only shown when there is genuinely an over-run, so a site that is on
    // programme is never nagged about a change it does not need.
    var box = document.getElementById('vo-offer');
    if (!box) return;
    var d = await (await fetch('/api/variations/suggest/' + woId,
                               { credentials: 'include' })).json();
    if (!d.count) { box.style.display = 'none'; return; }
    box.style.display = 'block';
    box.innerHTML =
        '<div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap;' +
        'padding:14px 18px;border-left:3px solid var(--warning-color);' +
        'background:var(--warning-soft,#fff7ed);border-radius:var(--radius-md);">' +
        '<div style="flex:1;min-width:240px;"><strong>' + d.count + ' line' +
        (d.count > 1 ? 's have' : ' has') + ' been built past the order.</strong>' +
        '<div style="font-size:0.85rem;color:var(--text-secondary);margin-top:2px;">' +
        formatCurrency(d.value) + ' of work is done, measured, and not covered by ' +
        'the order. Raise a variation and it becomes billable.</div></div>' +
        '<button class="btn btn-primary" onclick="raiseVariation(' + woId + ')">' +
        'Raise it from the book</button></div>';
}
window.offerVariation = offerVariation;

async function raiseVariation(woId) {
    var reason = prompt('Why did the work run over? (goes on the variation)') || '';
    var res = await fetch('/api/variations', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ work_order_id: woId, reason: reason }),
    });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not raise it', 'error'); return; }
    showToast(out.message, 'success');
    openMeasurementBook(woId);
}
window.raiseVariation = raiseVariation;

async function voAct(voId, action, needsReason) {
    var comments = '';
    if (needsReason) {
        comments = prompt('Why is this going back?');
        if (comments === null) return;
        if (!comments.trim()) { showToast('A reason is required', 'error'); return; }
    }
    var res = await fetch('/api/variations/' + voId + '/' + action, {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ comments: comments }),
    });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not do that', 'error'); return; }
    showToast(out.message, 'success');
    if (MB.wo) openMeasurementBook(MB.wo.id);
}
window.voAct = voAct;
