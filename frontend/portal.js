/* ===========================================================================
   portal.js - the partner portal: a gang's or a supplier's own view of their
   orders, bills, payments and statement with the company.
   =========================================================================== */

var P = { me: null, tab: 'overview', orders: [] };

function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
        return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; });
}
var INR = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2 });
function rs(n) { return INR.format(n || 0); }
function pill(text, tone) { return '<span class="pill ' + tone + '">' + esc(text) + '</span>'; }
function show(id) {
    ['p-login', 'p-invite', 'p-app'].forEach(function (x) { document.getElementById(x).classList.toggle('hidden', x !== id); });
}
async function api(path, opts) {
    var res = await fetch(path, Object.assign({ credentials: 'same-origin' }, opts || {}));
    var body = null;
    try { body = await res.json(); } catch (e) { body = {}; }
    if (res.status === 401 && path !== '/api/portal/login') { show('p-login'); }
    return { ok: res.ok, status: res.status, body: body };
}
function post(path, data) {
    return api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data || {}) });
}

async function pStart() {
    var token = new URLSearchParams(location.search).get('invite');
    if (token) {
        var r = await api('/api/portal/invite?token=' + encodeURIComponent(token));
        show('p-invite');
        if (!r.ok) {
            document.getElementById('pi-title').textContent = 'This link has expired';
            document.getElementById('pi-text').textContent = r.body.detail || 'Ask the office for a new one.';
            document.querySelector('#p-invite form').classList.add('hidden');
            return;
        }
        document.getElementById('pi-title').textContent = 'Welcome, ' + (r.body.name || r.body.party);
        document.getElementById('pi-text').textContent = r.body.company + ' has opened its partner portal to ' +
            r.body.party + '. You will sign in as ' + r.body.email + '.';
        return;
    }
    var me = await api('/api/portal/me');
    if (!me.ok) { show('p-login'); return; }
    P.me = me.body;
    openApp();
}

async function pLogin() {
    var msg = document.getElementById('pl-msg');
    msg.className = 'msg'; msg.textContent = 'Signing in...';
    var r = await post('/api/portal/login', { email: document.getElementById('pl-email').value,
                                              password: document.getElementById('pl-pass').value });
    if (!r.ok) { msg.className = 'msg bad'; msg.textContent = r.body.detail || 'Could not sign in.'; return; }
    msg.textContent = '';
    P.me = (await api('/api/portal/me')).body;
    openApp();
}

async function pAccept() {
    var msg = document.getElementById('pi-msg');
    var a = document.getElementById('pi-pass').value, b = document.getElementById('pi-pass2').value;
    if (a !== b) { msg.className = 'msg bad'; msg.textContent = 'The two passwords are not the same.'; return; }
    var token = new URLSearchParams(location.search).get('invite');
    var r = await post('/api/portal/accept-invite', { token: token, password: a });
    if (!r.ok) { msg.className = 'msg bad'; msg.textContent = r.body.detail || 'Could not set it.'; return; }
    history.replaceState(null, '', location.pathname);
    P.me = (await api('/api/portal/me')).body;
    openApp();
}

async function pLogout() {
    await post('/api/portal/logout');
    P.me = null;
    show('p-login');
}

function openApp() {
    show('p-app');
    document.getElementById('pa-party').textContent = P.me.party;
    document.getElementById('pa-with').textContent = 'Your account with ' + P.me.company +
        (P.me.name ? ' · ' + P.me.name : '');
    document.title = P.me.company + ' · Partner portal';
    document.getElementById('pa-send-tab').classList.toggle('hidden', P.me.party_type !== 'supplier');
    pTab('overview');
}

function pTab(t) {
    P.tab = t;
    document.querySelectorAll('#pa-tabs button').forEach(function (b) { b.classList.toggle('active', b.dataset.tab === t); });
    ({ overview: pOverview, orders: pOrders, bills: pBills, payments: pPayments,
       statement: pStatement, send: pSend })[t]();
}

function main(html) {
    var host = document.getElementById('pa-main');
    host.innerHTML = html;
    labelTables(host);
}
function labelTables(host) {
    host.querySelectorAll('table').forEach(function (t) {
        t.classList.add('stack');
        var heads = Array.prototype.map.call(t.querySelectorAll('thead th'), function (th) { return th.textContent; });
        t.querySelectorAll('tbody tr').forEach(function (tr) {
            Array.prototype.forEach.call(tr.children, function (td, i) { if (heads[i]) td.setAttribute('data-label', heads[i]); });
        });
    });
}
function card(k, v, s) { return '<div class="card"><div class="k">' + esc(k) + '</div><div class="v">' + v + '</div>' + (s ? '<div class="s">' + s + '</div>' : '') + '</div>'; }
function table(head, rows, empty, cols) {
    return '<div class="table-wrap"><table><thead><tr>' + head + '</tr></thead><tbody>' +
        (rows || '<tr><td colspan="' + cols + '" class="empty">' + esc(empty) + '</td></tr>') + '</tbody></table></div>';
}

async function pOverview() {
    main('<p class="sub">Loading...</p>');
    var s = (await api('/api/portal/summary')).body;
    var last = s.last_payment;
    var html = '<h2>Where things stand</h2><div class="cards">' +
        card(s.balance >= 0 ? 'Due to you' : 'Due from you', rs(Math.abs(s.balance)), 'on your statement today') +
        card('Passed, not yet paid', rs(s.passed_unpaid)) +
        card('Bills being checked', String(s.bills_waiting)) +
        card('Paid to you so far', rs(s.paid_total), last ? 'last ' + rs(last.amount) + ' on ' + esc(last.paid_on) : '') +
        card('Live orders', String(s.orders), rs(s.order_value)) +
        (s.retention_held !== undefined ? card('Your retention with us', rs(s.retention_held)) : '') + '</div>';
    if (s.retention && s.retention.length) {
        html += '<h2 style="margin-top:22px;">Retention</h2>' + table(
            '<th>Order</th><th class="r">Held</th><th class="r">Released</th><th class="r">Still held</th><th>Defects period ends</th>',
            s.retention.map(function (r) {
                return '<tr><td class="mono">' + esc(r.order_number) + '</td><td class="r">' + rs(r.held) + '</td><td class="r">' +
                    rs(r.released) + '</td><td class="r"><b>' + rs(r.balance) + '</b></td><td>' + esc(r.dlp_ends || '—') + '</td></tr>';
            }).join(''), '', 5);
    }
    main(html);
}

async function pOrders() {
    main('<p class="sub">Loading...</p>');
    P.orders = (await api('/api/portal/orders')).body.orders || [];
    main('<h2>Your orders</h2>' + table('<th>Order</th><th>Project</th><th class="r">Value</th><th>Period</th><th></th>',
        P.orders.map(function (o) {
            return '<tr><td><span class="mono">' + esc(o.number) + '</span>' + (o.superseded ? ' ' + pill('replaced by an amendment', 'calm') : '') +
                (o.subject ? '<div class="sub">' + esc(o.subject.slice(0, 90)) + '</div>' : '') + '</td><td>' + esc(o.project) + '</td>' +
                '<td class="r">' + rs(o.value) + '</td><td class="sub" style="white-space:nowrap;">' + esc(o.from || '') + (o.to ? ' → ' + esc(o.to) : '') + '</td>' +
                '<td class="r" style="white-space:nowrap;"><button class="btn" onclick="pOrder(' + o.id + ')">Items</button> ' +
                '<a class="btn" href="/api/portal/orders/' + o.id + '/document.pdf" target="_blank" rel="noopener">PDF</a></td></tr>';
        }).join(''), 'No orders yet.', 5) + '<div id="pa-order"></div>');
}

async function pOrder(id) {
    var r = (await api('/api/portal/orders/' + id)).body;
    document.getElementById('pa-order').innerHTML = '<h2 style="margin-top:22px;">' + esc(r.order.number) + ' - items</h2>' +
        table('<th>Item</th><th class="r">Qty</th><th class="r">Rate</th><th class="r">Amount</th>',
            r.lines.map(function (l) {
                return '<tr><td>' + (l.code ? '<span class="mono">' + esc(l.code) + '</span> ' : '') + esc(l.description) + '</td>' +
                    '<td class="r">' + l.qty + ' ' + esc(l.uom) + '</td><td class="r">' + rs(l.rate) + '</td><td class="r">' + rs(l.amount) + '</td></tr>';
            }).join(''), 'No items.', 4);
    labelTables(document.getElementById('pa-order'));
    document.getElementById('pa-order').scrollIntoView({ behavior: 'smooth' });
}
window.pOrder = pOrder;

function billTone(b) {
    if (/paid/.test(b.where)) return 'good';
    if (/sent back/.test(b.where)) return 'bad';
    if (/passed|accepted/.test(b.where)) return 'wait';
    return 'calm';
}

async function pBills() {
    main('<p class="sub">Loading...</p>');
    var bills = (await api('/api/portal/bills')).body.bills || [];
    var gang = P.me.party_type === 'contractor';
    main('<h2>Your bills</h2>' + table(
        '<th>Bill</th><th>Where it is</th><th class="r">' + (gang ? 'Work claimed' : 'Before tax') + '</th>' +
        '<th class="r">Payable</th><th class="r">Paid</th><th class="r">Left</th>',
        bills.map(function (b) {
            var deduct = gang && (b.retention || b.tds || b.deductions)
                ? '<div class="sub">retention ' + rs(b.retention) + (b.deductions ? ', recoveries ' + rs(b.deductions) : '') +
                  ', TDS ' + rs(b.tds) + ', GST ' + rs(b.gst) + '</div>' : '<div class="sub">GST ' + rs(b.gst) + '</div>';
            return '<tr><td><span class="mono">' + esc(b.number) + '</span><div class="sub">' + esc(b.date) + '</div></td>' +
                '<td><div>' + pill(b.where, billTone(b)) + (b.note ? '<div class="sub">' + esc(b.note) + '</div>' : '') + '</div></td>' +
                '<td class="r"><div>' + rs(b.claimed) + deduct + '</div></td><td class="r"><b>' + rs(b.net) + '</b></td>' +
                '<td class="r">' + rs(b.paid) + '</td><td class="r">' + rs(b.left) +
                (b.pdf ? '<div><a class="btn" style="padding:4px 10px;margin-top:4px;" href="' + b.pdf + '" target="_blank" rel="noopener">PDF</a></div>' : '') +
                '</td></tr>';
        }).join(''), 'No bills yet.', 6));
}

async function pPayments() {
    main('<p class="sub">Loading...</p>');
    var pays = (await api('/api/portal/payments')).body.payments || [];
    main('<h2>Payments to you</h2>' + table('<th>Date</th><th>Voucher</th><th>Against</th><th>How</th><th class="r">Amount</th>',
        pays.map(function (p) {
            return '<tr><td style="white-space:nowrap;">' + esc(p.paid_on) + '</td><td class="mono">' + esc(p.number) + '</td>' +
                '<td>' + esc(p.against) + '</td><td>' + esc(p.mode) + (p.reference ? '<div class="sub">' + esc(p.reference) + '</div>' : '') + '</td>' +
                '<td class="r"><b>' + rs(p.amount) + '</b></td></tr>';
        }).join(''), 'Nothing paid yet.', 5));
}

async function pStatement() {
    var from = (document.getElementById('ps-from') || {}).value || '';
    var to = (document.getElementById('ps-to') || {}).value || '';
    var q = '?date_from=' + encodeURIComponent(from) + '&date_to=' + encodeURIComponent(to);
    var s = (await api('/api/portal/statement' + q)).body;
    main('<h2>Statement of account</h2>' +
        '<div class="filters"><div><label for="ps-from">From</label><input type="date" id="ps-from" value="' + esc(from) + '"></div>' +
        '<div><label for="ps-to">To</label><input type="date" id="ps-to" value="' + esc(to) + '"></div>' +
        '<div style="flex:0 0 auto;display:flex;gap:8px;"><button class="btn" onclick="pStatement()">Show</button>' +
        '<a class="btn" href="/api/portal/statement.pdf' + q + '" target="_blank" rel="noopener">PDF</a>' +
        '<a class="btn" href="/api/portal/statement.xlsx' + q + '">Excel</a></div></div>' +
        (s.opening ? '<p class="sub" style="margin-top:12px;">Brought forward: ' + rs(s.opening) + '</p>' : '') +
        table('<th>Date</th><th>Entry</th><th class="r">Billed</th><th class="r">Paid</th><th class="r">Balance</th>',
            (s.rows || []).map(function (r) {
                return '<tr><td style="white-space:nowrap;">' + esc(r.date) + '</td><td>' + esc(r.kind) +
                    '<div class="sub">' + esc(r.number) + (r.against ? ' · against ' + esc(r.against) : '') + (r.reference ? ' · ' + esc(r.reference) : '') + '</div></td>' +
                    '<td class="r">' + (r.billed ? rs(r.billed) : '') + '</td><td class="r">' + (r.paid ? rs(r.paid) : '') + '</td>' +
                    '<td class="r"><b>' + rs(r.balance) + '</b></td></tr>';
            }).join(''), 'Nothing in this period.', 5) +
        '<p style="margin-top:12px;font-weight:700;">' + (s.closing >= 0 ? 'Balance due to you: ' : 'Balance due from you: ') + rs(Math.abs(s.closing)) + '</p>');
}
window.pStatement = pStatement;

async function pSend() {
    if (!P.orders.length) P.orders = (await api('/api/portal/orders')).body.orders || [];
    var today = new Date().toISOString().slice(0, 10);
    main('<h2>Send us an invoice</h2><p class="sub" style="margin-bottom:12px;">It reaches the office as a bill to check against what was delivered. ' +
        'You will see it under Bills, and when it is accepted and paid.</p>' +
        '<form class="form" onsubmit="event.preventDefault(); pSendInvoice();">' +
        '<div class="two"><div><label for="si-no">Your invoice number</label><input id="si-no" required></div>' +
        '<div><label for="si-date">Invoice date</label><input type="date" id="si-date" value="' + today + '" required></div></div>' +
        '<div class="two"><div><label for="si-amt">Value before GST</label><input type="number" step="0.01" min="0" id="si-amt" required></div>' +
        '<div><label for="si-gst">GST</label><input type="number" step="0.01" min="0" id="si-gst" value="0"></div></div>' +
        '<label for="si-po">Against our order</label><select id="si-po"><option value="">Not against an order</option>' +
        P.orders.filter(function (o) { return !o.superseded; }).map(function (o) {
            return '<option>' + esc(o.number) + '</option>'; }).join('') + '</select>' +
        '<label for="si-file">The invoice (PDF or a photo)</label><input type="file" id="si-file" accept="application/pdf,image/*" required>' +
        '<label for="si-note">Note</label><input id="si-note" placeholder="Delivery challan numbers, anything the office should know">' +
        '<button class="btn btn-primary btn-block" type="submit" id="si-go">Send it</button><div class="msg" id="si-msg"></div></form>');
}

async function pSendInvoice() {
    var msg = document.getElementById('si-msg'), go = document.getElementById('si-go');
    var fd = new FormData();
    fd.append('number', document.getElementById('si-no').value);
    fd.append('issue_date', document.getElementById('si-date').value);
    fd.append('amount', document.getElementById('si-amt').value);
    fd.append('tax_amount', document.getElementById('si-gst').value || '0');
    fd.append('po_number', document.getElementById('si-po').value);
    fd.append('note', document.getElementById('si-note').value);
    fd.append('file', document.getElementById('si-file').files[0]);
    go.disabled = true; msg.className = 'msg'; msg.textContent = 'Sending...';
    var r = await api('/api/portal/invoices', { method: 'POST', body: fd });
    go.disabled = false;
    msg.className = 'msg ' + (r.ok ? 'good' : 'bad');
    msg.textContent = r.ok ? r.body.message : (r.body.detail || 'Not sent.');
    if (r.ok) document.querySelector('#pa-main form').reset();
}
window.pSendInvoice = pSendInvoice;

pStart();
