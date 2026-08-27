/* ===========================================================================
   subcontracts.js - work orders issued out to a subcontractor.

   Four steps, because that is the order the document is actually assembled
   in: who it is with, what they are doing, on what terms, and then a read of
   the whole thing before anybody is asked to sign it.

   The wizard saves at every step rather than at the end. A schedule of two
   hundred BOQ lines is not something to lose to a closed tab, and the order
   has a number from the moment it is opened so it can be quoted while it is
   still being priced.
   =========================================================================== */

var WO = { id: null, step: 1, order: null, vocab: null, boq: [], terms: [] };

var WO_STATUS_TONE = {
    DRAFT: 'calm', PROVISIONAL: 'wait', APPROVED: 'good',
    EXECUTED: 'good', REJECTED: 'bad', CANCELLED: 'bad', AMENDED: 'calm',
};
var WO_STEPS = ['Order details', 'Schedule of work', 'Terms', 'Review'];


/* --- The list ------------------------------------------------------------ */

async function loadSubcontracts() {
    var body = document.getElementById('sc-body');
    if (!body) return;
    body.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:30px;color:var(--text-secondary);">Loading work orders...</td></tr>';
    var data;
    try {
        data = await (await fetch('/api/wo/orders', { credentials: 'include' })).json();
    } catch (e) {
        body.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:30px;color:var(--text-secondary);">Could not load work orders.</td></tr>';
        return;
    }
    var s = data.summary || {};
    var stats = document.getElementById('sc-stats');
    if (stats) {
        stats.innerHTML = statCard('Work orders', s.total || 0) +
            statCard('Drafts', s.draft || 0) +
            statCard('Awaiting approval', s.awaiting || 0) +
            statCard('Committed value', formatCurrency(s.value || 0));
    }
    var rows = data.orders || [];
    body.innerHTML = rows.length ? rows.map(function (o) {
        return '<tr>' +
            '<td style="font-family:monospace;font-weight:600;">' + esc(o.wo_number) +
                (o.amendment_no ? '<div style="font-size:0.72rem;font-weight:400;color:var(--text-secondary);">rev ' + o.amendment_no + '</div>' : '') + '</td>' +
            '<td>' + esc(o.contractor || '—') +
                '<div style="font-size:0.75rem;color:var(--text-secondary);">' + esc(o.project || '') + '</div></td>' +
            '<td>' + esc(o.department || '—') + '</td>' +
            '<td class="text-right">' + o.item_count + '</td>' +
            '<td class="text-right">' + formatCurrency(o.net_order_value) + '</td>' +
            '<td>' + statusPill(o.status, WO_STATUS_TONE[o.status] || 'calm') + '</td>' +
            '<td class="text-right">' +
                '<button class="btn btn-sm btn-outline" onclick="openSubcontract(' + o.id + ')">' +
                (o.editable ? 'Continue' : 'Open') + '</button></td>' +
            '</tr>';
    }).join('') : '<tr><td colspan="7" style="text-align:center;padding:30px;color:var(--text-secondary);">' +
        'No work orders yet. Raise the first one to issue work to a subcontractor.</td></tr>';
}
window.loadSubcontracts = loadSubcontracts;


/* --- Opening the wizard -------------------------------------------------- */

async function woVocab() {
    if (!WO.vocab) {
        WO.vocab = await (await fetch('/api/wo/vocabulary', { credentials: 'include' })).json();
        WO.vocab.business_units = (await (await fetch('/api/wo/business-units',
            { credentials: 'include' })).json()).business_units || [];
        WO.vocab.contractors = (await (await fetch('/api/wo/contractors',
            { credentials: 'include' })).json()).contractors || [];
    }
    return WO.vocab;
}

async function newSubcontract() {
    WO = { id: null, step: 1, order: null, vocab: WO.vocab, boq: [], terms: [] };
    await woVocab();
    showView('subcontract-wizard-view');
    renderWizard();
}
window.newSubcontract = newSubcontract;

async function openSubcontract(id) {
    await woVocab();
    var data = await (await fetch('/api/wo/orders/' + id, { credentials: 'include' })).json();
    WO.order = data.order;
    WO.id = id;
    WO.boq = (data.order.items || []).slice();
    WO.terms = (data.order.terms || []).slice();
    WO.step = data.order.editable ? 1 : 4;
    showView('subcontract-wizard-view');
    renderWizard();
}
window.openSubcontract = openSubcontract;

function woGoStep(n) {
    // Nothing before the order exists: the later steps hang off its number.
    if (n > 1 && !WO.id) { showToast('Save the order details first', 'error'); return; }
    WO.step = n;
    renderWizard();
}
window.woGoStep = woGoStep;


/* --- Chrome -------------------------------------------------------------- */

function wizardHeader() {
    var o = WO.order;
    var crumbs = WO_STEPS.map(function (label, i) {
        var n = i + 1, on = WO.step === n, done = WO.step > n;
        return '<button class="btn btn-sm ' + (on ? 'btn-primary' : 'btn-outline') + '" ' +
            'style="margin-right:6px;' + (done ? 'opacity:0.85;' : '') + '" ' +
            'onclick="woGoStep(' + n + ')">' + n + '. ' + esc(label) + '</button>';
    }).join('');
    return '<div style="display:flex;justify-content:space-between;align-items:center;' +
        'gap:12px;flex-wrap:wrap;margin-bottom:16px;">' +
        '<div>' + crumbs + '</div>' +
        '<div>' + (o ? '<span style="font-family:monospace;font-weight:600;">' +
            esc(o.wo_number) + '</span> ' +
            statusPill(o.status, WO_STATUS_TONE[o.status] || 'calm') : '') + '</div></div>';
}

function field(label, html, hint) {
    return '<div class="form-group"><label>' + esc(label) + '</label>' + html +
        (hint ? '<p style="font-size:0.75rem;color:var(--text-secondary);margin-top:4px;">' +
                esc(hint) + '</p>' : '') + '</div>';
}

function options(list, value, valueKey, labelFn) {
    return '<option value=""></option>' + list.map(function (x) {
        var v = valueKey ? x[valueKey] : x;
        return '<option value="' + esc(v) + '"' + (String(v) === String(value) ? ' selected' : '') +
            '>' + esc(labelFn ? labelFn(x) : x) + '</option>';
    }).join('');
}


/* --- Adding what the order needs, without leaving the order --------------
   The first screen asks for a contractor, a business unit and a project. On a
   new installation there are none of any of them, and every picker is empty -
   so the first work order somebody tries to raise cannot be raised at all,
   and nothing on the screen says where to go instead. These add one from
   here and select it.
   ------------------------------------------------------------------------ */

var WO_QUICK = {
    contractor: {
        title: 'New contractor', url: '/api/wo/contractors', pick: 'wo-con',
        fields: [['company_name', 'Company name *', 'text'],
                 ['contact_person', 'Contact person', 'text'],
                 ['phone_number', 'Phone', 'tel'],
                 ['pan', 'PAN', 'text'],
                 ['gst_number', 'GST number', 'text'],
                 ['address', 'Address', 'text']],
        required: 'company_name',
    },
    unit: {
        title: 'New business unit', url: '/api/wo/business-units', pick: 'wo-bu',
        fields: [['name', 'Unit name *', 'text'],
                 ['code', 'Code', 'text'],
                 ['gstin', 'GSTIN', 'text'],
                 ['pan', 'PAN', 'text'],
                 ['address', 'Address', 'text']],
        required: 'name',
    },
    project: {
        title: 'New project', url: '/api/jobs', pick: 'wo-job',
        fields: [['name', 'Project name *', 'text'],
                 ['customer_name', 'Client', 'text'],
                 ['site_address', 'Site address', 'text']],
        required: 'name',
    },
};

function woQuickAdd(kind) {
    var spec = WO_QUICK[kind];
    if (!spec) return;
    // Whatever is already typed into step one is kept, so adding a contractor
    // does not throw away the subject somebody just wrote.
    WO.order = Object.assign({}, WO.order || {}, detailsPayload());
    document.getElementById('wo-quick-title').textContent = spec.title;
    document.getElementById('wo-quick-kind').value = kind;
    document.getElementById('wo-quick-body').innerHTML = spec.fields.map(function (f) {
        return '<div class="form-group"><label>' + esc(f[1]) + '</label>' +
            '<input type="' + f[2] + '" class="form-control" id="wq-' + f[0] + '"></div>';
    }).join('');
    document.getElementById('wo-quick-modal').style.display = 'flex';
    var first = document.getElementById('wq-' + spec.fields[0][0]);
    if (first) first.focus();
}
window.woQuickAdd = woQuickAdd;

function closeWoQuick() {
    document.getElementById('wo-quick-modal').style.display = 'none';
}
window.closeWoQuick = closeWoQuick;

async function saveWoQuick() {
    var kind = document.getElementById('wo-quick-kind').value;
    var spec = WO_QUICK[kind];
    var payload = {};
    spec.fields.forEach(function (f) {
        var el = document.getElementById('wq-' + f[0]);
        payload[f[0]] = el ? el.value.trim() : '';
    });
    if (!payload[spec.required]) {
        showToast('A name is required', 'error');
        return;
    }
    var res = await fetch(spec.url, {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
    });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not save', 'error'); return; }

    closeWoQuick();
    showToast(out.message || 'Added', 'success');
    WO.vocab = null;                       // the pickers are now out of date
    await woVocab();
    // Select what was just added, which is what it was added for.
    if (kind === 'contractor') WO.order.contractor_id = out.id;
    if (kind === 'unit') WO.order.business_unit_id = out.id;
    if (kind === 'project') WO.order.job_id = out.id;
    renderWizard();
}
window.saveWoQuick = saveWoQuick;


/* --- Step 1: who the order is with --------------------------------------- */

function stepDetails() {
    var o = WO.order || {}, v = WO.vocab;
    var locked = o.id && !o.editable;
    var dis = locked ? ' disabled' : '';
    // A picker plus a way to fill it. On a new installation all three are
    // empty, and without this the first order cannot be raised at all.
    var withAdd = function (selectHtml, kind, empty) {
        return '<div style="display:flex;gap:6px;align-items:center;">' +
            '<div style="flex:1;min-width:0;">' + selectHtml + '</div>' +
            (locked ? '' : '<button type="button" class="btn btn-sm btn-outline" ' +
                'style="white-space:nowrap;" onclick="woQuickAdd(\'' + kind + '\')">+ New</button>') +
            '</div>' + (empty && !locked
                ? '<p style="font-size:0.75rem;color:var(--warning-color);margin-top:4px;">' +
                  'None on file yet &mdash; add the first one here.</p>' : '');
    };

    return '<div class="grid-2-1" style="display:grid;grid-template-columns:1fr 1fr;gap:0 18px;">' +
        field('Business unit *', withAdd('<select id="wo-bu" class="form-control"' + dis + '>' +
            options(v.business_units, o.business_unit_id, 'id', function (b) { return b.name; }) +
            '</select>', 'unit', !v.business_units.length),
            'The entity issuing the order. Its GSTIN prints on it.') +
        field('Contractor *', withAdd('<select id="wo-con" class="form-control"' + dis + '>' +
            options(v.contractors, o.contractor_id, 'id',
                function (c) { return c.company_name + (c.vendor_code ? ' (' + c.vendor_code + ')' : ''); }) +
            '</select>', 'contractor', !v.contractors.length)) +
        field('Project', withAdd('<select id="wo-job" class="form-control"' + dis + '>' +
            options(v.jobs, o.job_id, 'id', function (j) { return j.number + ' — ' + j.name; }) +
            '</select>', 'project', !v.jobs.length)) +
        field('Department *', '<select id="wo-dept" class="form-control"' + dis + '>' +
            options(v.departments, o.department) + '</select>',
            'Decides the series the number is filed under.') +
        '</div>' +
        field('Subject *', '<input id="wo-subject" class="form-control" value="' +
            esc(o.subject || '') + '"' + dis +
            ' placeholder="Work order for primary civil STP supply &amp; commissioning for 295 KLD plant">') +
        field('Scope of work', '<textarea id="wo-scope" class="form-control" rows="4"' + dis + '>' +
            esc(o.scope_of_work || '') + '</textarea>') +
        '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:0 14px;">' +
        field('Commencement *', '<input type="date" id="wo-start" class="form-control" value="' +
            esc(o.commencement_date || '') + '"' + dis + '>') +
        field('Completion *', '<input type="date" id="wo-end" class="form-control" value="' +
            esc(o.completion_date || '') + '"' + dis + '>') +
        field('Duration (months)', '<input type="number" step="0.5" id="wo-dur" class="form-control" value="' +
            (o.duration_months || '') + '"' + dis + '>') +
        field('Defect liability (months)', '<input type="number" id="wo-dlp" class="form-control" value="' +
            (o.defect_liability_months || '') + '"' + dis + '>') +
        '</div>' +
        '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:0 14px;">' +
        field('GST %', '<input type="number" step="0.01" id="wo-gst" class="form-control" value="' +
            (o.gst_rate !== undefined ? o.gst_rate : 18) + '"' + dis + '>') +
        field('TDS %', '<input type="number" step="0.01" id="wo-tds" class="form-control" value="' +
            (o.tds_rate !== undefined ? o.tds_rate : 1) + '"' + dis + '>') +
        field('Bank guarantee', '<select id="wo-bg" class="form-control"' + dis + '>' +
            '<option value="no"' + (o.bank_guarantee_applicable ? '' : ' selected') + '>Not applicable</option>' +
            '<option value="yes"' + (o.bank_guarantee_applicable ? ' selected' : '') + '>Required</option></select>') +
        field('BG amount', '<input type="number" step="0.01" id="wo-bgamt" class="form-control" value="' +
            (o.bank_guarantee_amount || '') + '"' + dis + '>') +
        '</div>' +
        (locked ? '' :
        '<div style="display:flex;gap:8px;margin-top:8px;">' +
        '<button class="btn btn-primary" onclick="saveWoDetails()">' +
            (WO.id ? 'Save and continue' : 'Open the order') + '</button>' +
        '<button class="btn btn-outline" onclick="showView(\'subcontracts-view\')">Cancel</button></div>');
}

function detailsPayload() {
    var val = function (id) { var e = document.getElementById(id); return e ? e.value : ''; };
    return {
        business_unit_id: parseInt(val('wo-bu')) || null,
        contractor_id: parseInt(val('wo-con')) || null,
        job_id: parseInt(val('wo-job')) || null,
        department: val('wo-dept'), work_type: val('wo-dept'),
        subject: val('wo-subject'), scope_of_work: val('wo-scope'),
        commencement_date: val('wo-start'), completion_date: val('wo-end'),
        duration_months: parseFloat(val('wo-dur')) || 0,
        defect_liability_months: parseInt(val('wo-dlp')) || 0,
        gst_rate: parseFloat(val('wo-gst')) || 0,
        tds_rate: parseFloat(val('wo-tds')) || 0,
        bank_guarantee_applicable: val('wo-bg') === 'yes',
        bank_guarantee_amount: parseFloat(val('wo-bgamt')) || 0,
    };
}

async function saveWoDetails() {
    var payload = detailsPayload();
    if (!payload.contractor_id) { showToast('Choose the contractor', 'error'); return; }
    if (!payload.department) { showToast('Choose the department', 'error'); return; }
    var res = await fetch('/api/wo/orders' + (WO.id ? '/' + WO.id : ''), {
        method: WO.id ? 'PUT' : 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
    });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not save', 'error'); return; }
    WO.order = out.order;
    WO.id = out.order.id;
    showToast(out.message, 'success');
    WO.step = 2;
    renderWizard();
}
window.saveWoDetails = saveWoDetails;


/* --- Step 2: the schedule ------------------------------------------------ */

function stepBoq() {
    var locked = WO.order && !WO.order.editable;
    var v = WO.vocab;
    var rows = WO.boq.map(function (l, i) {
        var amount = (parseFloat(l.quantity) || 0) * (parseFloat(l.unit_rate) || 0);
        var dis = locked ? ' disabled' : '';
        return '<tr>' +
            '<td><input class="form-control" style="min-width:64px;" value="' + esc(l.activity_no || '') +
                '" oninput="woBoqSet(' + i + ',\'activity_no\',this.value)"' + dis + '></td>' +
            '<td><input class="form-control" style="min-width:96px;" value="' + esc(l.item_code || '') +
                '" oninput="woBoqSet(' + i + ',\'item_code\',this.value)"' + dis + '></td>' +
            '<td><textarea class="form-control" rows="2" style="min-width:260px;" ' +
                'oninput="woBoqSet(' + i + ',\'item_description\',this.value)"' + dis + '>' +
                esc(l.item_description || '') + '</textarea></td>' +
            '<td><select class="form-control" style="min-width:80px;" ' +
                'onchange="woBoqSet(' + i + ',\'uom\',this.value)"' + dis + '>' +
                options(v.uoms, l.uom) + '</select></td>' +
            '<td><input type="number" step="any" class="form-control text-right" style="min-width:90px;" value="' +
                (l.quantity || '') + '" oninput="woBoqSet(' + i + ',\'quantity\',this.value)"' + dis + '></td>' +
            '<td><input type="number" step="any" class="form-control text-right" style="min-width:100px;" value="' +
                (l.unit_rate || '') + '" oninput="woBoqSet(' + i + ',\'unit_rate\',this.value)"' + dis + '></td>' +
            '<td class="text-right" style="font-weight:600;white-space:nowrap;">' + formatCurrency(amount) + '</td>' +
            '<td class="text-right">' + (locked ? '' :
                '<button class="btn btn-sm btn-outline" onclick="woBoqRemove(' + i + ')">&times;</button>') + '</td>' +
            '</tr>';
    }).join('');

    var gross = WO.boq.reduce(function (t, l) {
        return t + (parseFloat(l.quantity) || 0) * (parseFloat(l.unit_rate) || 0); }, 0);

    return '<div class="table-responsive"><table class="data-table">' +
        '<thead><tr><th>Activity</th><th>Item code</th><th>Description</th><th>UOM</th>' +
        '<th class="text-right">Qty</th><th class="text-right">Rate</th>' +
        '<th class="text-right">Amount</th><th></th></tr></thead>' +
        '<tbody>' + (rows || '<tr><td colspan="8" style="text-align:center;padding:24px;' +
            'color:var(--text-secondary);">Nothing scheduled yet.</td></tr>') + '</tbody>' +
        '<tfoot><tr><td colspan="6" class="text-right"><strong>Gross</strong></td>' +
        '<td class="text-right"><strong>' + formatCurrency(gross) + '</strong></td><td></td></tr></tfoot>' +
        '</table></div>' +
        (locked ? '' :
        '<div style="display:flex;gap:8px;margin-top:12px;flex-wrap:wrap;">' +
        '<button class="btn btn-outline" onclick="woBoqAdd()">+ Add line</button>' +
        '<button class="btn btn-primary" onclick="saveWoBoq()">Save schedule</button>' +
        '<button class="btn btn-outline" onclick="woGoStep(3)">Skip to terms</button></div>');
}

function woBoqSet(i, key, value) {
    WO.boq[i][key] = value;
    // Only the money column is redrawn as you type; redrawing the table would
    // take the caret out of the cell being edited.
    if (key === 'quantity' || key === 'unit_rate') renderWizard();
}
window.woBoqSet = woBoqSet;

function woBoqAdd() {
    var last = WO.boq[WO.boq.length - 1];
    var next = last ? String(parseFloat(last.activity_no || 0) + 1) + '.0' : '1.0';
    WO.boq.push({ activity_no: next, item_code: '', item_description: '',
                  uom: 'cum', quantity: '', unit_rate: '' });
    renderWizard();
}
window.woBoqAdd = woBoqAdd;

function woBoqRemove(i) { WO.boq.splice(i, 1); renderWizard(); }
window.woBoqRemove = woBoqRemove;

async function saveWoBoq() {
    var res = await fetch('/api/wo/orders/' + WO.id + '/boq', {
        method: 'PUT', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ lines: WO.boq.map(function (l) {
            return { activity_no: l.activity_no, item_code: l.item_code,
                     item_description: l.item_description, uom: l.uom,
                     quantity: parseFloat(l.quantity) || 0,
                     unit_rate: parseFloat(l.unit_rate) || 0 }; }) }),
    });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not save the schedule', 'error'); return; }
    WO.order = out.order;
    WO.boq = out.order.items.slice();
    showToast(out.message, 'success');
    WO.step = 3;
    renderWizard();
}
window.saveWoBoq = saveWoBoq;


/* --- Step 3: the terms --------------------------------------------------- */

function stepTerms() {
    var locked = WO.order && !WO.order.editable;
    var v = WO.vocab;
    var rows = WO.terms.map(function (t, i) {
        var dis = locked ? ' disabled' : '';
        return '<div style="border:1px solid var(--border-color);border-radius:8px;' +
            'padding:12px;margin-bottom:10px;">' +
            '<div style="display:flex;gap:8px;align-items:center;margin-bottom:6px;">' +
            '<select class="form-control" style="max-width:280px;" ' +
                'onchange="woTermSet(' + i + ',\'clause_category\',this.value)"' + dis + '>' +
                options(v.clause_categories, t.clause_category) + '</select>' +
            (locked ? '' : '<button class="btn btn-sm btn-outline" style="margin-left:auto;" ' +
                'onclick="woTermRemove(' + i + ')">Remove</button>') + '</div>' +
            '<textarea class="form-control" rows="3" ' +
                'oninput="woTermSet(' + i + ',\'clause_text\',this.value)"' + dis + '>' +
                esc(t.clause_text || '') + '</textarea></div>';
    }).join('');

    return (rows || '<p style="color:var(--text-secondary);padding:12px 0;">' +
        'No clauses yet. The standard set is a starting point, not a policy &mdash; ' +
        'every one of them is edited on the order it goes out on.</p>') +
        (locked ? '' :
        '<div style="display:flex;gap:8px;margin-top:8px;flex-wrap:wrap;">' +
        '<button class="btn btn-outline" onclick="woTermAdd()">+ Add clause</button>' +
        '<button class="btn btn-outline" onclick="woLoadStandardTerms()">Load standard terms</button>' +
        '<button class="btn btn-primary" onclick="saveWoTerms()">Save terms</button></div>');
}

function woTermSet(i, key, value) { WO.terms[i][key] = value; }
window.woTermSet = woTermSet;

function woTermAdd() {
    WO.terms.push({ clause_category: WO.vocab.clause_categories[0], clause_text: '' });
    renderWizard();
}
window.woTermAdd = woTermAdd;

function woTermRemove(i) { WO.terms.splice(i, 1); renderWizard(); }
window.woTermRemove = woTermRemove;

async function woLoadStandardTerms() {
    var lib = (await (await fetch('/api/wo/terms/library',
        { credentials: 'include' })).json()).library || [];
    // Appended, not substituted: anything already written on this order was
    // written deliberately.
    var have = WO.terms.map(function (t) { return t.clause_category; });
    lib.forEach(function (t) {
        if (have.indexOf(t.clause_category) < 0) WO.terms.push(Object.assign({}, t));
    });
    renderWizard();
}
window.woLoadStandardTerms = woLoadStandardTerms;

async function saveWoTerms() {
    var res = await fetch('/api/wo/orders/' + WO.id + '/terms', {
        method: 'PUT', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ terms: WO.terms }),
    });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not save the terms', 'error'); return; }
    WO.order = out.order;
    WO.terms = out.order.terms.slice();
    showToast(out.message, 'success');
    WO.step = 4;
    renderWizard();
}
window.saveWoTerms = saveWoTerms;


/* --- Step 4: read it before signing it ----------------------------------- */

function money2(n) { return formatCurrency(n || 0); }

function stepReview() {
    var o = WO.order;
    if (!o) return '<p>Nothing to review yet.</p>';

    var money_rows = [
        ['Gross value', money2(o.gross_amount)],
        ['GST @ ' + o.gst_rate + '%', money2(o.gst_amount)],
        ['TDS @ ' + o.tds_rate + '% (withheld)', '(' + money2(o.tds_amount) + ')'],
        ['Net order value', '<strong>' + money2(o.net_order_value) + '</strong>'],
    ].map(function (r) {
        return '<tr><td>' + r[0] + '</td><td class="text-right">' + r[1] + '</td></tr>';
    }).join('');

    var facts = [
        ['Contractor', o.contractor], ['Business unit', o.business_unit],
        ['Project', o.project], ['Department', o.department],
        ['Commencement', o.commencement_date], ['Completion', o.completion_date],
        ['Defect liability', (o.defect_liability_months || 0) + ' months'],
        ['Bank guarantee', o.bank_guarantee_applicable
            ? money2(o.bank_guarantee_amount) : 'Not applicable'],
    ].map(function (r) {
        return '<tr><td style="color:var(--text-secondary);">' + esc(r[0]) +
            '</td><td>' + esc(String(r[1] || '—')) + '</td></tr>';
    }).join('');

    var history = (o.history || []).map(function (h) {
        return '<tr><td>' + esc(h.action) + '</td><td>' + esc(h.actor) + '</td>' +
            '<td>' + esc(h.at) + '</td><td>' + esc(h.comments || '') + '</td></tr>';
    }).join('');

    return '<div style="display:grid;grid-template-columns:1fr 1fr;gap:18px;">' +
        '<div class="widget"><div class="widget-header"><h3>The order</h3></div>' +
            '<div class="table-responsive"><table class="data-table"><tbody>' + facts +
            '</tbody></table></div></div>' +
        '<div class="widget"><div class="widget-header"><h3>What it is worth</h3></div>' +
            '<div class="table-responsive"><table class="data-table"><tbody>' + money_rows +
            '</tbody></table></div>' +
            '<p style="padding:12px 16px;color:var(--text-secondary);font-size:0.82rem;">' +
            esc(o.subject || '') + '</p></div>' +
        '</div>' +
        '<div class="widget" style="margin-top:16px;"><div class="widget-header">' +
            '<h3>' + (o.items || []).length + ' schedule item(s) &middot; ' +
            (o.terms || []).length + ' clause(s)</h3>' +
            '<div><a class="btn btn-sm btn-outline" href="/api/wo/orders/' + o.id +
                '/boq.xlsx">Download schedule</a></div></div></div>' +
        (history ? '<div class="widget" style="margin-top:16px;">' +
            '<div class="widget-header"><h3>History</h3></div>' +
            '<div class="table-responsive"><table class="data-table">' +
            '<thead><tr><th>Action</th><th>By</th><th>When</th><th>Remarks</th></tr></thead>' +
            '<tbody>' + history + '</tbody></table></div></div>' : '') +
        woActions(o);
}

function woActions(o) {
    // Only the moves the order can actually make. A button that answers with
    // a refusal is worse than no button.
    var can = o.actions || [];
    var buttons = [];
    if (can.indexOf('SUBMIT') >= 0)
        buttons.push('<button class="btn btn-primary" onclick="woAct(\'submit\')">Submit for approval</button>');
    if (can.indexOf('APPROVE') >= 0)
        buttons.push('<button class="btn btn-primary" onclick="woAct(\'approve\')">Approve</button>');
    if (can.indexOf('REJECT') >= 0)
        buttons.push('<button class="btn btn-outline" onclick="woAct(\'reject\', true)">Send back</button>');
    if (can.indexOf('EXECUTE') >= 0)
        buttons.push('<button class="btn btn-primary" onclick="woAct(\'execute\')">Mark executed</button>');
    if (can.indexOf('AMEND') >= 0)
        buttons.push('<button class="btn btn-outline" onclick="woAct(\'amend\')">Raise an amendment</button>');
    if (can.indexOf('CANCEL') >= 0)
        buttons.push('<button class="btn btn-outline" onclick="woAct(\'cancel\', true)">Cancel</button>');
    buttons.push('<button class="btn btn-outline" onclick="showView(\'subcontracts-view\');loadSubcontracts()">Back to list</button>');
    return '<div style="display:flex;gap:8px;margin-top:16px;flex-wrap:wrap;">' +
        buttons.join('') + '</div>';
}

async function woAct(action, needsReason) {
    var comments = '';
    if (needsReason) {
        comments = prompt(action === 'reject'
            ? 'Why is this going back?' : 'Why is this being cancelled?');
        if (comments === null) return;
        if (!comments.trim()) { showToast('A reason is required', 'error'); return; }
    }
    var res = await fetch('/api/wo/orders/' + WO.id + '/' + action, {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ comments: comments }),
    });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not do that', 'error'); return; }
    showToast(out.message, 'success');
    // An amendment hands back a different order, so follow it there.
    WO.order = out.order;
    WO.id = out.order.id;
    WO.boq = (out.order.items || []).slice();
    WO.terms = (out.order.terms || []).slice();
    WO.step = out.order.editable ? 1 : 4;
    renderWizard();
}
window.woAct = woAct;


function renderWizard() {
    var host = document.getElementById('sc-wizard');
    if (!host) return;
    var step = WO.step === 1 ? stepDetails()
             : WO.step === 2 ? stepBoq()
             : WO.step === 3 ? stepTerms() : stepReview();
    host.innerHTML = wizardHeader() + step;
}
