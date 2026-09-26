/* ===========================================================================
   stock.js - what is in the store, what went to site, and what it cost.

   The store's balance is the sum of its movements. Nothing on this screen
   edits a movement; corrections are posted, which is why the figures can be
   trusted three months later when a bill is disputed.
   =========================================================================== */

var STOCK = { rows: [], summary: {}, lowOnly: false };
var ISSUE = { list: [], current: null };

/* --- What is in the store ------------------------------------------------- */

async function loadStock() {
    var body = document.getElementById('stock-body');
    if (!body) return;
    var d = await (await fetch('/api/stock' + (STOCK.lowOnly ? '?low_only=true' : ''),
                               { credentials: 'include' })).json();
    STOCK.rows = d.stock || [];
    STOCK.summary = d.summary || {};

    var s = STOCK.summary;
    var stats = document.getElementById('stock-stats');
    if (stats) stats.innerHTML =
        statCard('Items held', String(s.items_held || 0)) +
        statCard('Value in the store', formatCurrency(s.value_on_hand || 0)) +
        statCard('Below reorder level', String(s.below_reorder || 0)) +
        statCard('Going negative', String(s.negative_lines || 0));

    body.innerHTML = STOCK.rows.length ? STOCK.rows.map(function (r) {
        return '<tr>' +
            '<td style="font-family:monospace;font-weight:600;">' + esc(r.item_code) +
                '<div style="font-size:0.75rem;font-family:inherit;font-weight:400;' +
                'color:var(--text-secondary);">' + esc(r.item_name) + '</div></td>' +
            '<td class="text-right">' + r.received + '</td>' +
            '<td class="text-right">' + r.issued + '</td>' +
            '<td class="text-right" style="font-weight:700;' +
                (r.negative ? 'color:var(--danger-color);' :
                 r.below_level ? 'color:var(--warning-color);' : '') + '">' +
                r.on_hand + ' ' + esc(r.uom) +
                (r.below_level ? '<div style="font-size:0.7rem;font-weight:400;">' +
                 'below ' + r.reorder_level + '</div>' : '') +
                (r.negative ? '<div style="font-size:0.7rem;font-weight:400;">' +
                 'more issued than received</div>' : '') + '</td>' +
            '<td class="text-right">' + formatCurrency(r.rate) + '</td>' +
            '<td class="text-right" style="font-weight:600;">' + formatCurrency(r.value) + '</td>' +
            '<td class="text-right">' +
                '<button class="btn btn-sm btn-outline" onclick="showLedger(\'' +
                esc(r.item_code) + '\')">Ledger</button> ' +
                // A count adjusts the books; that is the office's to do.
                (can('workorders.manage') ? '<button class="btn btn-sm btn-outline" onclick="countStock(\'' +
                esc(r.item_code) + '\',' + r.on_hand + ')">Count</button>' : '') + '</td>' +
            '</tr>';
    }).join('') : '<tr><td colspan="7" style="text-align:center;padding:30px;' +
        'color:var(--text-secondary);">Nothing in the store yet. Material arrives ' +
        'by posting a goods receipt.</td></tr>';

    loadIssues();
}
window.loadStock = loadStock;

function toggleLowStock(el) {
    STOCK.lowOnly = el.checked;
    loadStock();
}
window.toggleLowStock = toggleLowStock;

async function showLedger(code) {
    var d = await (await fetch('/api/stock/' + encodeURIComponent(code) + '/ledger',
                               { credentials: 'include' })).json();
    document.getElementById('ledger-title').textContent =
        code + ' — ' + (d.item_name || '');
    document.getElementById('ledger-summary').textContent =
        d.on_hand + ' ' + (d.uom || '') + ' on hand · ' + formatCurrency(d.rate) +
        ' each · ' + formatCurrency(d.value) + ' in the store';
    document.getElementById('ledger-body').innerHTML = (d.movements || []).map(function (m) {
        return '<tr>' +
            '<td>' + esc(m.moved_on) + '</td>' +
            '<td>' + statusPill(m.kind.toLowerCase(),
                                m.quantity < 0 ? 'wait' : 'good') + '</td>' +
            '<td class="text-right"' + (m.quantity < 0
                ? ' style="color:var(--warning-color);"' : '') + '>' + m.quantity + '</td>' +
            '<td class="text-right">' + formatCurrency(m.rate) + '</td>' +
            '<td class="text-right" style="font-weight:600;">' + m.balance + '</td>' +
            '<td style="font-family:monospace;font-size:0.8rem;">' +
                esc(m.source_ref || '—') + '</td>' +
            '<td>' + esc(m.remarks || '') + '</td></tr>';
    }).join('') || '<tr><td colspan="7" style="text-align:center;padding:20px;' +
        'color:var(--text-secondary);">No movements.</td></tr>';
    document.getElementById('ledger-modal').style.display = 'flex';
}
window.showLedger = showLedger;

function closeLedger() {
    document.getElementById('ledger-modal').style.display = 'none';
}
window.closeLedger = closeLedger;

async function countStock(code, book) {
    var counted = prompt('Physical count for ' + code +
                         '\n\nThe book says ' + book + '. What did you count?');
    if (counted === null) return;
    var n = parseFloat(counted);
    if (isNaN(n)) { showToast('That is not a number', 'error'); return; }
    var res = await fetch('/api/stock/adjustments', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ item_code: code, counted: n,
                               remarks: 'Physical count' }),
    });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not post it', 'error'); return; }
    showToast(out.message, out.difference ? 'warning' : 'success');
    loadStock();
}
window.countStock = countStock;

/* --- Issuing to site ------------------------------------------------------ */

async function loadIssues() {
    var body = document.getElementById('issue-body');
    if (!body) return;
    var d = await (await fetch('/api/stock-issues', { credentials: 'include' })).json();
    ISSUE.list = d.issues || [];
    var s = d.summary || {};
    var stats = document.getElementById('issue-stats');
    if (stats) stats.innerHTML =
        statCard('Issue notes', String(s.notes || 0)) +
        statCard('Not yet posted', String(s.not_yet_posted || 0)) +
        statCard('Issued to site', formatCurrency(s.issued_value || 0));

    body.innerHTML = ISSUE.list.length ? ISSUE.list.map(function (i) {
        return '<tr>' +
            '<td style="font-family:monospace;font-weight:600;">' + esc(i.number) + '</td>' +
            '<td>' + esc(i.work_order || '—') +
                (i.purpose ? '<div style="font-size:0.75rem;color:var(--text-secondary);">' +
                 esc(i.purpose) + '</div>' : '') + '</td>' +
            '<td>' + esc(i.issued_to || '—') + '</td>' +
            '<td>' + esc(i.issued_on) + '</td>' +
            '<td class="text-right" style="font-weight:600;">' +
                formatCurrency(i.total_value) + '</td>' +
            '<td>' + statusPill(i.status,
                i.status === 'POSTED' ? 'good' : i.status === 'CANCELLED' ? 'bad' : 'calm') +
                '</td>' +
            '<td class="text-right" style="white-space:nowrap;">' +
                '<a class="btn btn-sm btn-outline" target="_blank" rel="noopener" href="/api/stock-issues/' + i.id + '/document.pdf">Slip</a> ' +
                (i.status === 'DRAFT'
                ? '<button class="btn btn-sm btn-primary" onclick="postIssue(' + i.id +
                  ')">Post it</button> '
                : '') + (i.status !== 'CANCELLED' && can('workorders.manage')
                ? '<button class="btn btn-sm btn-outline" onclick="cancelIssue(' + i.id +
                  ')">Cancel</button>' : '') + '</td>' +
            '</tr>';
    }).join('') : '<tr><td colspan="7" style="text-align:center;padding:24px;' +
        'color:var(--text-secondary);">Nothing issued yet.</td></tr>';
}
window.loadIssues = loadIssues;

async function showIssueModal() {
    var orders = await (await fetch('/api/erp/work-orders',
                                    { credentials: 'include' })).json();
    var open = (orders.work_orders || []).filter(function (w) {
        return w.status !== 'Draft';
    });
    document.getElementById('issue-order').innerHTML =
        '<option value="">Not against a particular order</option>' +
        open.map(function (w) {
            return '<option value="' + w.id + '">' + esc(w.number) + ' — ' +
                esc(w.job_name || '') + '</option>';
        }).join('');
    if (typeof fillJobPicker === 'function') await fillJobPicker('issue-job');
    issueOrderPicked();
    // The stores that hold something, fullest first; left on "wherever it
    // is", the server takes it from the store that has it.
    try {
        var st = (await (await fetch('/api/stock/stores', { credentials: 'include' })).json()).stores || [];
        st = st.filter(function (x) { return x.value > 0; }).sort(function (a, b) { return b.value - a.value; });
        document.getElementById('issue-store').innerHTML =
            '<option value="">Wherever it is held</option>' +
            st.map(function (x) { return '<option value="' + esc(x.store) + '">' + esc(x.store) + '</option>'; }).join('');
    } catch (e) { /* the server picks */ }

    // Only what is actually in the store can be issued from it.
    var held = STOCK.rows.filter(function (r) { return r.on_hand > 0; });
    document.getElementById('issue-lines').innerHTML = held.length
        ? held.map(function (r, i) {
            return '<tr><td style="font-family:monospace;">' + esc(r.item_code) +
                '<div style="font-size:0.72rem;font-family:inherit;' +
                'color:var(--text-secondary);">' + esc(r.item_name) + '</div></td>' +
                '<td class="text-right">' + r.on_hand + ' ' + esc(r.uom) + '</td>' +
                '<td class="text-right">' + formatCurrency(r.rate) + '</td>' +
                '<td><input type="number" step="any" min="0" class="form-control input-sm" ' +
                'id="iss-qty-' + i + '" data-code="' + esc(r.item_code) +
                '" data-max="' + r.on_hand + '" oninput="issueTotal()" ' +
                'style="text-align:right;"></td></tr>';
          }).join('')
        : '<tr><td colspan="4" style="text-align:center;padding:20px;' +
          'color:var(--text-secondary);">The store is empty.</td></tr>';
    document.getElementById('issue-date').value = new Date().toISOString().slice(0, 10);
    document.getElementById('issue-total').textContent = formatCurrency(0);
    document.getElementById('issue-charge').checked = false;
    document.getElementById('issue-markup').value = 0;
    issueChargeToggle();
    // The gangs that can be charged: live orders only.
    try {
        var so = await (await fetch('/api/wo/orders', { credentials: 'include' })).json();
        document.getElementById('issue-sub-order').innerHTML = (so.orders || []).filter(function (o) {
            return o.status === 'APPROVED' || o.status === 'EXECUTED'; }).map(function (o) {
            return '<option value="' + o.id + '">' + esc(o.wo_number + ' — ' + (o.contractor || '')) + '</option>';
        }).join('') || '<option value="">No live gang orders</option>';
    } catch (e) {}
    document.getElementById('issue-modal').style.display = 'flex';
}

function issueChargeToggle() {
    document.getElementById('issue-charge-fields').style.display =
        document.getElementById('issue-charge').checked ? '' : 'none';
}
window.issueChargeToggle = issueChargeToggle;
window.showIssueModal = showIssueModal;

function closeIssueModal() {
    document.getElementById('issue-modal').style.display = 'none';
}
window.closeIssueModal = closeIssueModal;

function issueLines() {
    var out = [];
    STOCK.rows.filter(function (r) { return r.on_hand > 0; }).forEach(function (r, i) {
        var el = document.getElementById('iss-qty-' + i);
        var qty = el ? parseFloat(el.value) : 0;
        if (qty > 0) out.push({ item_code: r.item_code, quantity: qty, rate: r.rate });
    });
    return out;
}

function issueTotal() {
    var total = 0, over = false;
    STOCK.rows.filter(function (r) { return r.on_hand > 0; }).forEach(function (r, i) {
        var el = document.getElementById('iss-qty-' + i);
        var qty = el ? parseFloat(el.value) || 0 : 0;
        total += qty * r.rate;
        // Said while they type, rather than after the post is refused.
        if (el) {
            var bad = qty > r.on_hand;
            el.style.borderColor = bad ? 'var(--danger-color)' : '';
            if (bad) over = true;
        }
    });
    document.getElementById('issue-total').textContent = formatCurrency(total);
    document.getElementById('issue-warn').textContent =
        over ? 'One line asks for more than the store holds.' : '';
}
window.issueTotal = issueTotal;

async function saveIssue(andPost) {
    var lines = issueLines();
    if (!lines.length) { showToast('Nothing entered to issue', 'error'); return; }
    var res = await fetch('/api/stock-issues', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            work_order_id: parseInt(document.getElementById('issue-order').value) || null,
            job_id: parseInt((document.getElementById('issue-job') || {}).value) || null,
            store: (document.getElementById('issue-store') || {}).value || '',
            issued_on: document.getElementById('issue-date').value,
            issued_to: document.getElementById('issue-to').value,
            purpose: document.getElementById('issue-purpose').value,
            lines: lines,
        }),
    });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not open the note', 'error'); return; }
    var charge = document.getElementById('issue-charge').checked
        ? { recover_from_order_id: parseInt(document.getElementById('issue-sub-order').value) || null,
            markup_percent: parseFloat(document.getElementById('issue-markup').value) || 0 }
        : null;
    if (charge && !charge.recover_from_order_id) {
        showToast('Choose the gang\'s work order to recover it from', 'error'); return;
    }
    closeIssueModal();
    if (andPost || charge) await postIssue(out.issue.id, charge);
    else { showToast(out.message, 'success'); loadStock(); }
}
window.saveIssue = saveIssue;

async function postIssue(id, charge) {
    var res = await fetch('/api/stock-issues/' + id + '/post', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(charge || {}),
    });
    var out = await res.json();
    if (!res.ok) {
        // The store may genuinely be behind the site; say so and let them decide.
        if (res.status === 409 && confirm(out.detail + '\n\nPost it anyway?')) {
            var forced = await fetch('/api/stock-issues/' + id + '/post', {
                method: 'POST', credentials: 'include',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(Object.assign({ allow_negative: true }, charge || {})),
            });
            var f = await forced.json();
            showToast(forced.ok ? f.message : (f.detail || 'Could not post it'),
                      forced.ok ? 'warning' : 'error');
            loadStock();
            return;
        }
        showToast(out.detail || 'Could not post it', 'error');
        return;
    }
    showToast(out.message, 'success');
    loadStock();
}
window.postIssue = postIssue;

async function cancelIssue(id) {
    if (!confirm('Cancel this issue note? Anything already posted goes back into the store.'))
        return;
    var res = await fetch('/api/stock-issues/' + id + '/cancel', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' }, body: '{}',
    });
    var out = await res.json();
    showToast(res.ok ? out.message : (out.detail || 'Could not cancel it'),
              res.ok ? 'success' : 'error');
    loadStock();
}
window.cancelIssue = cancelIssue;

/* --- What the job was costed on, against what it drew --------------------- */

async function loadConsumption(woId) {
    var body = document.getElementById('consume-body');
    if (!body || !woId) return;
    var d = await (await fetch('/api/stock/consumption/' + woId,
                               { credentials: 'include' })).json();
    var s = d.summary || {};
    var stats = document.getElementById('consume-stats');
    if (stats) stats.innerHTML =
        statCard('Costed on', formatCurrency(s.planned_value || 0)) +
        statCard('Actually drawn', formatCurrency(s.issued_value || 0)) +
        statCard('Difference', formatCurrency(s.variance_value || 0)) +
        statCard('Items over-consumed', String(s.lines_over_consumed || 0)) +
        statCard('Never budgeted', String(s.unplanned_items || 0));

    body.innerHTML = (d.lines || []).length ? d.lines.map(function (l) {
        var pc = Math.max(0, Math.min(100, l.percent_used));
        return '<tr>' +
            '<td style="font-family:monospace;font-weight:600;">' + esc(l.item_code) +
                '<div style="font-size:0.75rem;font-family:inherit;font-weight:400;' +
                'color:var(--text-secondary);">' + esc(l.item_name) + '</div></td>' +
            '<td class="text-right">' + l.planned_qty + '</td>' +
            '<td class="text-right">' + l.issued_qty +
                '<div style="height:5px;background:var(--border-color);border-radius:3px;' +
                'margin-top:4px;overflow:hidden;"><div style="width:' + pc + '%;height:100%;' +
                'background:' + (l.over_consumed ? 'var(--warning-color)'
                                                 : 'var(--primary-color)') +
                ';"></div></div></td>' +
            '<td class="text-right"' + (l.over_consumed
                ? ' style="color:var(--warning-color);font-weight:600;"' : '') + '>' +
                (l.variance_qty > 0 ? '+' : '') + l.variance_qty + '</td>' +
            '<td class="text-right">' + formatCurrency(l.variance_value) + '</td>' +
            '<td>' + (l.unplanned
                ? statusPill('never budgeted', 'bad')
                : l.over_consumed ? statusPill('over', 'wait')
                                  : statusPill('within', 'good')) + '</td>' +
            '</tr>';
    }).join('') : '<tr><td colspan="6" style="text-align:center;padding:24px;' +
        'color:var(--text-secondary);">Nothing costed or drawn on this order.</td></tr>';
}
window.loadConsumption = loadConsumption;

async function consumeChanged() {
    var pick = document.getElementById('consume-order');
    if (pick && pick.value) loadConsumption(parseInt(pick.value));
}
window.consumeChanged = consumeChanged;

async function loadConsumptionPicker() {
    var pick = document.getElementById('consume-order');
    if (!pick) return;
    var d = await (await fetch('/api/erp/work-orders', { credentials: 'include' })).json();
    var open = (d.work_orders || []).filter(function (w) { return w.status !== 'Draft'; });
    pick.innerHTML = open.length
        ? open.map(function (w) {
            return '<option value="' + w.id + '">' + esc(w.number) + ' — ' +
                esc(w.job_name || '') + '</option>';
          }).join('')
        : '<option value="">No placed orders yet</option>';
    if (open.length) loadConsumption(open[0].id);
}
window.loadConsumptionPicker = loadConsumptionPicker;


/* --- Site to site ---------------------------------------------------------------
   Material left at one site sent to the next, at what it cost. Not consumption:
   nothing is charged to a project until it is issued at the other end.
   ------------------------------------------------------------------------------ */

var TRF = { stores: [], held: {} };

async function showTransferModal() {
    var d = await (await fetch('/api/stock/stores', { credentials: 'include' })).json();
    TRF.stores = (d.stores || []).map(function (s) { return s.store; });
    if (!TRF.stores.length) TRF.stores = ['Main store'];
    document.getElementById('trf-from').innerHTML = TRF.stores.map(function (s) {
        return '<option>' + esc(s) + '</option>'; }).join('');
    document.getElementById('trf-stores').innerHTML = TRF.stores.map(function (s) {
        return '<option value="' + esc(s) + '">'; }).join('');
    document.getElementById('trf-to').value = '';
    document.getElementById('trf-note').value = '';
    document.getElementById('trf-date').value = localDate(new Date());
    await transferLines();
    openModal('transfer-modal');
}
window.showTransferModal = showTransferModal;

async function transferLines() {
    var from = document.getElementById('trf-from').value;
    var d = await (await fetch('/api/stock?store=' + encodeURIComponent(from), { credentials: 'include' })).json();
    TRF.held = (d.stock || []).filter(function (r) { return r.on_hand > 0; });
    document.getElementById('trf-lines').innerHTML = TRF.held.length ? TRF.held.map(function (r, i) {
        return '<tr><td style="font-family:monospace;">' + esc(r.item_code) +
            '<div style="font-size:0.72rem;font-family:inherit;color:var(--text-secondary);">' + esc(r.item_name) + '</div></td>' +
            '<td class="text-right">' + r.on_hand + ' ' + esc(r.uom) + '</td>' +
            '<td><input type="number" step="any" min="0" class="form-control input-sm" id="trf-qty-' + i +
            '" style="text-align:right;"></td></tr>';
    }).join('') : '<tr><td colspan="3" style="text-align:center;padding:18px;color:var(--text-secondary);">Nothing held in ' + esc(from) + '.</td></tr>';
}
window.transferLines = transferLines;

async function saveTransfer() {
    var lines = [];
    TRF.held.forEach(function (r, i) {
        var q = parseFloat((document.getElementById('trf-qty-' + i) || {}).value) || 0;
        if (q > 0) lines.push({ item_code: r.item_code, qty: q });
    });
    if (!lines.length) { showToast('Nothing entered to send', 'error'); return; }
    var res = await fetch('/api/stock/transfers', {
        method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ from_store: document.getElementById('trf-from').value,
            to_store: document.getElementById('trf-to').value,
            moved_on: document.getElementById('trf-date').value,
            note: document.getElementById('trf-note').value, lines: lines }) });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not send it', 'error'); return; }
    closeModal('transfer-modal');
    showToast(out.message, 'success');
    loadStock();
}
window.saveTransfer = saveTransfer;


// An order carries its project; without one, the project is picked here so
// the material is still charged to the site it went to.
function issueOrderPicked() {
    var wrap = document.getElementById('issue-job-wrap');
    var order = (document.getElementById('issue-order') || {}).value;
    if (wrap) wrap.style.display = order ? 'none' : '';
    if (order && document.getElementById('issue-job')) document.getElementById('issue-job').value = '';
}
window.issueOrderPicked = issueOrderPicked;
