/* ===========================================================================
   ewaybill.js - e-way bills for goods on the road.

   Transfers heavy enough to need one are listed until they have one. A bill
   is drawn from the transfer (or typed for plant and returns), checked for
   what the portal would refuse, written as the portal's bulk file, and its
   number and validity recorded once the portal has issued it.
   =========================================================================== */

var EWB = { rows: [], meta: null, current: null, lines: [] };

async function ewbMeta() {
    if (!EWB.meta) EWB.meta = await (await fetch('/api/eway-places', { credentials: 'include' })).json();
    return EWB.meta;
}

async function loadEway() {
    var host = document.getElementById('eway-body');
    if (!host) return;
    var d = await (await fetch('/api/eway-bills', { credentials: 'include' })).json();
    EWB.rows = d.eway_bills || [];
    var s = d.summary || {};
    document.getElementById('eway-stats').innerHTML =
        statCard('Transfers needing one', String(s.uncovered || 0)) +
        statCard('Drafts', String(s.drafts || 0)) +
        statCard('Live on the road', String(s.live || 0)) +
        statCard('Past their validity', String(s.expired || 0));
    var need = (d.uncovered_transfers || []).map(function (t) {
        return '<tr><td style="font-family:monospace;">' + esc(t.number) + '</td><td>' + esc(t.moved_on) + '</td>' +
            '<td>' + esc(t.from_store) + ' &rarr; ' + esc(t.to_store) + '</td>' +
            '<td class="text-right">' + formatCurrency(t.value) + '</td>' +
            '<td class="text-right"><button class="btn btn-sm btn-primary" onclick="ewbFromTransfer(\'' +
            esc(t.number) + '\')">Draw the e-way bill</button></td></tr>';
    }).join('');
    var rows = EWB.rows.map(function (e) {
        var tone = e.status === 'GENERATED' ? (e.expired ? 'bad' : 'good') : e.status === 'CANCELLED' ? 'calm' : 'warn';
        return '<tr style="cursor:pointer;" onclick="ewbOpen(' + e.id + ')">' +
            '<td style="font-family:monospace;">' + esc(e.number) + '<div style="font-size:0.72rem;color:var(--text-secondary);">' +
            esc(e.source_ref || 'typed') + '</div></td>' +
            '<td>' + esc(e.from.name) + ' &rarr; ' + esc(e.to.name) + '<div style="font-size:0.72rem;color:var(--text-secondary);">' +
            esc(e.from.pincode) + ' &rarr; ' + esc(e.to.pincode) + (e.distance_km ? ' &middot; ' + e.distance_km + ' km' : '') + '</div></td>' +
            '<td class="text-right">' + formatCurrency(e.total_value) + '</td>' +
            '<td style="font-family:monospace;">' + esc(e.vehicle_no || '—') + '</td>' +
            '<td style="font-family:monospace;">' + esc(e.ewb_no || '—') + '</td>' +
            '<td>' + esc(e.valid_upto || '') + '</td>' +
            '<td>' + statusPill(e.expired ? 'EXPIRED' : e.status, tone) + '</td></tr>';
    }).join('');
    host.innerHTML =
        (need ? '<div class="widget" style="margin-bottom:16px;"><div class="widget-header"><h3>Transfers that need one</h3>' +
            '<span style="font-size:0.78rem;color:var(--text-secondary);">over ' + formatCurrency(50000) + ' of goods on the road</span></div>' +
            '<div class="table-responsive"><table class="data-table"><thead><tr><th>Transfer</th><th>Moved</th><th>From &rarr; to</th>' +
            '<th class="text-right">Value</th><th></th></tr></thead><tbody>' + need + '</tbody></table></div></div>' : '') +
        '<div class="widget"><div class="widget-header"><h3>E-way bills</h3></div><div class="table-responsive">' +
        '<table class="data-table"><thead><tr><th>Ref</th><th>From &rarr; to</th><th class="text-right">Value</th>' +
        '<th>Vehicle</th><th>EWB no.</th><th>Valid to</th><th>Status</th></tr></thead><tbody>' +
        (rows || '<tr><td colspan="7" style="text-align:center;padding:24px;color:var(--text-secondary);">' +
            'None yet. Draw one from a transfer above, or type one for plant or a return.</td></tr>') +
        '</tbody></table></div></div>';
}
window.loadEway = loadEway;

function ewbPlaceOptions(selected) {
    return '<option value="">Choose&hellip;</option>' + (EWB.meta.places || []).map(function (p) {
        return '<option value="' + esc(p.key) + '"' + (p.key === selected ? ' selected' : '') + '>' + esc(p.name) +
            (p.pincode ? ' (' + esc(p.pincode) + ')' : ' (no PIN)') + '</option>';
    }).join('');
}

function ewbKeyFor(side) {
    // Match the saved address back to a place, so an open draft shows its picks.
    var e = EWB.current;
    if (!e) return '';
    var hit = (EWB.meta.places || []).filter(function (p) {
        return p.name === e[side].name && p.address === e[side].address; })[0];
    return hit ? hit.key : '';
}

async function ewbFromTransfer(ref) {
    await ewbMeta();
    EWB.current = null;
    EWB.lines = [];
    ewbForm({ source_ref: ref });
}
window.ewbFromTransfer = ewbFromTransfer;

async function ewbNew() {
    await ewbMeta();
    EWB.current = null;
    EWB.lines = [{ product_name: '', hsn: '', qty: 1, unit: 'Nos', taxable: 0, tax_rate: 0 }];
    ewbForm({});
}
window.ewbNew = ewbNew;

async function ewbOpen(id) {
    await ewbMeta();
    var d = await (await fetch('/api/eway-bills/' + id, { credentials: 'include' })).json();
    EWB.current = d.eway_bill;
    EWB.lines = (EWB.current.lines || []).slice();
    ewbForm({});
}
window.ewbOpen = ewbOpen;

function ewbForm(opt) {
    var e = EWB.current || {};
    var m = EWB.meta;
    var draft = !e.id || e.status === 'DRAFT';
    var dis = draft ? '' : ' disabled';
    var sel = function (id, map, val) {
        return '<select id="' + id + '" class="form-control"' + dis + '>' + Object.keys(map).map(function (k) {
            return '<option value="' + k + '"' + (String(k) === String(val) ? ' selected' : '') + '>' + esc(map[k]) + '</option>';
        }).join('') + '</select>';
    };
    var fromTransfer = opt.source_ref || e.source_ref;
    document.getElementById('ewb-title').textContent = e.id
        ? e.number + (e.ewb_no ? ' — EWB ' + e.ewb_no : '')
        : 'E-way bill' + (opt.source_ref ? ' for ' + opt.source_ref : '');
    EWB.sourceRef = opt.source_ref || '';
    var lines = EWB.lines.map(function (l, i) {
        var cell = function (k, type, w) {
            return '<input class="form-control" style="min-width:' + w + 'px;" type="' + type + '"' + dis +
                (fromTransfer && k !== 'hsn' && k !== 'tax_rate' ? ' readonly' : '') +
                ' value="' + esc(l[k] === undefined || l[k] === null ? '' : l[k]) + '" oninput="EWB.lines[' + i + '].' + k + '=this.value">';
        };
        return '<tr><td>' + cell('product_name', 'text', 180) + '</td><td>' + cell('hsn', 'text', 90) + '</td>' +
            '<td>' + cell('qty', 'number', 70) + '</td><td>' + cell('unit', 'text', 60) + '</td>' +
            '<td>' + cell('taxable', 'number', 100) + '</td><td>' + cell('tax_rate', 'number', 60) + '</td>' +
            '<td>' + (draft && !fromTransfer ? '<button class="btn btn-sm btn-outline" onclick="EWB.lines.splice(' + i + ',1);ewbForm({})">&times;</button>' : '') + '</td></tr>';
    }).join('');
    var problems = (e.problems || []);
    document.getElementById('ewb-body').innerHTML =
        '<div class="form-row">' +
        '<div class="form-group"><label>From</label><select id="ewb-from" class="form-control"' + dis + '>' + ewbPlaceOptions(ewbKeyFor('from') || (e.id ? '' : 'company')) + '</select></div>' +
        '<div class="form-group"><label>To</label><select id="ewb-to" class="form-control"' + dis + '>' + ewbPlaceOptions(ewbKeyFor('to')) + '</select></div>' +
        '</div>' +
        (e.id ? '<p style="font-size:0.78rem;color:var(--text-secondary);margin:-4px 0 10px;">' +
            esc(e.from.address) + ' (' + esc(e.from.state_name) + ') &rarr; ' + esc(e.to.address) + ' (' + esc(e.to.state_name) + ')</p>' : '') +
        '<div class="form-row">' +
        '<div class="form-group"><label>Document</label>' + sel('ewb-doctype', m.doc_types, e.doc_type || 'CHL') + '</div>' +
        '<div class="form-group"><label>Document no.</label><input id="ewb-docno" class="form-control" maxlength="16" value="' + esc(e.doc_no || opt.source_ref || '') + '"' + dis + '></div>' +
        '<div class="form-group"><label>Date</label><input type="date" id="ewb-docdate" class="form-control" value="' + esc(e.doc_date || localDate(new Date())) + '"' + dis + '></div>' +
        '<div class="form-group"><label>Why it moves</label>' + sel('ewb-subtype', m.sub_types, e.sub_type || '5') + '</div>' +
        '</div>' +
        '<div class="form-row">' +
        '<div class="form-group"><label>Distance (km)</label><input type="number" id="ewb-km" class="form-control" value="' + (e.distance_km || '') + '" placeholder="0 = portal works it out"' + dis + '></div>' +
        '<div class="form-group"><label>By</label>' + sel('ewb-mode', m.modes, e.trans_mode || '1') + '</div>' +
        '<div class="form-group"><label>Vehicle no.</label><input id="ewb-vehicle" class="form-control" style="text-transform:uppercase;" value="' + esc(e.vehicle_no || '') + '" placeholder="TS09UB1234"' + dis + '></div>' +
        '<div class="form-group"><label>Transporter (GSTIN / ID)</label><input id="ewb-trid" class="form-control" value="' + esc(e.transporter_id || '') + '"' + dis + '></div>' +
        '</div>' +
        '<div class="table-responsive"><table class="data-table"><thead><tr><th>Goods</th><th>HSN</th><th>Qty</th><th>Unit</th>' +
        '<th>Value &#8377;</th><th>GST %</th><th></th></tr></thead><tbody>' +
        (lines || (fromTransfer ? '<tr><td colspan="7" style="color:var(--text-secondary);">The transfer\'s lines are filled in when it is saved.</td></tr>' : '')) +
        '</tbody></table></div>' +
        (draft && !fromTransfer ? '<button class="btn btn-sm btn-outline" style="margin-top:6px;" onclick="EWB.lines.push({product_name:\'\',hsn:\'\',qty:1,unit:\'Nos\',taxable:0,tax_rate:0});ewbForm({})">+ Line</button>' : '') +
        (e.id ? '<div style="margin-top:12px;font-size:0.84rem;">Value ' + formatCurrency(e.taxable_value) +
            (e.igst ? ' &middot; IGST ' + formatCurrency(e.igst) : (e.cgst ? ' &middot; CGST ' + formatCurrency(e.cgst) + ' + SGST ' + formatCurrency(e.sgst) : '')) +
            ' &middot; <strong>' + formatCurrency(e.total_value) + '</strong>' +
            (e.total_value <= 50000 ? ' <span style="color:var(--text-secondary);">(under ' + formatCurrency(50000) + ': not required, allowed)</span>' : '') + '</div>' : '') +
        (problems.length ? '<div style="margin-top:12px;padding:10px 12px;border:1px solid var(--warning-color);border-radius:8px;font-size:0.82rem;">' +
            '<strong>The portal would refuse it for want of:</strong><ul style="margin:6px 0 0 18px;">' +
            problems.map(function (p) { return '<li>' + esc(p) + '</li>'; }).join('') + '</ul></div>' : '') +
        ((e.vehicle_history || []).length ? '<div style="margin-top:10px;font-size:0.76rem;color:var(--text-secondary);">Vehicle changes:<br>' +
            e.vehicle_history.map(esc).join('<br>') + '</div>' : '') +
        (e.cancel_reason ? '<p style="margin-top:10px;color:var(--danger-color);font-size:0.82rem;">Cancelled: ' + esc(e.cancel_reason) + '</p>' : '');

    var b = [];
    if (draft) b.push('<button class="btn btn-primary" onclick="ewbSave()">Save</button>');
    if (e.id && draft) b.push('<a class="btn btn-outline" href="/api/eway-bills/' + e.id + '/json" onclick="return ewbCanDownload()">Download for the portal</a>');
    if (e.id && draft) b.push('<button class="btn btn-outline" onclick="ewbGenerated()">Portal issued it&hellip;</button>');
    if (e.id && e.status === 'GENERATED') b.push('<button class="btn btn-outline" onclick="ewbVehicle()">Change vehicle</button>');
    if (e.id && e.status !== 'CANCELLED') b.push('<button class="btn btn-outline" style="color:var(--danger-color);" onclick="ewbCancel()">Cancel</button>');
    b.push('<button class="btn btn-outline" onclick="closeModal(\'ewb-modal\')">Close</button>');
    document.getElementById('ewb-actions').innerHTML = b.join(' ');
    openModal('ewb-modal');
}

function ewbCanDownload() {
    var p = (EWB.current || {}).problems || [];
    if (p.length) { showToast('Fix what is listed first - the portal would refuse it.', 'error'); return false; }
    return true;
}
window.ewbCanDownload = ewbCanDownload;

async function ewbSave() {
    var v = function (id) { return (document.getElementById(id) || {}).value || ''; };
    var e = EWB.current;
    var body = {
        from_key: v('ewb-from'), to_key: v('ewb-to'), doc_type: v('ewb-doctype'), doc_no: v('ewb-docno'),
        doc_date: v('ewb-docdate'), sub_type: v('ewb-subtype'), distance_km: parseInt(v('ewb-km')) || 0,
        trans_mode: v('ewb-mode'), vehicle_no: v('ewb-vehicle'), transporter_id: v('ewb-trid'),
    };
    if (!body.to_key && !(e && e.id)) { showToast('Where is it going?', 'error'); return; }
    if (EWB.sourceRef) { body.source_type = 'transfer'; body.source_ref = EWB.sourceRef; }
    if (EWB.lines.length) body.lines = EWB.lines.map(function (l) {
        return { item_code: l.item_code || '', product_name: l.product_name || '', hsn: String(l.hsn || ''),
                 qty: parseFloat(l.qty) || 0, unit: l.unit || '', taxable: parseFloat(l.taxable) || 0,
                 tax_rate: parseFloat(l.tax_rate) || 0 };
    });
    var res = await fetch('/api/eway-bills' + (e && e.id ? '/' + e.id : ''), {
        method: e && e.id ? 'PUT' : 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not save it', 'error'); return; }
    EWB.current = out.eway_bill;
    EWB.lines = (EWB.current.lines || []).slice();
    EWB.sourceRef = '';
    showToast(EWB.current.problems.length ? 'Saved - ' + EWB.current.problems.length + ' thing(s) still needed.'
                                          : 'Saved. Ready for the portal.', EWB.current.problems.length ? 'warning' : 'success');
    ewbForm({});
    loadEway();
}
window.ewbSave = ewbSave;

async function ewbPost(path, body, done) {
    var res = await fetch('/api/eway-bills/' + EWB.current.id + '/' + path, {
        method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body) });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not do that', 'error'); return; }
    EWB.current = out.eway_bill;
    EWB.lines = (EWB.current.lines || []).slice();
    showToast(out.message || done, 'success');
    ewbForm({});
    loadEway();
}

function ewbGenerated() {
    var no = prompt('The twelve-digit e-way bill number the portal gave:');
    if (!no) return;
    ewbPost('generated', { ewb_no: no, ewb_date: localDate(new Date()) }, 'Recorded.');
}
window.ewbGenerated = ewbGenerated;

function ewbVehicle() {
    var no = prompt('The new vehicle number (as on the portal\'s Part B):');
    if (!no) return;
    var why = prompt('Why did it change? (breakdown, transhipment...)') || '';
    ewbPost('vehicle', { vehicle_no: no, reason: why }, 'Vehicle updated.');
}
window.ewbVehicle = ewbVehicle;

function ewbCancel() {
    var why = prompt('Why is it being cancelled?');
    if (!why) return;
    ewbPost('cancel', { reason: why }, 'Cancelled.');
}
window.ewbCancel = ewbCancel;
