/* ===========================================================================
   rfq.js - the enquiry to suppliers, their quotes, the comparative statement.

   Lines down the side, suppliers across the top, the lowest in each row
   marked, and each supplier's total landed at site underneath - freight in,
   because a cheaper rate with a lorry charge on top is not cheaper. The award
   makes the purchase orders; choosing anybody but the lowest asks why.
   =========================================================================== */

var RFQ = { list: [], current: null, data: null };

async function loadRfqs() {
    var body = document.getElementById('rfq-body');
    if (!body) return;
    var d = await (await fetch('/api/rfqs', { credentials: 'include' })).json();
    RFQ.list = d.rfqs || [];
    var s = d.summary || {};
    document.getElementById('rfq-stats').innerHTML =
        statCard('Open enquiries', String(s.open || 0)) +
        statCard('Fewer than three quotes', String(s.waiting_for_quotes || 0)) +
        statCard('Awarded', String(s.awarded || 0));
    var tone = { OPEN: 'wait', AWARDED: 'good', CANCELLED: 'calm' };
    body.innerHTML = RFQ.list.length ? RFQ.list.map(function (r) {
        return '<tr><td style="font-family:monospace;font-weight:600;">' + esc(r.number) + '</td>' +
            '<td>' + esc(r.title) + '<div style="font-size:0.72rem;color:var(--text-secondary);">' +
                esc(r.project || '') + '</div></td>' +
            '<td class="text-right">' + r.lines + '</td>' +
            '<td class="text-right">' + r.quotes + (r.status === 'OPEN' && r.quotes < 3
                ? ' <span style="font-size:0.7rem;color:var(--warning-color);">need 3</span>' : '') + '</td>' +
            '<td>' + esc(r.needed_by || '—') + '</td>' +
            '<td>' + statusPill(r.status, tone[r.status] || 'calm') + '</td>' +
            '<td class="text-right"><button class="btn btn-sm btn-primary" onclick="openRfq(' + r.id + ')">' +
                (r.status === 'OPEN' ? 'Quotes &amp; compare' : 'Statement') + '</button></td></tr>';
    }).join('') : '<tr><td colspan="7" style="text-align:center;padding:26px;color:var(--text-secondary);">' +
        'No enquiries yet. Ask three suppliers before an order goes out.</td></tr>';
    if (RFQ.current) openRfq(RFQ.current);
}
window.loadRfqs = loadRfqs;

/* --- A new enquiry ------------------------------------------------------------ */

async function newRfq() {
    try {
        var d = await (await fetch('/api/jobs', { credentials: 'include' })).json();
        document.getElementById('rfqn-job').innerHTML = '<option value="">No particular project</option>' +
            (d.jobs || d || []).map(function (j) {
                return '<option value="' + j.id + '">' + esc((j.number || '') + ' — ' + j.name) + '</option>';
            }).join('');
    } catch (e) {}
    try {
        var w = await (await fetch('/api/erp/work-orders', { credentials: 'include' })).json();
        document.getElementById('rfqn-wo').innerHTML = '<option value="">&mdash; or build it from a work order&rsquo;s budget &mdash;</option>' +
            (w.work_orders || []).filter(function (x) { return x.status !== 'Draft'; }).map(function (x) {
                return '<option value="' + x.id + '">' + esc(x.number + ' — ' + (x.job_name || '')) + '</option>';
            }).join('');
    } catch (e) {}
    document.getElementById('rfqn-title').value = '';
    document.getElementById('rfqn-needed').value = '';
    RFQ.newLines = [{ item_code: '', description: '', uom: 'Bags', qty: '' }];
    rfqNewLines();
    openModal('rfq-new-modal');
    document.getElementById('rfqn-title').focus();
}
window.newRfq = newRfq;

function rfqNewLines() {
    var units = (window.VOCAB && window.VOCAB.units) || ['cum', 'sqm', 'rmt', 'Nos', 'MT', 'Kgs', 'Bags', 'Litres', 'Lot'];
    document.getElementById('rfqn-lines').innerHTML = RFQ.newLines.map(function (l, i) {
        var set = function (k) { return ' oninput="RFQ.newLines[' + i + '].' + k + '=this.value"'; };
        return '<tr><td><input class="form-control" style="min-width:90px;" placeholder="code" value="' + esc(l.item_code) + '"' + set('item_code') + '></td>' +
            '<td><input class="form-control" style="min-width:200px;" placeholder="What" value="' + esc(l.description) + '"' + set('description') + '></td>' +
            '<td><select class="form-control" onchange="RFQ.newLines[' + i + '].uom=this.value">' + units.map(function (u) {
                return '<option' + (u === l.uom ? ' selected' : '') + '>' + esc(u) + '</option>'; }).join('') + '</select></td>' +
            '<td><input type="number" step="any" class="form-control text-right" style="width:100px;" value="' + esc(String(l.qty)) + '"' + set('qty') + '></td>' +
            '<td><button class="btn btn-sm btn-outline" onclick="RFQ.newLines.splice(' + i + ',1);rfqNewLines()">&times;</button></td></tr>';
    }).join('');
}
window.rfqNewLines = rfqNewLines;

async function saveNewRfq() {
    var wo = parseInt(document.getElementById('rfqn-wo').value) || 0;
    var res;
    if (wo) {
        res = await fetch('/api/rfqs/from-work-order/' + wo, { method: 'POST', credentials: 'include' });
    } else {
        res = await fetch('/api/rfqs', {
            method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title: document.getElementById('rfqn-title').value,
                job_id: parseInt(document.getElementById('rfqn-job').value) || null,
                needed_by: document.getElementById('rfqn-needed').value,
                lines: RFQ.newLines.map(function (l) {
                    return { item_code: l.item_code, description: l.description, uom: l.uom,
                             qty: parseFloat(l.qty) || 0 }; }) }) });
    }
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not open it', 'error'); return; }
    closeModal('rfq-new-modal');
    showToast(out.message, 'success');
    RFQ.current = out.rfq.id;
    loadRfqs();
}
window.saveNewRfq = saveNewRfq;

/* --- The statement ---------------------------------------------------------------- */

async function openRfq(id) {
    RFQ.current = id;
    var d = await (await fetch('/api/rfqs/' + id, { credentials: 'include' })).json();
    RFQ.data = d;
    var r = d.rfq, open = r.status === 'OPEN';
    var sups = d.suppliers || [];
    var head = '<th>Item</th><th class="text-right">Qty</th>' + sups.map(function (s) {
        return '<th class="text-right" style="min-width:130px;">' + esc(s.supplier_name) +
            (s.rank ? ' <span style="font-size:0.66rem;padding:1px 5px;border-radius:4px;background:' +
                (s.is_l1 ? 'var(--success-color)' : 'var(--border-color)') + ';color:' +
                (s.is_l1 ? '#fff' : 'inherit') + ';">' + s.rank + '</span>' : '') + '</th>';
    }).join('');
    var rows = d.lines.map(function (l) {
        return '<tr><td>' + esc(l.description) + '<div style="font-size:0.7rem;color:var(--text-secondary);">' +
                esc(l.item_code) + (l.spread_percent ? ' &middot; spread ' + l.spread_percent + '%' : '') +
                (l.awarded_supplier ? ' &middot; <strong>awarded ' + esc(l.awarded_supplier) + '</strong>' : '') + '</div></td>' +
            '<td class="text-right" style="white-space:nowrap;">' + l.qty + ' ' + esc(l.uom) + '</td>' +
            sups.map(function (s) {
                var o = (l.offers || []).filter(function (x) { return x.supplier_name === s.supplier_name; })[0];
                if (!o) return '<td class="text-right" style="color:var(--text-secondary);">not quoted</td>';
                var low = o.supplier_name === l.lowest;
                return '<td class="text-right" style="white-space:nowrap;' + (low ? 'background:rgba(16,185,129,0.10);font-weight:700;' : '') + '">' +
                    formatCurrency(o.rate) + '<div style="font-size:0.7rem;font-weight:400;color:var(--text-secondary);">' +
                    formatCurrency(o.amount) + ' +' + o.tax_percent + '%</div></td>';
            }).join('') + '</tr>';
    }).join('');
    var foot = [['Basic', 'basic'], ['Tax', 'tax'], ['Freight', 'freight'], ['Landed at site', 'landed']].map(function (x) {
        return '<tr style="' + (x[1] === 'landed' ? 'font-weight:700;border-top:2px solid var(--border-color);' : '') + '">' +
            '<td colspan="2" class="text-right">' + x[0] + '</td>' + sups.map(function (s) {
                return '<td class="text-right" style="white-space:nowrap;' + (s.is_l1 && x[1] === 'landed' ? 'color:var(--success-color);' : '') + '">' +
                    formatCurrency(s[x[1]]) + '</td>'; }).join('') + '</tr>';
    }).join('') +
        '<tr><td colspan="2" class="text-right" style="font-size:0.76rem;">Delivery / payment</td>' + sups.map(function (s) {
            return '<td class="text-right" style="font-size:0.72rem;">' + (s.delivery_days ? s.delivery_days + ' days' : '—') +
                '<br>' + esc(s.payment_terms || '—') + (s.complete ? '' : '<br><span style="color:var(--warning-color);">incomplete</span>') + '</td>';
        }).join('') + '</tr>';

    document.getElementById('rfq-detail').innerHTML = '<div class="widget" style="margin-top:18px;">' +
        '<div class="widget-header"><h3>Comparative statement &mdash; ' + esc(r.number) + ' ' + esc(r.title) + '</h3>' +
        '<div style="display:flex;gap:8px;flex-wrap:wrap;">' +
        (open ? '<button class="btn btn-sm btn-outline" onclick="rfqQuote()">+ Quote</button>' +
                (sups.length ? '<button class="btn btn-sm btn-primary" onclick="rfqAward()">Award</button>' : '') : '') +
        '<button class="btn btn-sm btn-outline" onclick="window.print()">Print</button>' +
        '<button class="btn btn-sm btn-outline" onclick="RFQ.current=null;document.getElementById(\'rfq-detail\').innerHTML=\'\'">Close</button></div></div>' +
        (sups.length
            ? '<div style="padding:10px 18px;font-size:0.84rem;">' +
              (d.l1 ? 'L1 landed: <strong>' + esc(d.l1) + '</strong> at ' + formatCurrency(d.l1_landed) +
                  (d.saving_vs_l2 ? ' &mdash; ' + formatCurrency(d.saving_vs_l2) + ' under L2' : '') + '. ' : '') +
              'Lowest in every line, from whoever quoted it: ' + formatCurrency(d.lowest_per_line_basic) + ' basic.' +
              (r.award_reason ? '<div style="margin-top:6px;"><strong>Why not the lowest:</strong> ' + esc(r.award_reason) + '</div>' : '') +
              '</div>' : '') +
        '<div class="table-responsive"><table class="data-table"><thead><tr>' + head + '</tr></thead><tbody>' + rows +
        '</tbody>' + (sups.length ? '<tfoot>' + foot + '</tfoot>' : '') + '</table></div>' +
        (!sups.length ? '<p style="padding:18px;color:var(--text-secondary);">No quotes yet. Record each supplier\'s answer with + Quote.</p>' : '') +
        '</div>';
    document.getElementById('rfq-detail').scrollIntoView({ block: 'start', behavior: 'smooth' });
}
window.openRfq = openRfq;

function rfqQuote() {
    var d = RFQ.data;
    document.getElementById('rfqq-title').textContent = d.rfq.number;
    ['supplier', 'ref', 'terms', 'freight', 'days'].forEach(function (k) {
        document.getElementById('rfqq-' + k).value = ''; });
    document.getElementById('rfqq-date').value = localDate(new Date());
    document.getElementById('rfqq-lines').innerHTML = d.lines.map(function (l, i) {
        return '<tr><td>' + esc(l.description) + '<div style="font-size:0.7rem;color:var(--text-secondary);">' +
            l.qty + ' ' + esc(l.uom) + '</div></td>' +
            '<td><input type="number" step="any" class="form-control text-right" id="rfqq-rate-' + i + '" placeholder="rate"></td>' +
            '<td><input type="number" step="0.5" class="form-control text-right" style="width:80px;" id="rfqq-tax-' + i + '" value="18"></td></tr>';
    }).join('');
    try {
        fetch('/api/suppliers', { credentials: 'include' }).then(function (r) { return r.json(); }).then(function (s) {
            document.getElementById('rfqq-suppliers').innerHTML = (s.suppliers || []).map(function (x) {
                return '<option value="' + esc(x.name) + '">'; }).join('');
        });
    } catch (e) {}
    openModal('rfq-quote-modal');
    document.getElementById('rfqq-supplier').focus();
}
window.rfqQuote = rfqQuote;

async function saveRfqQuote() {
    var d = RFQ.data;
    var lines = d.lines.map(function (l, i) {
        return { rfq_line_id: l.rfq_line_id,
                 rate: parseFloat(document.getElementById('rfqq-rate-' + i).value) || 0,
                 tax_percent: parseFloat(document.getElementById('rfqq-tax-' + i).value) || 0 };
    });
    var val = function (k) { return document.getElementById('rfqq-' + k).value; };
    var res = await fetch('/api/rfqs/' + d.rfq.id + '/quotes', {
        method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ supplier_name: val('supplier'), quote_ref: val('ref'), quote_date: val('date'),
            payment_terms: val('terms'), freight: parseFloat(val('freight')) || 0,
            delivery_days: parseInt(val('days')) || 0, lines: lines }) });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not record it', 'error'); return; }
    closeModal('rfq-quote-modal');
    showToast(out.message, 'success');
    loadRfqs();
}
window.saveRfqQuote = saveRfqQuote;

function rfqAward() {
    var d = RFQ.data;
    document.getElementById('rfqa-mode').value = 'lowest_per_line';
    document.getElementById('rfqa-supplier').innerHTML = d.suppliers.filter(function (s) { return s.complete; })
        .map(function (s) { return '<option' + (s.is_l1 ? ' selected' : '') + '>' + esc(s.supplier_name) + '</option>'; }).join('');
    document.getElementById('rfqa-reason').value = '';
    rfqAwardMode();
    openModal('rfq-award-modal');
}
window.rfqAward = rfqAward;

function rfqAwardMode() {
    document.getElementById('rfqa-one').style.display =
        document.getElementById('rfqa-mode').value === 'one_supplier' ? '' : 'none';
}
window.rfqAwardMode = rfqAwardMode;

async function saveRfqAward() {
    var res = await fetch('/api/rfqs/' + RFQ.data.rfq.id + '/award', {
        method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode: document.getElementById('rfqa-mode').value,
            supplier_name: document.getElementById('rfqa-supplier').value,
            reason: document.getElementById('rfqa-reason').value }) });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not award it', 'error'); return; }
    closeModal('rfq-award-modal');
    showToast(out.message + ' They are drafts under Purchase Orders.', 'success');
    loadRfqs();
}
window.saveRfqAward = saveRfqAward;
