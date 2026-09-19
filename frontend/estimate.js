/* ===========================================================================
   estimate.js - tenders, rate build-ups, and the order a won one becomes.

   A rate is defensible when it is written down per resource: so much cement,
   so much sand, so many mason-days, a share of a mixer. The analysis editor
   here is that page. Overhead goes on cost and profit on the result, in that
   order, because the other way round quietly understates the margin.
   =========================================================================== */

var EST = { list: [], current: null, itemId: null };
var EST_TONE = { DRAFT: 'calm', SUBMITTED: 'wait', WON: 'good', LOST: 'bad', WITHDRAWN: 'bad' };
var RATE_KINDS = ['MATERIAL', 'LABOUR', 'PLANT', 'OTHER'];

async function loadEstimates() {
    var body = document.getElementById('est-body');
    if (!body) return;
    var d = await (await fetch('/api/estimates', { credentials: 'include' })).json();
    EST.list = d.estimates || [];
    var s = d.summary || {};
    document.getElementById('est-stats').innerHTML =
        statCard('Open tenders', String(s.open || 0)) +
        statCard('Out for decision', formatCurrency(s.out_for_decision || 0)) +
        statCard('Won', formatCurrency(s.won_value || 0)) +
        statCard('Strike rate', (s.strike_rate || 0) + '%');

    body.innerHTML = EST.list.length ? EST.list.map(function (e) {
        return '<tr>' +
            '<td style="font-family:monospace;font-weight:600;">' + esc(e.number) + '</td>' +
            '<td>' + esc(e.title) + '<div style="font-size:0.75rem;color:var(--text-secondary);">' +
                esc(e.customer_name || '') + (e.tender_reference ? ' · ' + esc(e.tender_reference) : '') +
                '</div></td>' +
            '<td>' + esc(e.due_on || '—') + '</td>' +
            '<td class="text-right">' + e.item_count + '</td>' +
            '<td class="text-right">' + formatCurrency(e.cost_total) + '</td>' +
            '<td class="text-right" style="font-weight:700;">' + formatCurrency(e.quoted_total) +
                '<div style="font-size:0.72rem;font-weight:400;color:var(--text-secondary);">' +
                e.margin_percent + '% margin</div></td>' +
            '<td>' + statusPill(e.status, EST_TONE[e.status] || 'calm') +
                (e.work_order ? '<div style="font-size:0.72rem;color:var(--text-secondary);">' +
                 '→ ' + esc(e.work_order) + '</div>' : '') + '</td>' +
            '<td class="text-right"><button class="btn btn-sm btn-primary" onclick="openEstimate(' +
                e.id + ')">Open</button> <a class="btn btn-sm btn-outline" href="/api/estimates/' +
                e.id + '/export.xlsx">Excel</a></td></tr>';
    }).join('') : '<tr><td colspan="8" style="text-align:center;padding:30px;' +
        'color:var(--text-secondary);">No tenders yet. Pricing the job is where the ' +
        'business starts.</td></tr>';
    document.getElementById('est-detail').style.display = 'none';
}
window.loadEstimates = loadEstimates;

async function newEstimate() {
    var title = prompt('What is the tender for? (e.g. 295 KLD STP, Vizag)');
    if (!title || !title.trim()) return;
    var customer = prompt('Client (who issued the tender)?') || '';
    var res = await fetch('/api/estimates', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: title.trim(), customer_name: customer.trim(),
                               overhead_percent: 10, profit_percent: 8 }),
    });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not open it', 'error'); return; }
    showToast(out.message, 'success');
    await loadEstimates();
    openEstimate(out.estimate.id);
}
window.newEstimate = newEstimate;

async function openEstimate(id) {
    var res = await fetch('/api/estimates/' + id, { credentials: 'include' });
    if (!res.ok) return;
    EST.current = await res.json();
    renderEstimate();
}
window.openEstimate = openEstimate;

function renderEstimate() {
    var e = EST.current;
    var box = document.getElementById('est-detail');
    box.style.display = '';
    var locked = !e.editable;

    var act = '';
    if (e.actions.indexOf('SUBMIT') >= 0)
        act += '<button class="btn btn-primary" onclick="estAct(\'submit\')">Submit the price</button> ';
    if (e.actions.indexOf('WIN') >= 0)
        act += '<button class="btn btn-primary" onclick="estAct(\'win\')">We won it</button> ';
    if (e.actions.indexOf('LOSE') >= 0)
        act += '<button class="btn btn-outline" onclick="estAct(\'lose\', true)">We lost it</button> ';
    if (e.actions.indexOf('REOPEN') >= 0)
        act += '<button class="btn btn-outline" onclick="estAct(\'reopen\')">Reopen</button> ';
    if (e.actions.indexOf('WITHDRAW') >= 0)
        act += '<button class="btn btn-outline" onclick="estAct(\'withdraw\')">Withdraw</button> ';

    document.getElementById('est-head').innerHTML =
        '<div style="display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap;align-items:flex-start;">' +
        '<div><h3 style="margin:0;">' + esc(e.number) + ' — ' + esc(e.title) + '</h3>' +
        '<div style="font-size:0.85rem;color:var(--text-secondary);margin-top:4px;">' +
        esc(e.customer_name || '') + (e.tender_reference ? ' · ' + esc(e.tender_reference) : '') +
        ' · ' + statusPill(e.status, EST_TONE[e.status] || 'calm') +
        (e.work_order ? ' · became <strong>' + esc(e.work_order) + '</strong>' : '') +
        '</div></div><div>' + act + '</div></div>' +
        '<div class="form-row" style="margin-top:14px;max-width:420px;">' +
        '<div class="form-group"><label>Overhead %</label><input type="number" step="any" ' +
        'class="form-control input-sm" id="est-oh" value="' + e.overhead_percent + '"' +
        (locked ? ' disabled' : ' onchange="saveEstimateHead()"') + '></div>' +
        '<div class="form-group"><label>Profit %</label><input type="number" step="any" ' +
        'class="form-control input-sm" id="est-pf" value="' + e.profit_percent + '"' +
        (locked ? ' disabled' : ' onchange="saveEstimateHead()"') + '></div></div>';

    document.getElementById('est-totals').innerHTML =
        statCard('It will cost', formatCurrency(e.cost_total)) +
        statCard('We ask', formatCurrency(e.quoted_total)) +
        statCard('Margin', formatCurrency(e.margin_amount) + ' <span style="font-size:0.8rem;' +
                 'font-weight:400;color:var(--text-secondary);">' + e.margin_percent + '%</span>');

    document.getElementById('est-items').innerHTML = e.items.length ? e.items.map(function (it) {
        var built = it.analysis.length;
        return '<tr>' +
            '<td style="font-family:monospace;">' + esc(it.item_no) + '</td>' +
            '<td>' + esc(it.description) +
                (it.fg_code ? '<div style="font-size:0.72rem;font-family:monospace;color:var(--text-secondary);">' +
                 esc(it.fg_code) + '</div>' : '') + '</td>' +
            '<td class="text-right">' + it.quantity + ' ' + esc(it.uom) + '</td>' +
            '<td class="text-right">' + formatCurrency(it.cost_rate) +
                (built ? '<div style="font-size:0.7rem;color:var(--success-color);">built up from ' +
                 built + '</div>' : '<div style="font-size:0.7rem;color:var(--text-secondary);">typed</div>') +
                '</td>' +
            '<td class="text-right" style="font-weight:600;">' + formatCurrency(it.quoted_rate) + '</td>' +
            '<td class="text-right">' + formatCurrency(it.quoted_amount) + '</td>' +
            '<td class="text-right">' + (locked ? ''
                : '<button class="btn btn-sm btn-outline" onclick="openAnalysis(' + it.id + ')">Rate</button> ' +
                  '<button class="btn btn-sm btn-outline" onclick="removeEstItem(' + it.id + ')">&times;</button>') +
                '</td></tr>';
    }).join('') : '<tr><td colspan="7" style="text-align:center;padding:22px;' +
        'color:var(--text-secondary);">No items yet. Add the BOQ items from the tender.</td></tr>';
    document.getElementById('est-add-item').style.display = locked ? 'none' : '';
    box.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

async function saveEstimateHead() {
    var e = EST.current;
    var res = await fetch('/api/estimates/' + e.id, {
        method: 'PUT', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: e.title, customer_name: e.customer_name,
                               tender_reference: e.tender_reference, due_on: e.due_on,
                               overhead_percent: parseFloat(document.getElementById('est-oh').value) || 0,
                               profit_percent: parseFloat(document.getElementById('est-pf').value) || 0,
                               notes: e.notes }),
    });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not save', 'error'); return; }
    EST.current = out.estimate; renderEstimate();
}
window.saveEstimateHead = saveEstimateHead;

async function addEstItem() {
    var desc = document.getElementById('est-new-desc').value.trim();
    if (!desc) { showToast('Describe the item', 'error'); return; }
    var res = await fetch('/api/estimates/' + EST.current.id + '/items', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            item_no: document.getElementById('est-new-no').value.trim(),
            description: desc, uom: document.getElementById('est-new-uom').value.trim(),
            quantity: parseFloat(document.getElementById('est-new-qty').value) || 0,
            cost_rate: parseFloat(document.getElementById('est-new-rate').value) || 0,
        }),
    });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not add it', 'error'); return; }
    ['est-new-no', 'est-new-desc', 'est-new-uom', 'est-new-qty', 'est-new-rate'].forEach(function (id) {
        document.getElementById(id).value = '';
    });
    EST.current = out.estimate; renderEstimate();
    loadEstimates().then(function () { document.getElementById('est-detail').style.display = ''; });
}
window.addEstItem = addEstItem;

async function removeEstItem(itemId) {
    if (!confirm('Remove this item and its rate build-up?')) return;
    var res = await fetch('/api/estimates/' + EST.current.id + '/items/' + itemId,
                          { method: 'DELETE', credentials: 'include' });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not remove it', 'error'); return; }
    EST.current = out.estimate; renderEstimate();
}
window.removeEstItem = removeEstItem;

/* --- The rate build-up ----------------------------------------------------- */

function openAnalysis(itemId) {
    var it = EST.current.items.filter(function (x) { return x.id === itemId; })[0];
    if (!it) return;
    EST.itemId = itemId;
    document.getElementById('ra-title').textContent = it.item_no + ' — ' + it.description;
    document.getElementById('ra-context').textContent =
        'Per 1 ' + (it.uom || 'unit') + '. Enter what goes into one unit of this item; ' +
        'the rate is their sum, and it replaces anything typed.';
    var rows = it.analysis.length ? it.analysis.slice() : [];
    while (rows.length < 4) rows.push({});
    rows.push({});
    document.getElementById('ra-rows').innerHTML = rows.map(raRow).join('');
    EST.raRows = rows.length;
    raTotal();
    openModal('ra-modal');
}
window.openAnalysis = openAnalysis;

function raRow(a, i) {
    a = a || {};
    return '<tr>' +
        '<td><select class="form-control input-sm" id="ra-kind-' + i + '">' +
            RATE_KINDS.map(function (k) {
                return '<option' + (k === (a.kind || 'MATERIAL') ? ' selected' : '') + '>' + k + '</option>';
            }).join('') + '</select></td>' +
        '<td><input class="form-control input-sm" id="ra-desc-' + i + '" value="' + esc(a.description || '') +
            '" placeholder="Cement OPC 53"></td>' +
        '<td><input class="form-control input-sm" id="ra-uom-' + i + '" value="' + esc(a.uom || '') +
            '" placeholder="bag" style="width:70px;"></td>' +
        '<td><input type="number" step="any" class="form-control input-sm" id="ra-qty-' + i +
            '" value="' + (a.quantity_per_unit || '') + '" style="text-align:right;" oninput="raTotal()"></td>' +
        '<td><input type="number" step="any" class="form-control input-sm" id="ra-rate-' + i +
            '" value="' + (a.rate || '') + '" style="text-align:right;" oninput="raTotal()"></td>' +
        '<td><input type="number" step="any" class="form-control input-sm" id="ra-waste-' + i +
            '" value="' + (a.wastage_percent || '') + '" placeholder="0" style="text-align:right;width:70px;" oninput="raTotal()"></td>' +
        '<td class="text-right" id="ra-amt-' + i + '"></td></tr>';
}

function raLines() {
    var out = [];
    for (var i = 0; i < EST.raRows; i++) {
        var d = (document.getElementById('ra-desc-' + i) || {}).value || '';
        var q = parseFloat((document.getElementById('ra-qty-' + i) || {}).value) || 0;
        if (!d.trim() || !q) continue;
        out.push({ kind: document.getElementById('ra-kind-' + i).value, description: d,
                   uom: document.getElementById('ra-uom-' + i).value,
                   quantity_per_unit: q,
                   rate: parseFloat(document.getElementById('ra-rate-' + i).value) || 0,
                   wastage_percent: parseFloat(document.getElementById('ra-waste-' + i).value) || 0 });
    }
    return out;
}

function raTotal() {
    var total = 0;
    for (var i = 0; i < EST.raRows; i++) {
        var q = parseFloat((document.getElementById('ra-qty-' + i) || {}).value) || 0;
        var r = parseFloat((document.getElementById('ra-rate-' + i) || {}).value) || 0;
        var w = parseFloat((document.getElementById('ra-waste-' + i) || {}).value) || 0;
        var a = q * r * (1 + w / 100);
        total += a;
        var cell = document.getElementById('ra-amt-' + i);
        if (cell) cell.textContent = a ? formatCurrency(a) : '';
    }
    var oh = parseFloat((document.getElementById('est-oh') || {}).value) || 0;
    var pf = parseFloat((document.getElementById('est-pf') || {}).value) || 0;
    document.getElementById('ra-total').innerHTML =
        'Cost per unit <strong>' + formatCurrency(total) + '</strong> · with ' + oh + '% overhead and ' +
        pf + '% profit, we ask <strong>' + formatCurrency(total * (1 + oh / 100) * (1 + pf / 100)) + '</strong>';
}
window.raTotal = raTotal;

function closeAnalysis() { closeModal('ra-modal'); }
window.closeAnalysis = closeAnalysis;

async function saveAnalysis() {
    var res = await fetch('/api/estimates/' + EST.current.id + '/items/' + EST.itemId + '/analysis', {
        method: 'PUT', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ lines: raLines() }),
    });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not save the rate', 'error'); return; }
    closeAnalysis();
    EST.current = out.estimate; renderEstimate();
}
window.saveAnalysis = saveAnalysis;

async function estAct(action, needsReason) {
    var body = {};
    if (needsReason) {
        var why = prompt('Why did we lose it? (L1 price, spec, timing...)');
        if (why === null) return;
        body.reason = why;
    }
    if (action === 'win' && !confirm('Mark this tender as won? A work order will be drawn ' +
                                     'up from it, line for line.')) return;
    var res = await fetch('/api/estimates/' + EST.current.id + '/' + action, {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not do that', 'error'); return; }
    showToast(out.message, 'success');
    await loadEstimates();
    openEstimate(EST.current.id);
}
window.estAct = estAct;
