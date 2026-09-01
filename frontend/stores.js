/* ===========================================================================
   stores.js - what arrived at the gate, and whether the three papers agree.

   A purchase order says what was agreed. A bill says what is being charged.
   Until something records what came off the lorry, those two can differ by
   any amount and nobody finds out. This screen is that third number, and the
   match report that puts all three side by side.
   =========================================================================== */

var GRN = { list: [], summary: {}, current: null, openOrders: [] };
var MATCH = { orders: [], summary: {} };

var GRN_TONE = { DRAFT: 'calm', POSTED: 'good', CANCELLED: 'bad' };

// Only the two that cost money are shouted about. The rest are states an
// order passes through on the way to being settled.
var VERDICT_TONE = {
    OVER_BILLED: 'bad', AWAITING_RECEIPT: 'bad', OVER_RECEIVED: 'wait',
    AWAITING_BILL: 'wait', PART_BILLED: 'calm',
    AWAITING_DELIVERY: 'calm', MATCHED: 'good',
};
var VERDICT_LABEL = {
    OVER_BILLED: 'Billed over receipt', AWAITING_RECEIPT: 'Nothing received',
    OVER_RECEIVED: 'Over-received', AWAITING_BILL: 'To be billed',
    PART_BILLED: 'Part billed', AWAITING_DELIVERY: 'Awaiting delivery',
    MATCHED: 'Matched',
};

async function loadStores() {
    await Promise.all([loadReceipts(), loadOpenOrders(), loadMatch()]);
}
window.loadStores = loadStores;

/* --- The register --------------------------------------------------------- */

async function loadReceipts() {
    var body = document.getElementById('grn-body');
    if (!body) return;
    var d = await (await fetch('/api/grn', { credentials: 'include' })).json();
    GRN.list = d.goods_receipts || [];
    GRN.summary = d.summary || {};

    var stats = document.getElementById('grn-stats');
    if (stats) {
        var s = GRN.summary;
        stats.innerHTML =
            statCard('Receipts', String(s.count || 0)) +
            statCard('Not yet posted', String(s.awaiting_posting || 0)) +
            statCard('Accepted', formatCurrency(s.accepted_value || 0)) +
            statCard('Rejected', formatCurrency(s.rejected_value || 0));
    }

    body.innerHTML = GRN.list.length ? GRN.list.map(function (g) {
        var act = '';
        if (g.actions.indexOf('POST') >= 0)
            act = '<button class="btn btn-sm btn-primary" onclick="postGrn(' + g.id + ')">Post</button> ';
        return '<tr>' +
            '<td style="font-family:monospace;font-weight:600;">' + esc(g.number) +
                (g.challan_number ? '<div style="font-size:0.72rem;font-family:inherit;' +
                 'font-weight:400;color:var(--text-secondary);">challan ' +
                 esc(g.challan_number) + '</div>' : '') + '</td>' +
            '<td>' + esc(g.supplier_name) +
                '<div style="font-size:0.75rem;color:var(--text-secondary);">' +
                esc(g.purchase_order) + (g.project ? ' · ' + esc(g.project) : '') +
                '</div></td>' +
            '<td>' + esc(g.received_on) + '</td>' +
            '<td class="text-right">' + formatCurrency(g.accepted_value) + '</td>' +
            '<td class="text-right">' + (g.rejected_value
                ? '<span style="color:var(--warning-color);">' +
                  formatCurrency(g.rejected_value) + '</span>' : '—') + '</td>' +
            '<td>' + statusPill(g.status, GRN_TONE[g.status] || 'calm') + '</td>' +
            '<td class="text-right">' + act +
                '<button class="btn btn-sm btn-outline" onclick="openGrn(' + g.id + ')">Open</button> ' +
                '<a class="btn btn-sm btn-outline" href="/api/grn/' + g.id +
                '/export.xlsx">Excel</a></td>' +
            '</tr>';
    }).join('') : '<tr><td colspan="7" style="text-align:center;padding:26px;' +
        'color:var(--text-secondary);">Nothing received yet. Take a delivery ' +
        'against an approved order.</td></tr>';
}
window.loadReceipts = loadReceipts;

/* --- Taking a delivery ---------------------------------------------------- */

async function loadOpenOrders() {
    var pick = document.getElementById('grn-order');
    if (!pick) return;
    var d = await (await fetch('/api/grn/open-orders', { credentials: 'include' })).json();
    GRN.openOrders = d.orders || [];
    pick.innerHTML = GRN.openOrders.length
        ? GRN.openOrders.map(function (o) {
            return '<option value="' + o.id + '">' + esc(o.number) + ' — ' +
                esc(o.supplier_name) + ' (' + formatCurrency(o.pending_value) +
                ' to come)</option>';
          }).join('')
        : '<option value="">No approved orders with material still to come</option>';
}

function showReceiveModal() {
    if (!GRN.openOrders.length) {
        showToast('Approve a purchase order first — there is nothing to receive against',
                  'error');
        return;
    }
    ['grn-challan', 'grn-invoice', 'grn-vehicle', 'grn-store', 'grn-inspector'
    ].forEach(function (id) { var e = document.getElementById(id); if (e) e.value = ''; });
    var d = document.getElementById('grn-date');
    if (d) d.value = new Date().toISOString().slice(0, 10);
    document.getElementById('grn-modal').style.display = 'flex';
}
window.showReceiveModal = showReceiveModal;

function closeReceiveModal() {
    document.getElementById('grn-modal').style.display = 'none';
}
window.closeReceiveModal = closeReceiveModal;

async function startReceipt() {
    var order = document.getElementById('grn-order').value;
    if (!order) { showToast('Choose an order', 'error'); return; }
    var res = await fetch('/api/grn', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            purchase_order_id: parseInt(order),
            received_on: document.getElementById('grn-date').value,
            challan_number: document.getElementById('grn-challan').value,
            invoice_number: document.getElementById('grn-invoice').value,
            vehicle_number: document.getElementById('grn-vehicle').value,
            store_location: document.getElementById('grn-store').value,
            inspected_by: document.getElementById('grn-inspector').value,
        }),
    });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not open a receipt', 'error'); return; }
    closeReceiveModal();
    GRN.current = out;
    renderGrnLines();
    showToast(out.number + ' opened — check the quantities against the lorry', 'success');
    loadReceipts();
    loadOpenOrders();
}
window.startReceipt = startReceipt;

async function openGrn(id) {
    var res = await fetch('/api/grn/' + id, { credentials: 'include' });
    if (!res.ok) { showToast('Could not open that receipt', 'error'); return; }
    GRN.current = await res.json();
    renderGrnLines();
}
window.openGrn = openGrn;

function renderGrnLines() {
    var wrap = document.getElementById('grn-detail');
    var g = GRN.current;
    if (!wrap) return;
    if (!g) { wrap.style.display = 'none'; return; }
    wrap.style.display = '';

    document.getElementById('grn-detail-title').textContent =
        g.number + ' — ' + g.supplier_name + ' against ' + g.purchase_order;
    document.getElementById('grn-detail-meta').innerHTML =
        statusPill(g.status, GRN_TONE[g.status] || 'calm') +
        ' <span style="color:var(--text-secondary);font-size:0.82rem;">' +
        esc(g.received_on) + (g.challan_number ? ' · challan ' + esc(g.challan_number) : '') +
        (g.vehicle_number ? ' · ' + esc(g.vehicle_number) : '') +
        (g.received_by_name ? ' · received by ' + esc(g.received_by_name) : '') +
        '</span>';

    var editable = g.editable;
    document.getElementById('grn-lines').innerHTML = g.lines.map(function (l, i) {
        var balance = l.ordered_qty - l.previously_received;
        return '<tr>' +
            '<td style="font-family:monospace;">' + esc(l.item_code || '—') +
                '<div style="font-size:0.75rem;font-family:inherit;' +
                'color:var(--text-secondary);">' + esc(l.description) + '</div></td>' +
            '<td class="text-right">' + l.ordered_qty + ' ' + esc(l.uom) +
                (l.previously_received
                    ? '<div style="font-size:0.72rem;color:var(--text-secondary);">' +
                      l.previously_received + ' already in</div>' : '') + '</td>' +
            '<td class="text-right">' + balance + '</td>' +
            '<td>' + (editable
                ? '<input type="number" step="any" class="form-control input-sm" ' +
                  'id="grnl-rec-' + i + '" value="' + l.received_qty +
                  '" oninput="grnLineChanged(' + i + ')">'
                : l.received_qty) + '</td>' +
            '<td>' + (editable
                ? '<input type="number" step="any" class="form-control input-sm" ' +
                  'id="grnl-rej-' + i + '" value="' + l.rejected_qty +
                  '" oninput="grnLineChanged(' + i + ')">'
                : l.rejected_qty) + '</td>' +
            '<td class="text-right" id="grnl-acc-' + i + '" style="font-weight:600;">' +
                l.accepted_qty + '</td>' +
            '<td>' + (editable
                ? '<input type="text" class="form-control input-sm" id="grnl-why-' + i +
                  '" value="' + esc(l.rejection_reason) + '" placeholder="If rejected, why">'
                : esc(l.rejection_reason || '')) + '</td>' +
            '<td class="text-right">' + formatCurrency(l.amount) + '</td>' +
            '</tr>';
    }).join('');

    document.getElementById('grn-detail-actions').innerHTML = editable
        ? '<button class="btn btn-outline" onclick="saveGrn()">Save</button> ' +
          '<button class="btn btn-primary" onclick="saveGrn(true)">Save and post</button> ' +
          '<button class="btn btn-outline" onclick="discardGrn()">Discard</button>'
        : (g.actions.indexOf('CANCEL') >= 0
            ? '<button class="btn btn-outline" onclick="cancelGrn()">Cancel this receipt</button>'
            : '');
    document.getElementById('grn-detail-totals').innerHTML =
        'Arrived ' + formatCurrency(g.received_value) +
        ' · accepted <strong>' + formatCurrency(g.accepted_value) + '</strong>' +
        (g.rejected_value ? ' · rejected ' + formatCurrency(g.rejected_value) : '');
}

// Accepted is shown as it is derived rather than typed, so a storekeeper sees
// the number that will actually be billed before they commit to it.
function grnLineChanged(i) {
    var rec = parseFloat((document.getElementById('grnl-rec-' + i) || {}).value) || 0;
    var rej = parseFloat((document.getElementById('grnl-rej-' + i) || {}).value) || 0;
    var cell = document.getElementById('grnl-acc-' + i);
    if (!cell) return;
    var acc = rec - rej;
    cell.textContent = acc;
    cell.style.color = acc < 0 ? 'var(--danger-color)' : '';
}
window.grnLineChanged = grnLineChanged;

function grnLinePayload() {
    return GRN.current.lines.map(function (l, i) {
        return {
            id: l.id,
            received_qty: parseFloat((document.getElementById('grnl-rec-' + i) || {}).value) || 0,
            rejected_qty: parseFloat((document.getElementById('grnl-rej-' + i) || {}).value) || 0,
            rejection_reason: (document.getElementById('grnl-why-' + i) || {}).value || '',
        };
    });
}

async function saveGrn(thenPost) {
    var res = await fetch('/api/grn/' + GRN.current.id, {
        method: 'PUT', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ lines: grnLinePayload() }),
    });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not save', 'error'); return; }
    GRN.current = out;
    if (thenPost) { await postGrn(out.id); return; }
    renderGrnLines();
    showToast('Saved.', 'success');
    loadReceipts();
}
window.saveGrn = saveGrn;

async function postGrn(id) {
    var res = await fetch('/api/grn/' + id + '/post',
                          { method: 'POST', credentials: 'include' });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not post it', 'error'); return; }
    GRN.current = out.goods_receipt;
    renderGrnLines();
    showToast(out.message, out.over_received.length ? 'warning' : 'success');
    loadReceipts();
    loadOpenOrders();
    loadMatch();
}
window.postGrn = postGrn;

async function cancelGrn() {
    var why = prompt('Why is this receipt being cancelled?');
    if (why === null) return;
    if (!why.trim()) { showToast('A reason is required', 'error'); return; }
    var res = await fetch('/api/grn/' + GRN.current.id + '/cancel', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ comments: why }),
    });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not cancel it', 'error'); return; }
    showToast(out.message, 'success');
    GRN.current = null;
    renderGrnLines();
    loadStores();
}
window.cancelGrn = cancelGrn;

async function discardGrn() {
    var res = await fetch('/api/grn/' + GRN.current.id,
                          { method: 'DELETE', credentials: 'include' });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not discard it', 'error'); return; }
    showToast(out.message, 'success');
    GRN.current = null;
    renderGrnLines();
    loadStores();
}
window.discardGrn = discardGrn;

/* --- The match ------------------------------------------------------------ */

async function loadMatch() {
    var body = document.getElementById('match-body');
    if (!body) return;
    var only = document.getElementById('match-exceptions');
    var url = '/api/match/three-way' + (only && only.checked ? '?only_exceptions=true' : '');
    var d = await (await fetch(url, { credentials: 'include' })).json();
    MATCH.orders = d.orders || [];
    MATCH.summary = d.summary || {};

    var stats = document.getElementById('match-stats');
    if (stats) {
        var s = MATCH.summary;
        stats.innerHTML =
            statCard('Orders', String(s.orders || 0)) +
            statCard('Agreeing', String(s.matched || 0)) +
            statCard('Need a look', String(s.exceptions || 0)) +
            statCard('Billed over receipt', formatCurrency(s.over_billed || 0)) +
            statCard('Received, not billed', formatCurrency(s.accrual_owed || 0));
    }

    body.innerHTML = MATCH.orders.length ? MATCH.orders.map(function (r) {
        return '<tr>' +
            '<td style="font-family:monospace;font-weight:600;">' + esc(r.number) +
                '<div style="font-size:0.75rem;font-family:inherit;font-weight:400;' +
                'color:var(--text-secondary);">' + esc(r.supplier_name) + '</div></td>' +
            '<td>' + esc(r.project || '—') + '</td>' +
            '<td class="text-right">' + formatCurrency(r.ordered_value) + '</td>' +
            '<td class="text-right">' + formatCurrency(r.received_value) +
                '<div style="font-size:0.72rem;color:var(--text-secondary);">' +
                r.receipt_count + ' receipt' + (r.receipt_count === 1 ? '' : 's') +
                '</div></td>' +
            '<td class="text-right">' + formatCurrency(r.billed_value) +
                '<div style="font-size:0.72rem;color:var(--text-secondary);">' +
                r.bill_count + ' bill' + (r.bill_count === 1 ? '' : 's') + '</div></td>' +
            '<td>' + statusPill(VERDICT_LABEL[r.verdict] || r.verdict,
                                VERDICT_TONE[r.verdict] || 'calm') +
                '<div style="font-size:0.72rem;color:var(--text-secondary);max-width:280px;">' +
                esc(r.note) + '</div></td>' +
            '</tr>';
    }).join('') : '<tr><td colspan="6" style="text-align:center;padding:26px;' +
        'color:var(--text-secondary);">Nothing to compare yet.</td></tr>';
}
window.loadMatch = loadMatch;
