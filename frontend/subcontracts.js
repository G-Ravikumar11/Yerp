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

var WO = { id: null, step: 1, order: null, vocab: null, boq: [], terms: [],
           imported: null, doc: null };

var WO_STATUS_TONE = {
    DRAFT: 'calm', PROVISIONAL: 'wait', APPROVED: 'good',
    EXECUTED: 'good', REJECTED: 'bad', CANCELLED: 'bad', AMENDED: 'calm',
};
var WO_STEPS = ['General info', 'Schedule of work', 'Billing terms', 'Submission'];


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
            '<td class="text-right" style="white-space:nowrap;">' +
                '<button class="btn btn-sm btn-outline" onclick="woPreview(' + o.id + ')" ' +
                    'title="The printed document">Document</button> ' +
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
    WO = { id: null, step: 1, order: null, vocab: WO.vocab, boq: [], terms: [],
           imported: null, doc: null };
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
    WO.imported = null;
    WO.doc = null;
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
    // A numbered rail rather than four buttons: at a glance it says how far
    // through the document you are, which of it is done, and that there is an
    // end to it. Somebody pricing two hundred lines wants to know that.
    var steps = WO_STEPS.map(function (label, i) {
        var n = i + 1, on = WO.step === n, done = WO.step > n;
        var fill = on ? 'var(--primary-color)' : done ? 'var(--success-color)' : 'transparent';
        var edge = (on || done) ? fill : 'var(--border-color)';
        return '<button type="button" onclick="woGoStep(' + n + ')" title="' + esc(label) + '" ' +
            'style="display:flex;align-items:center;gap:8px;background:none;border:none;' +
            'padding:0;cursor:pointer;font:inherit;white-space:nowrap;">' +
            '<span style="width:24px;height:24px;border-radius:50%;display:inline-flex;' +
            'align-items:center;justify-content:center;font-size:0.75rem;font-weight:700;' +
            'background:' + fill + ';border:1.5px solid ' + edge + ';' +
            'color:' + ((on || done) ? '#fff' : 'var(--text-secondary)') + ';">' +
            (done ? '&#10003;' : n) + '</span>' +
            '<span style="font-size:0.84rem;' + (on ? 'font-weight:700;' :
                'font-weight:500;color:var(--text-secondary);') + '">' +
            esc(label) + '</span></button>';
    }).join('<span style="flex:1;height:1.5px;min-width:14px;' +
            'background:var(--border-color);"></span>');

    return '<div style="display:flex;justify-content:space-between;align-items:center;' +
        'gap:18px;flex-wrap:wrap;margin-bottom:18px;padding-bottom:14px;' +
        'border-bottom:1px solid var(--border-color);">' +
        '<div style="display:flex;align-items:center;gap:8px;flex:1;min-width:280px;">' +
            steps + '</div>' +
        '<div style="display:flex;align-items:center;gap:8px;">' +
        (o ? '<span style="font-family:monospace;font-weight:600;">' + esc(o.wo_number) +
             '</span>' + statusPill(o.status, WO_STATUS_TONE[o.status] || 'calm') +
             (o.id ? '<button class="btn btn-sm btn-outline" onclick="woPreview()">Preview</button>' : '')
           : '') +
        '</div></div>';
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

function woVendorCard() {
    /* What is known about the contractor, shown the moment one is picked.
       These are the fields that make a payment legal rather than merely
       addressed, and finding out at the point of paying that there is no PAN
       on file is finding out three weeks too late. */
    var o = WO.order || {};
    var v = WO.vocab || {};
    var con = null;
    (v.contractors || []).forEach(function (c) {
        if (String(c.id) === String(o.contractor_id)) con = c;
    });
    if (!con) return '';

    var rows = [
        ['Vendor code', con.vendor_code], ['Contact', con.contact_person],
        ['Phone', con.phone_number], ['PAN', con.pan],
        ['GST number', con.gst_number],
        ['Bank', [con.bank_name, con.bank_account, con.bank_ifsc]
            .filter(Boolean).join(' · ')],
    ].filter(function (r) { return r[1]; });

    var missing = [];
    if (!con.pan) missing.push('PAN');
    if (!con.gst_number) missing.push('GST number');
    if (!con.bank_account) missing.push('bank details');

    return '<div style="border:1px solid var(--border-color);border-radius:8px;' +
        'padding:12px 14px;margin-bottom:14px;">' +
        '<div style="font-weight:700;font-size:0.88rem;margin-bottom:8px;">' +
            esc(con.company_name) + '</div>' +
        (con.address ? '<div style="font-size:0.78rem;color:var(--text-secondary);' +
            'margin-bottom:8px;white-space:pre-line;">' + esc(con.address) + '</div>' : '') +
        '<div style="display:grid;grid-template-columns:auto 1fr;gap:2px 14px;' +
            'font-size:0.78rem;">' +
        rows.map(function (r) {
            return '<span style="color:var(--text-secondary);">' + esc(r[0]) + '</span>' +
                '<span>' + esc(r[1]) + '</span>'; }).join('') + '</div>' +
        (missing.length
            ? '<p style="font-size:0.75rem;color:var(--warning-color);margin:8px 0 0;">' +
              'No ' + esc(missing.join(', ')) + ' on file. It will be needed before ' +
              'a bill against this order can be paid.</p>' : '') +
        '</div>';
}

/* --- The scope of work, written rather than typed ------------------------ */

function woRichEditor(id, html, disabled) {
    /* Bold, italic and bullets and nothing else. A scope of work is a
       paragraph of prose with the odd emphasis in it, and every heavier
       editor is a dependency to keep alive for a toolbar nobody uses. The
       markup is narrowed again on the server, so what is stored is a known
       set whatever gets pasted in here. */
    var buttons = [['bold', 'B', 'font-weight:700;'],
                   ['italic', 'I', 'font-style:italic;'],
                   ['insertUnorderedList', '&bull; List', '']];
    return '<div style="border:1px solid var(--border-color);border-radius:8px;' +
        'overflow:hidden;">' +
        (disabled ? '' :
        '<div style="display:flex;gap:4px;padding:6px 8px;' +
            'border-bottom:1px solid var(--border-color);">' +
        buttons.map(function (b) {
            return '<button type="button" class="btn btn-sm btn-outline" ' +
                'style="min-width:34px;' + b[2] + '" onmousedown="event.preventDefault()" ' +
                'onclick="woRichCommand(\'' + b[0] + '\')">' + b[1] + '</button>';
        }).join('') + '</div>') +
        '<div id="' + id + '" ' + (disabled ? '' : 'contenteditable="true" ') +
            'style="min-height:110px;padding:10px 12px;outline:none;' +
            'font-size:0.88rem;line-height:1.5;">' + (html || '') + '</div></div>';
}

function woRichCommand(command) {
    var host = document.getElementById('wo-scope');
    if (host) host.focus();
    try { document.execCommand(command, false, null); } catch (e) { /* older browser */ }
}
window.woRichCommand = woRichCommand;

function woRichValue(id) {
    var host = document.getElementById(id);
    if (!host) return '';
    // An editor left empty reports a stray <br>, which would save as a scope
    // that is not empty and prints as a blank heading.
    var html = host.innerHTML.trim();
    return (host.textContent || '').trim() ? html : '';
}

/* --- Work types ---------------------------------------------------------- */

async function woRequestWorkType() {
    var name = prompt('Which work type is missing?');
    if (name === null || !name.trim()) return;
    var why = prompt('What is it for? (so whoever administers the list can '
                     + 'see why it is needed)') || '';
    var res = await fetch('/api/wo/work-types', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name.trim(), request_reason: why.trim(),
                               department: (WO.order || {}).department || '' }),
    });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not ask for that', 'error'); return; }
    showToast(out.message, 'success');
    WO.vocab = null;
    await woVocab();
    // An administrator's addition is usable at once; a request is not, and
    // selecting something nobody has approved would fail on save.
    if (out.work_type.status === 'active') {
        WO.order = Object.assign({}, WO.order || {}, detailsPayload());
        WO.order.work_type = out.work_type.name;
    }
    renderWizard();
}
window.woRequestWorkType = woRequestWorkType;

function woAutoDuration() {
    /* Months between the two dates, filled in rather than asked for. It is
       arithmetic on two dates that are already on the screen, and the field
       stays editable because a programme is sometimes stated in whole months
       that the calendar does not agree with. */
    var start = (document.getElementById('wo-start') || {}).value;
    var end = (document.getElementById('wo-end') || {}).value;
    var box = document.getElementById('wo-dur');
    if (!start || !end || !box) return;
    var a = new Date(start), b = new Date(end);
    if (isNaN(a) || isNaN(b) || b < a) return;
    var months = (b.getFullYear() - a.getFullYear()) * 12 + (b.getMonth() - a.getMonth())
        + (b.getDate() - a.getDate()) / 30.0;
    box.value = Math.round(months * 2) / 2;          // to the half month
}
window.woAutoDuration = woAutoDuration;

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
        field('Contractor *', withAdd('<select id="wo-con" class="form-control"' + dis +
            ' onchange="woPickContractor(this.value)">' +
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
        woVendorCard() +
        field('Work type', '<div style="display:flex;gap:6px;align-items:center;">' +
            '<div style="flex:1;min-width:0;"><select id="wo-wtype" class="form-control"' + dis + '>' +
            options(v.work_types || [], o.work_type, 'name', function (w) {
                return w.name + (w.code ? ' (' + w.code + ')' : ''); }) + '</select></div>' +
            (locked ? '' : '<button type="button" class="btn btn-sm btn-outline" ' +
                'style="white-space:nowrap;" onclick="woRequestWorkType()">Not listed</button>') +
            '</div>',
            (v.may_administer
                ? 'Anything you add here is available to everybody at once.'
                : 'Missing one? Ask for it — it can be used once whoever administers '
                  + 'the system approves it.')) +
        field('Subject *', '<input id="wo-subject" class="form-control" value="' +
            esc(o.subject || '') + '"' + dis +
            ' placeholder="Work order for primary civil STP supply &amp; commissioning for 295 KLD plant">') +
        field('Scope of work', woRichEditor('wo-scope', o.scope_of_work || '', locked)) +
        '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:0 14px;">' +
        field('Commencement *', '<input type="date" id="wo-start" class="form-control" value="' +
            esc(o.commencement_date || '') + '"' + dis + ' onchange="woAutoDuration()">') +
        field('Completion *', '<input type="date" id="wo-end" class="form-control" value="' +
            esc(o.completion_date || '') + '"' + dis + ' onchange="woAutoDuration()">') +
        field('Duration (months)', '<input type="number" step="0.5" id="wo-dur" class="form-control" value="' +
            (o.duration_months || '') + '"' + dis + '>', 'Worked out from the dates; change it if the programme says otherwise.') +
        field('Defect liability (months)', '<input type="number" id="wo-dlp" class="form-control" value="' +
            (o.defect_liability_months || '') + '"' + dis + '>') +
        '</div>' +
        '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:0 14px;">' +
        field('Bank guarantee', '<select id="wo-bg" class="form-control"' + dis +
            ' onchange="renderWizardKeeping()">' +
            '<option value="no"' + (o.bank_guarantee_applicable ? '' : ' selected') + '>Not applicable</option>' +
            '<option value="yes"' + (o.bank_guarantee_applicable ? ' selected' : '') + '>Required</option></select>') +
        field('BG amount', '<input type="number" step="0.01" id="wo-bgamt" class="form-control" value="' +
            (o.bank_guarantee_amount || '') + '"' + dis + '>') +
        field('BG valid until', '<input type="date" id="wo-bgval" class="form-control" value="' +
            esc(o.bank_guarantee_validity || '') + '"' + dis + '>') +
        '</div>' +

        '<div style="margin-top:18px;padding-top:14px;border-top:1px solid var(--border-color);">' +
        '<div style="display:flex;justify-content:space-between;align-items:center;' +
            'gap:10px;flex-wrap:wrap;margin-bottom:10px;">' +
        '<div><h3 style="margin:0;font-size:1rem;">Terms and conditions</h3>' +
        '<p style="margin:2px 0 0;font-size:0.78rem;color:var(--text-secondary);">' +
            'The clauses this order goes out on. The standard set is a starting ' +
            'point, not a policy &mdash; every one of them is edited here.</p></div>' +
        (locked ? '' : '<div style="display:flex;gap:8px;">' +
            '<button class="btn btn-sm btn-outline" onclick="woLoadStandardTerms()">' +
                'Load standard terms</button>' +
            '<button class="btn btn-sm btn-outline" onclick="woTermAdd()">+ Clause</button>' +
            '</div>') + '</div>' + woTermsEditor(locked) + '</div>' +

        (locked ? '' :
        '<div style="display:flex;gap:8px;margin-top:16px;">' +
        '<button class="btn btn-primary" onclick="saveWoDetails()">' +
            (WO.id ? 'Save and continue' : 'Open the order') + '</button>' +
        '<button class="btn btn-outline" onclick="showView(\'subcontracts-view\')">Cancel</button></div>');
}

function woPickContractor(value) {
    // Redrawn so the vendor card follows the picker, keeping everything else
    // that has been typed into the step.
    WO.order = Object.assign({}, WO.order || {}, detailsPayload());
    WO.order.contractor_id = parseInt(value) || null;
    renderWizard();
}
window.woPickContractor = woPickContractor;

function renderWizardKeeping() {
    /* Redraw without losing what is on the screen. Any redraw of step one
       rebuilds the inputs from WO.order, so whatever has been typed since the
       last save has to be folded back in first. */
    if (WO.step === 1) WO.order = Object.assign({}, WO.order || {}, detailsPayload());
    renderWizard();
}
window.renderWizardKeeping = renderWizardKeeping;

function detailsPayload() {
    var val = function (id) { var e = document.getElementById(id); return e ? e.value : ''; };
    var o = WO.order || {};
    var kept = function (field, fallback) {
        return o[field] !== undefined && o[field] !== null ? o[field] : fallback;
    };
    return {
        business_unit_id: parseInt(val('wo-bu')) || null,
        contractor_id: parseInt(val('wo-con')) || null,
        job_id: parseInt(val('wo-job')) || null,
        department: val('wo-dept'), work_type: val('wo-wtype'),
        subject: val('wo-subject'), scope_of_work: woRichValue('wo-scope'),
        commencement_date: val('wo-start'), completion_date: val('wo-end'),
        duration_months: parseFloat(val('wo-dur')) || 0,
        defect_liability_months: parseInt(val('wo-dlp')) || 0,
        bank_guarantee_applicable: val('wo-bg') === 'yes',
        bank_guarantee_amount: parseFloat(val('wo-bgamt')) || 0,
        bank_guarantee_validity: val('wo-bgval'),
        // The commercial terms live on step three, but the whole head is saved
        // in one call - so they are carried through here rather than left out,
        // which would send the defaults and quietly undo what was set there.
        gst_rate: kept('gst_rate', 18),
        tds_rate: kept('tds_rate', 1),
        retention_percent: kept('retention_percent', 0),
        mobilization_advance_percent: kept('mobilization_advance_percent', 0),
        advance_recovery_percent: kept('advance_recovery_percent', 0),
    };
}

async function saveWoHead(payload, nextStep, message) {
    var res = await fetch('/api/wo/orders' + (WO.id ? '/' + WO.id : ''), {
        method: WO.id ? 'PUT' : 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
    });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not save', 'error'); return null; }
    WO.order = out.order;
    WO.id = out.order.id;
    showToast(message || out.message, 'success');
    if (nextStep) WO.step = nextStep;
    return out.order;
}

async function saveWoDetails() {
    var payload = detailsPayload();
    if (!payload.contractor_id) { showToast('Choose the contractor', 'error'); return; }
    if (!payload.department) { showToast('Choose the department', 'error'); return; }
    // Held before the save, because saving replaces WO.order and the terms on
    // the screen would be read back from an order that has not got them yet.
    var terms = WO.terms.slice();
    if (!(await saveWoHead(payload, 2))) return;
    if (terms.length) await putWoTerms(terms, true);
    renderWizard();
}
window.saveWoDetails = saveWoDetails;


/* --- Step 2: the schedule ------------------------------------------------ */

function woLineAmount(l) {
    return (parseFloat(l.quantity) || 0) * (parseFloat(l.unit_rate) || 0);
}

function woBudgetRows() {
    /* The project's allocations, with this order's share recomputed from what
       is on the screen rather than from what was last saved. The whole point
       of showing a budget while pricing is that it moves as the price does;
       one that only updated on save would tell you it was overrun after the
       decision that overran it. */
    var rows = ((WO.order || {}).budgets || []).map(function (b) {
        return Object.assign({}, b, { this_order: 0 });
    });
    var byId = {};
    rows.forEach(function (b) { byId[b.id] = b; });
    WO.boq.forEach(function (l) {
        var b = byId[l.budget_id];
        if (b) b.this_order += woLineAmount(l);
    });
    rows.forEach(function (b) {
        b.available = b.allocated - b.committed - b.this_order;
        b.over = b.allocated > 0 && (b.committed + b.this_order) > b.allocated;
    });
    return rows;
}

function woBudgetBar(b) {
    var base = b.allocated > 0 ? b.allocated : (b.committed + b.this_order) || 1;
    var pct = function (n) { return Math.max(0, Math.min(100, (n / base) * 100)); };
    var tone = b.over ? 'var(--danger-color)' : 'var(--primary-color)';
    return '<div style="padding:10px 0;border-bottom:1px solid var(--border-color);">' +
        '<div style="display:flex;justify-content:space-between;gap:10px;font-size:0.82rem;">' +
            '<span style="font-weight:600;">' + esc(b.name || b.code || 'Cost centre') +
            (b.code && b.name ? ' <span style="font-family:monospace;font-weight:400;' +
                'color:var(--text-secondary);">' + esc(b.code) + '</span>' : '') + '</span>' +
            '<span style="color:' + (b.over ? 'var(--danger-color)' : 'var(--text-secondary)') + ';">' +
            (b.allocated > 0
                ? (b.over ? 'Over by ' + formatCurrency(-b.available)
                          : formatCurrency(b.available) + ' left')
                : 'No allocation set') + '</span></div>' +
        '<div style="display:flex;height:7px;border-radius:4px;overflow:hidden;margin:6px 0 4px;' +
            'background:var(--border-color);">' +
            '<span style="width:' + pct(b.committed) + '%;background:var(--text-secondary);opacity:0.55;"></span>' +
            '<span style="width:' + pct(b.this_order) + '%;background:' + tone + ';"></span>' +
        '</div>' +
        '<div style="font-size:0.72rem;color:var(--text-secondary);">' +
            'Allocated ' + formatCurrency(b.allocated) +
            ' &middot; committed elsewhere ' + formatCurrency(b.committed) +
            ' &middot; this order ' + formatCurrency(b.this_order) + '</div></div>';
}

function woBudgetPanel() {
    var o = WO.order || {};
    if (!o.job_id) {
        return '<p style="font-size:0.8rem;color:var(--text-secondary);padding:8px 0;">' +
            'This order is not against a project, so there is no allocation to spend. ' +
            'Choose one on step 1 to check it against a budget.</p>';
    }
    var rows = woBudgetRows();
    if (!rows.length) {
        return '<p style="font-size:0.8rem;color:var(--text-secondary);padding:8px 0;">' +
            'Nothing allocated on this project yet. Add a cost centre to check what ' +
            'this order spends against it.</p>' +
            '<button class="btn btn-sm btn-outline" onclick="woAddBudget()">+ Cost centre</button>';
    }
    return rows.map(woBudgetBar).join('') +
        '<div style="margin-top:10px;"><button class="btn btn-sm btn-outline" ' +
        'onclick="woAddBudget()">+ Cost centre</button></div>';
}

async function woAddBudget() {
    var o = WO.order || {};
    if (!o.job_id) { showToast('Choose a project first', 'error'); return; }
    var name = prompt('What is the cost centre called? (e.g. Civil - substructure)');
    if (name === null || !name.trim()) return;
    var amount = prompt('How much is allocated to it?');
    if (amount === null) return;
    var res = await fetch('/api/wo/projects/' + o.job_id + '/budgets', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name.trim(),
                               allocated_amount: parseFloat(amount) || 0,
                               department: o.department || '' }),
    });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not add it', 'error'); return; }
    showToast(out.message, 'success');
    await woReload();
}
window.woAddBudget = woAddBudget;

async function woReload() {
    if (!WO.id) { renderWizard(); return; }
    var data = await (await fetch('/api/wo/orders/' + WO.id,
        { credentials: 'include' })).json();
    // The schedule on the screen is what is being edited and may not be saved
    // yet, so only the order around it is refreshed.
    var typed = WO.boq;
    WO.order = data.order;
    WO.boq = typed;
    renderWizard();
}

function stepBoq() {
    var locked = WO.order && !WO.order.editable;
    var v = WO.vocab;
    var budgets = ((WO.order || {}).budgets || []);
    var rows = WO.boq.map(function (l, i) {
        var dis = locked ? ' disabled' : '';
        return '<tr>' +
            '<td><input class="form-control" style="min-width:64px;" value="' + esc(l.activity_no || '') +
                '" oninput="woBoqSet(' + i + ',\'activity_no\',this.value)"' + dis + '></td>' +
            '<td><input class="form-control" style="min-width:96px;" value="' + esc(l.item_code || '') +
                '" oninput="woBoqSet(' + i + ',\'item_code\',this.value)"' + dis + '></td>' +
            '<td style="min-width:280px;">' +
                '<textarea class="form-control" rows="2" ' +
                'placeholder="What the line is" ' +
                'oninput="woBoqSet(' + i + ',\'item_description\',this.value)"' + dis + '>' +
                esc(l.item_description || '') + '</textarea>' +
                // The specification is what the line has to satisfy before it
                // can be measured. Kept under the description rather than in a
                // column, because it is written once and read once.
                '<textarea class="form-control" rows="1" style="margin-top:4px;' +
                'font-size:0.78rem;" placeholder="Technical specification (optional)" ' +
                'oninput="woBoqSet(' + i + ',\'technical_spec\',this.value)"' + dis + '>' +
                esc(l.technical_spec || '') + '</textarea></td>' +
            '<td><select class="form-control" style="min-width:80px;" ' +
                'onchange="woBoqSet(' + i + ',\'uom\',this.value)"' + dis + '>' +
                options(v.uoms, l.uom) + '</select></td>' +
            '<td><input type="number" step="any" class="form-control text-right" style="min-width:90px;" value="' +
                (l.quantity || '') + '" oninput="woBoqSet(' + i + ',\'quantity\',this.value)"' + dis + '></td>' +
            '<td><input type="number" step="any" class="form-control text-right" style="min-width:100px;" value="' +
                (l.unit_rate || '') + '" oninput="woBoqSet(' + i + ',\'unit_rate\',this.value)"' + dis + '></td>' +
            '<td><select class="form-control" style="min-width:130px;" ' +
                'onchange="woBoqSet(' + i + ',\'budget_id\',this.value)"' + dis + '>' +
                options(budgets, l.budget_id, 'id', function (b) {
                    return b.name || b.code || 'Cost centre'; }) + '</select></td>' +
            '<td class="text-right" style="font-weight:600;white-space:nowrap;">' +
                formatCurrency(woLineAmount(l)) + '</td>' +
            '<td class="text-right">' + (locked ? '' :
                '<button class="btn btn-sm btn-outline" onclick="woBoqRemove(' + i + ')">&times;</button>') + '</td>' +
            '</tr>';
    }).join('');

    var gross = WO.boq.reduce(function (t, l) { return t + woLineAmount(l); }, 0);
    var o = WO.order || {};

    return '<div style="display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:18px;' +
        'align-items:start;" class="wo-boq-layout">' +
        '<div>' + (locked ? '' : woImportPanel()) +
        '<div class="table-responsive"><table class="data-table">' +
        '<thead><tr><th>Activity</th><th>Item code</th><th>Description</th><th>UOM</th>' +
        '<th class="text-right">Qty</th><th class="text-right">Rate</th><th>Cost centre</th>' +
        '<th class="text-right">Amount</th><th></th></tr></thead>' +
        '<tbody>' + (rows || '<tr><td colspan="9" style="text-align:center;padding:24px;' +
            'color:var(--text-secondary);">Nothing scheduled yet.</td></tr>') + '</tbody>' +
        '<tfoot><tr><td colspan="7" class="text-right"><strong>Gross</strong></td>' +
        '<td class="text-right"><strong>' + formatCurrency(gross) + '</strong></td><td></td></tr></tfoot>' +
        '</table></div>' +
        (locked ? '' :
        '<div style="display:flex;gap:8px;margin-top:12px;flex-wrap:wrap;">' +
        '<button class="btn btn-outline" onclick="woBoqAdd()">+ Add line</button>' +
        '<button class="btn btn-primary" onclick="saveWoBoq()">Save schedule</button>' +
        '<button class="btn btn-outline" onclick="woGoStep(3)">Skip to billing terms</button>' +
        '</div>') +
        '</div>' +

        // The schedule value and the budget, beside the grid rather than under
        // it: both are being watched while the rates are typed in.
        '<div>' +
        '<div class="widget"><div class="widget-header"><h3>Schedule value</h3></div>' +
        '<div style="padding:12px 16px;">' +
        '<div style="font-size:1.45rem;font-weight:700;">' + formatCurrency(gross) + '</div>' +
        '<p style="font-size:0.76rem;color:var(--text-secondary);margin:4px 0 0;">' +
            WO.boq.length + ' line(s). Tax and deductions are set on step three.</p>' +
        '</div></div>' +
        '<div class="widget" style="margin-top:14px;"><div class="widget-header">' +
            '<h3>Project budget</h3></div>' +
        '<div style="padding:6px 16px 14px;">' + woBudgetPanel() + '</div></div>' +
        '</div></div>';
}


/* --- Two ways to get a schedule in --------------------------------------- */

function woImportPanel() {
    /* The grid is for building a schedule; the import is for the one that
       already exists. It usually arrives as the contractor's own quotation
       with the rates in it, and retyping two hundred priced lines to match a
       heading is how a rate gets typed wrong. */
    var read = WO.imported;
    return '<div style="border:1px dashed var(--border-color);border-radius:8px;' +
        'padding:12px 14px;margin-bottom:14px;">' +
        '<div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;">' +
        '<div style="flex:1;min-width:200px;">' +
        '<div style="font-weight:600;font-size:0.86rem;">Import a BOQ</div>' +
        '<div style="font-size:0.76rem;color:var(--text-secondary);">' +
            'An Excel or CSV schedule, headed however the contractor heads it. ' +
            'Nothing is saved until you have read it back.</div></div>' +
        '<input type="file" id="wo-boq-file" accept=".xlsx,.xls,.csv" ' +
            'class="form-control" style="max-width:230px;" onchange="woImportBoq(this)">' +
        '<a class="btn btn-sm btn-outline" href="/api/wo/boq/template">Template</a>' +
        '</div>' +
        (read ? '<div style="margin-top:10px;padding-top:10px;' +
            'border-top:1px solid var(--border-color);font-size:0.78rem;">' +
            '<div style="color:var(--success-color);font-weight:600;">' +
                esc(read.message) + '</div>' +
            '<div style="color:var(--text-secondary);margin-top:4px;">Read as: ' +
            Object.keys(read.read_as || {}).map(function (heading) {
                return esc(heading) + ' &rarr; ' +
                    esc(String(read.read_as[heading]).replace(/_/g, ' ')); }).join(' &middot; ') +
            '</div>' +
            ((read.ignored_columns || []).length
                ? '<div style="color:var(--text-secondary);margin-top:3px;">Ignored: ' +
                  read.ignored_columns.map(esc).join(', ') + '</div>' : '') +
            '<div style="margin-top:6px;">Check the lines below, then ' +
                '<strong>Save schedule</strong>.</div></div>' : '') +
        '</div>';
}

async function woImportBoq(input) {
    var file = input.files && input.files[0];
    if (!file) return;
    if (WO.boq.length && !confirm(
            'Replace the ' + WO.boq.length + ' line(s) already on this schedule?')) {
        input.value = '';
        return;
    }
    var form = new FormData();
    form.append('file', file);
    var res = await fetch('/api/wo/orders/' + WO.id + '/boq/import',
                          { method: 'POST', credentials: 'include', body: form });
    var out = await res.json();
    input.value = '';
    if (!res.ok) { showToast(out.detail || 'Could not read that sheet', 'error'); return; }
    WO.boq = out.lines;
    WO.imported = out;
    showToast(out.message, 'success');
    renderWizard();
}
window.woImportBoq = woImportBoq;

function woBoqSet(i, key, value) {
    WO.boq[i][key] = key === 'budget_id' ? (parseInt(value) || null) : value;
    // Only the money column is redrawn as you type; redrawing the table would
    // take the caret out of the cell being edited.
    if (key === 'quantity' || key === 'unit_rate' || key === 'budget_id') renderWizard();
}
window.woBoqSet = woBoqSet;

function woBoqAdd() {
    var last = WO.boq[WO.boq.length - 1];
    var next = last ? String(parseFloat(last.activity_no || 0) + 1) + '.0' : '1.0';
    // The cost centre carries down from the line above. A schedule is usually
    // one trade against one allocation, and re-picking it two hundred times is
    // how it ends up picked wrongly.
    WO.boq.push({ activity_no: next, item_code: '', item_description: '',
                  technical_spec: '', uom: 'cum', quantity: '', unit_rate: '',
                  budget_id: last ? (last.budget_id || null) : null });
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
                     item_description: l.item_description,
                     technical_spec: l.technical_spec || '', uom: l.uom,
                     quantity: parseFloat(l.quantity) || 0,
                     unit_rate: parseFloat(l.unit_rate) || 0,
                     budget_id: l.budget_id || null }; }) }),
    });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not save the schedule', 'error'); return; }
    WO.order = out.order;
    WO.boq = out.order.items.slice();
    WO.imported = null;              // it is on the order now, not waiting to be read
    showToast(out.message, 'success');
    WO.step = 3;
    renderWizard();
}
window.saveWoBoq = saveWoBoq;


/* --- Step 3: what it is worth and what comes off it ---------------------- */

function stepBilling() {
    var locked = WO.order && !WO.order.editable;
    var o = WO.order || {}, v = WO.vocab || {};
    var dis = locked ? ' disabled' : '';
    var gross = o.gross_amount || 0;

    var num = function (id, value, step) {
        return '<input type="number" step="' + (step || '0.01') + '" min="0" id="' + id +
            '" class="form-control" value="' + (value || 0) + '"' + dis +
            ' oninput="woBillingPreview()">';
    };

    var gstOptions = (v.gst_rates || [0, 5, 12, 18, 28]).map(function (rate) {
        return '<option value="' + rate + '"' +
            (Number(o.gst_rate) === Number(rate) ? ' selected' : '') + '>' +
            rate + '%</option>'; }).join('');
    var tdsOptions = (v.tds_options || []).map(function (opt) {
        return '<option value="' + opt.rate + '"' +
            (Number(o.tds_rate) === Number(opt.rate) ? ' selected' : '') + '>' +
            esc(opt.label) + '</option>'; }).join('');

    return '<div style="display:grid;grid-template-columns:minmax(0,1fr) 320px;' +
        'gap:18px;align-items:start;" class="wo-boq-layout"><div>' +

        '<div class="widget" style="margin-bottom:16px;">' +
        '<div class="widget-header"><h3>Gross BOQ amount</h3></div>' +
        '<div style="padding:14px 16px;">' +
        '<div style="font-size:1.7rem;font-weight:700;">' + formatCurrency(gross) + '</div>' +
        '<p style="font-size:0.78rem;color:var(--text-secondary);margin:4px 0 0;">' +
            (o.items || []).length + ' scheduled line(s). Change the schedule on ' +
            'step two; everything below is worked out from this figure.</p></div></div>' +

        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:0 16px;">' +
        field('GST rate', '<select id="wo-gst" class="form-control"' + dis +
            ' onchange="woBillingPreview()">' + gstOptions + '</select>',
            'Charged on top of the gross.') +
        field('TDS deduction', '<select id="wo-tds" class="form-control"' + dis +
            ' onchange="woBillingPreview()">' + tdsOptions + '</select>',
            'Withheld out of the gross and paid to the department.') +
        '</div>' +

        '<h3 style="font-size:1rem;margin:16px 0 4px;">Retention and advance</h3>' +
        '<p style="font-size:0.78rem;color:var(--text-secondary);margin:0 0 10px;">' +
            'Neither of these changes what the contract is worth. Retention is held ' +
            'back from each bill and released later; the advance is paid up front ' +
            'and recovered out of the bills.</p>' +
        '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:0 16px;">' +
        field('Retention %', num('wo-ret', o.retention_percent, '0.5'),
              'Typically 5%, half released on completion.') +
        field('Mobilization advance %', num('wo-adv', o.mobilization_advance_percent, '0.5'),
              'Against an equivalent bank guarantee.') +
        field('Advance recovery %', num('wo-advrec', o.advance_recovery_percent, '1'),
              'Taken back from each RA bill.') +
        '</div>' +

        (locked ? '' :
        '<div style="display:flex;gap:8px;margin-top:8px;flex-wrap:wrap;">' +
        '<button class="btn btn-primary" onclick="saveWoBilling()">Save and continue</button>' +
        '<button class="btn btn-outline" onclick="woGoStep(2)">Back to the schedule</button>' +
        '</div>') +

        '</div><div class="widget"><div class="widget-header"><h3>Net contract value</h3></div>' +
        '<div style="padding:12px 16px;" id="wo-billing-preview">' +
        woBillingLines(gross, o.gst_rate, o.tds_rate, o.retention_percent,
                       o.mobilization_advance_percent) +
        '</div></div></div>';
}

function woBillingLines(gross, gstRate, tdsRate, retentionPct, advancePct) {
    var gst = gross * ((gstRate || 0) / 100);
    var tds = gross * ((tdsRate || 0) / 100);
    var net = gross + gst - tds;
    var retention = gross * ((retentionPct || 0) / 100);
    var advance = gross * ((advancePct || 0) / 100);

    var line = function (label, value, muted) {
        return '<div style="display:flex;justify-content:space-between;gap:10px;' +
            'font-size:0.82rem;padding:3px 0;' +
            (muted ? 'color:var(--text-secondary);' : '') + '">' +
            '<span>' + label + '</span><span>' + value + '</span></div>';
    };

    return line('Gross BOQ amount', formatCurrency(gross), true) +
        line('Add: GST @ ' + (gstRate || 0) + '%', formatCurrency(gst), true) +
        line('Less: TDS @ ' + (tdsRate || 0) + '%', '(' + formatCurrency(tds) + ')', true) +
        '<div style="display:flex;justify-content:space-between;font-weight:700;' +
            'padding-top:8px;margin-top:6px;border-top:1px solid var(--border-color);">' +
            '<span>Net contract value</span><span>' + formatCurrency(net) + '</span></div>' +
        ((retention || advance) ?
            '<div style="margin-top:12px;padding-top:10px;' +
                'border-top:1px solid var(--border-color);">' +
            '<div style="font-size:0.72rem;text-transform:uppercase;letter-spacing:0.5px;' +
                'color:var(--text-secondary);margin-bottom:4px;">Timing, not price</div>' +
            (retention ? line('Retention withheld @ ' + retentionPct + '%',
                              formatCurrency(retention), true) : '') +
            (advance ? line('Advance payable @ ' + advancePct + '%',
                            formatCurrency(advance), true) : '') +
            '</div>' : '');
}

function woBillingPreview() {
    var val = function (id) {
        var e = document.getElementById(id); return e ? parseFloat(e.value) || 0 : 0; };
    var host = document.getElementById('wo-billing-preview');
    if (!host) return;
    host.innerHTML = woBillingLines((WO.order || {}).gross_amount || 0,
        val('wo-gst'), val('wo-tds'), val('wo-ret'), val('wo-adv'));
}
window.woBillingPreview = woBillingPreview;

async function saveWoBilling() {
    var val = function (id) {
        var e = document.getElementById(id); return e ? parseFloat(e.value) || 0 : 0; };
    var payload = Object.assign({}, WO.order, {
        gst_rate: val('wo-gst'), tds_rate: val('wo-tds'),
        retention_percent: val('wo-ret'),
        mobilization_advance_percent: val('wo-adv'),
        advance_recovery_percent: val('wo-advrec'),
    });
    if (await saveWoHead(payload, 4, 'Billing terms saved.')) renderWizard();
}
window.saveWoBilling = saveWoBilling;


/* --- The clauses, edited on step one ------------------------------------- */

function woTermsEditor(locked) {
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

    return rows || '<p style="color:var(--text-secondary);font-size:0.82rem;padding:6px 0;">' +
        'No clauses yet. Load the standard set to start from &mdash; it is the ' +
        'eleven this trade argues over, and every one of them is edited here.</p>';
}

function woTermSet(i, key, value) { WO.terms[i][key] = value; }
window.woTermSet = woTermSet;

function woTermAdd() {
    // Whatever is typed into step one is kept: adding a clause must not throw
    // away the subject somebody just wrote.
    if (WO.step === 1) WO.order = Object.assign({}, WO.order || {}, detailsPayload());
    WO.terms.push({ clause_category: WO.vocab.clause_categories[0], clause_text: '' });
    renderWizard();
}
window.woTermAdd = woTermAdd;

function woTermRemove(i) { WO.terms.splice(i, 1); renderWizard(); }
window.woTermRemove = woTermRemove;

async function woLoadStandardTerms() {
    if (WO.step === 1) WO.order = Object.assign({}, WO.order || {}, detailsPayload());
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

async function putWoTerms(terms, quiet) {
    if (!WO.id) return null;
    var res = await fetch('/api/wo/orders/' + WO.id + '/terms', {
        method: 'PUT', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ terms: terms }),
    });
    var out = await res.json();
    if (!res.ok) {
        showToast(out.detail || 'Could not save the terms', 'error');
        return null;
    }
    WO.order = out.order;
    WO.terms = out.order.terms.slice();
    if (!quiet) showToast(out.message, 'success');
    return out.order;
}


/* --- Step 4: read it before signing it ----------------------------------- */

function money2(n) { return formatCurrency(n || 0); }

function stepReview() {
    /* The document, not a summary of it. What is being decided on is the sheet
       of paper that will be signed, so that is what the last step shows -
       watermark, schedule, clauses, signature blocks and all. A summary here
       would be a fifth version of the same figures to keep in step with the
       other four. */
    var o = WO.order;
    if (!o) return '<p>Nothing to review yet.</p>';

    var history = (o.history || []).map(function (h) {
        return '<tr><td>' + esc(h.action) + '</td><td>' + esc(h.actor) + '</td>' +
            '<td>' + esc(h.at) + '</td><td>' + esc(h.comments || '') + '</td></tr>';
    }).join('');

    return woBudgetNotice(o) +
        (o.rejection_reason ?
            '<div style="margin-top:16px;padding:12px 14px;border-radius:8px;' +
            'border:1px solid var(--warning-color);">' +
            '<div style="font-weight:700;font-size:0.86rem;">Sent back</div>' +
            '<div style="font-size:0.82rem;margin-top:2px;">' +
            esc(o.rejection_reason) + '</div></div>' : '') +
        woActions(o) +
        '<div class="widget" style="margin-top:16px;">' +
        '<div class="widget-header"><h3>The document as it will print</h3>' +
        '<div style="display:flex;gap:8px;">' +
        '<a class="btn btn-sm btn-outline" href="/api/wo/orders/' + o.id +
            '/document.pdf" target="_blank" rel="noopener">Download PDF</a>' +
        '<a class="btn btn-sm btn-outline" href="/api/wo/orders/' + o.id +
            '/boq.xlsx">Schedule (Excel)</a>' +
        '<button class="btn btn-sm btn-outline" onclick="woPreview()">Full page</button>' +
        '</div></div>' +
        '<div style="padding:16px;background:rgba(0,0,0,0.18);" id="wo-inline-doc">' +
        (WO.doc ? woDocumentHtml(WO.doc)
                : '<p style="text-align:center;padding:30px;color:var(--text-secondary);">' +
                  'Laying out the document...</p>') + '</div></div>' +
        (history ? '<div class="widget" style="margin-top:16px;">' +
            '<div class="widget-header"><h3>History</h3></div>' +
            '<div class="table-responsive"><table class="data-table">' +
            '<thead><tr><th>Action</th><th>By</th><th>When</th><th>Remarks</th></tr></thead>' +
            '<tbody>' + history + '</tbody></table></div></div>' : '');
}

async function woLoadInlineDocument() {
    /* Fetched rather than assembled from WO.order, so the preview and the PDF
       are the same document by construction - the watermark, the signatory
       names and the printed date are all decided on the server. */
    if (!WO.id) return;
    var res = await fetch('/api/wo/orders/' + WO.id + '/document',
                          { credentials: 'include' });
    if (!res.ok) return;
    WO.doc = await res.json();
    var host = document.getElementById('wo-inline-doc');
    if (host && WO.step === 4) host.innerHTML = woDocumentHtml(WO.doc);
}

function woBudgetNotice(o) {
    /* Said on the review, where the decision is taken, and not only at the
       moment the approval is refused. An approver who finds out mid-click is
       an approver who overrides to get on with their day. */
    var warnings = o.budget_warnings || [];
    if (!warnings.length) return '';
    return '<div style="margin-top:16px;padding:12px 14px;border-radius:8px;' +
        'border:1px solid var(--danger-color);background:rgba(220,38,38,0.06);">' +
        '<div style="font-weight:700;font-size:0.86rem;margin-bottom:4px;">' +
        'This order overruns the project allocation</div>' +
        '<ul style="margin:0;padding-left:18px;font-size:0.82rem;">' +
        warnings.map(function (w) { return '<li>' + esc(w) + '</li>'; }).join('') +
        '</ul><p style="font-size:0.76rem;color:var(--text-secondary);margin:6px 0 0;">' +
        'It can still be approved, but the approver will have to say why.</p></div>';
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
        buttons.push('<button class="btn btn-outline" onclick="woAct(\'cancel\', true)">Cancel the order</button>');
    if (o.editable)
        buttons.push('<button class="btn btn-outline" onclick="woGoStep(1)">Keep editing</button>');
    buttons.push('<button class="btn btn-outline" onclick="woPreview()">Print</button>');
    buttons.push('<button class="btn btn-outline" onclick="showView(\'subcontracts-view\');loadSubcontracts()">Back to list</button>');
    return '<div style="display:flex;gap:8px;margin-top:16px;flex-wrap:wrap;">' +
        buttons.join('') + '</div>' +
        (o.editable
            ? '<p style="font-size:0.76rem;color:var(--text-secondary);margin:8px 0 0;">' +
              'It is saved as a draft already &mdash; every step saves as you go. ' +
              'Submitting is what asks somebody to sign it off.</p>' : '');
}

async function woAct(action, needsReason) {
    var comments = '', override = false;

    // Approving over the allocation is allowed, but not by accident: the
    // overrun is named, and the reason is what gets written into the history
    // beside the figures it overran.
    var warnings = (WO.order || {}).budget_warnings || [];
    if (action === 'approve' && warnings.length) {
        comments = prompt('This order overruns the project allocation:\n\n' +
            warnings.join('\n') + '\n\nApprove it anyway? Say why:');
        if (comments === null) return;
        if (!comments.trim()) { showToast('An overrun has to be explained', 'error'); return; }
        override = true;
    } else if (needsReason) {
        comments = prompt(action === 'reject'
            ? 'Why is this going back?' : 'Why is this being cancelled?');
        if (comments === null) return;
        if (!comments.trim()) { showToast('A reason is required', 'error'); return; }
    }
    var res = await fetch('/api/wo/orders/' + WO.id + '/' + action, {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ comments: comments, override: override }),
    });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not do that', 'error'); return; }
    showToast(out.message, 'success');
    // An amendment hands back a different order, so follow it there.
    WO.order = out.order;
    WO.id = out.order.id;
    WO.boq = (out.order.items || []).slice();
    WO.terms = (out.order.terms || []).slice();
    WO.imported = null;
    WO.doc = null;                   // the watermark has just changed
    WO.step = out.order.editable ? 1 : 4;
    renderWizard();
}
window.woAct = woAct;


/* --- The document itself -------------------------------------------------
   The same payload the PDF is built from, drawn as the sheet of paper it will
   be printed on. Nobody should have to download a file to find out what they
   are about to sign, and a preview that looked different from the print would
   be worse than no preview at all.
   ------------------------------------------------------------------------ */

function woDate(value) {
    var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(value || ''));
    return m ? m[3] + '/' + m[2] + '/' + m[1] : esc(value || '');
}

function woFacts(pairs) {
    return '<div class="wo-facts">' + pairs.filter(function (p) { return p[1]; })
        .map(function (p) {
            return '<span class="wo-label">' + esc(p[0]) + '</span>' +
                '<span>' + esc(String(p[1])) + '</span>';
        }).join('') + '</div>';
}

function woDocumentHtml(d) {
    var bu = d.business_unit_detail || {}, con = d.contractor_detail || {};
    var nl = function (s) { return esc(s || '').replace(/\n/g, '<br>'); };

    var items = (d.items || []).map(function (it, i) {
        return '<tr><td>' + esc(it.activity_no || (i + 1)) + '</td>' +
            '<td>' + esc(it.item_code || '') + '</td>' +
            '<td>' + nl(it.item_description) +
                ((it.technical_spec || '').trim()
                    ? '<div style="font-size:0.68rem;color:#6b7280;margin-top:2px;">' +
                      nl(it.technical_spec) + '</div>' : '') + '</td>' +
            '<td>' + esc(it.uom || '') + '</td>' +
            '<td class="num">' + (it.quantity || 0).toLocaleString('en-IN') + '</td>' +
            '<td class="num">' + (it.unit_rate || 0).toLocaleString('en-IN',
                { minimumFractionDigits: 2, maximumFractionDigits: 4 }) + '</td>' +
            '<td class="num">' + formatCurrency(it.total_amount) + '</td></tr>';
    }).join('') || '<tr><td colspan="7" style="text-align:center;padding:16px;">' +
        'No items scheduled.</td></tr>';

    var clauses = (d.terms || []).map(function (t, i) {
        return '<div class="wo-clause"><div class="wo-clause-head">' + (i + 1) + '. ' +
            esc(t.clause_category || 'Clause') + '</div>' +
            '<div class="wo-clause-text">' + nl(t.clause_text) + '</div></div>';
    }).join('') || '<p class="wo-muted">No additional terms were attached to this order.</p>';

    var signs = (d.signatures || []).map(function (s) {
        return '<div class="wo-sign"><span class="wo-label">' + esc(s.role) + '</span>' +
            '<div><div class="wo-sign-name">' + (esc(s.name) || '&nbsp;') + '</div>' +
            '<div class="wo-label" style="letter-spacing:0;text-transform:none;">' +
            esc(s['for'] || '') + '</div></div></div>';
    }).join('');

    return '<div class="wo-sheet">' +
        (d.watermark ? '<div class="wo-watermark"><span>' + esc(d.watermark) +
            '</span></div>' : '') +

        '<div class="wo-head"><div>' +
            (bu.logo_url ? '<img src="' + esc(bu.logo_url) + '" alt="" ' +
                'style="max-height:56px;max-width:180px;margin-bottom:6px;' +
                'display:block;">' : '') +
            '<div class="wo-head-name">' + esc(bu.name || d.company || '') + '</div>' +
            (bu.address ? '<div class="wo-muted" style="font-size:0.74rem;">' +
                nl(bu.address) + '</div>' : '') +
            ((bu.gstin || bu.pan) ? '<div class="wo-muted" style="font-size:0.72rem;">' +
                [bu.gstin ? 'GSTIN: ' + esc(bu.gstin) : '',
                 bu.pan ? 'PAN: ' + esc(bu.pan) : ''].filter(Boolean).join(' &nbsp;|&nbsp; ') +
                '</div>' : '') +
        '</div><div><div class="wo-doctitle">WORK ORDER</div>' +
            '<div class="wo-number" style="text-align:right;">' + esc(d.wo_number) + '</div>' +
            (d.amendment_no ? '<div class="wo-muted" style="font-size:0.7rem;text-align:right;">' +
                'Amendment ' + d.amendment_no + '</div>' : '') +
        '</div></div>' +

        '<div class="wo-cols" style="margin-top:14px;"><div>' +
            '<span class="wo-label">To</span>' +
            '<div style="font-weight:700;margin-top:2px;">' +
                esc(con.company_name || d.contractor || '') + '</div>' +
            (con.contact_person ? '<div>Kind attn: ' + esc(con.contact_person) + '</div>' : '') +
            (con.address ? '<div class="wo-muted">' + nl(con.address) + '</div>' : '') +
            '<div class="wo-muted" style="font-size:0.72rem;margin-top:3px;">' +
                [con.gst_number ? 'GSTIN: ' + esc(con.gst_number) : '',
                 con.pan ? 'PAN: ' + esc(con.pan) : '',
                 con.vendor_code ? 'Vendor: ' + esc(con.vendor_code) : ''
                ].filter(Boolean).join(' &nbsp;|&nbsp; ') + '</div>' +
        '</div><div>' + woFacts([
            ['Date', woDate((d.printed_at || '').split('  ')[0]) || d.printed_at],
            ['Financial year', d.financial_year], ['Project', d.project],
            ['Department', d.department], ['Work type', d.work_type],
            ['Status', d.status]]) + '</div></div>' +

        (d.subject ? '<div class="wo-band" style="margin-top:14px;">' +
            '<strong>Sub:</strong> ' + esc(d.subject) + '</div>' : '') +

        '<p style="margin-top:14px;">Dear Sir,</p>' +
        '<p style="text-align:justify;">With reference to your offer and the discussions ' +
        'held thereafter, we are pleased to place this work order on you for the work ' +
        'described below and scheduled in Annexure I, at the rates stated therein and ' +
        'subject to the terms and conditions at Annexure II, which form an integral ' +
        'part of this order.</p>' +

        // The scope keeps its formatting. It is written in the editor on step
        // one and narrowed to a known set of tags on the way into the
        // database, so what is rendered here is bold, italic and bullets and
        // nothing that was not one of those when it was saved.
        (d.scope_of_work ? '<div class="wo-section">Scope of work</div>' +
            '<div style="text-align:justify;">' + d.scope_of_work + '</div>' : '') +

        '<div class="wo-section">Programme and securities</div>' +
        '<div class="wo-cols">' +
            woFacts([['Commencement', woDate(d.commencement_date)],
                     ['Completion', woDate(d.completion_date)],
                     ['Duration', d.duration_months ? d.duration_months + ' months' : '']]) +
            woFacts([['Defect liability', d.defect_liability_months
                        ? d.defect_liability_months + ' months' : 'Not applicable'],
                     ['Bank guarantee', d.bank_guarantee_applicable
                        ? formatCurrency(d.bank_guarantee_amount) : 'Not applicable'],
                     ['BG valid until', d.bank_guarantee_applicable
                        ? woDate(d.bank_guarantee_validity) : '']]) +
        '</div>' +

        '<div class="wo-section">Order value</div>' +
        '<table class="wo-money"><tbody>' +
            '<tr><td>Gross order value</td><td class="num" style="text-align:right;">' +
                formatCurrency(d.gross_amount) + '</td></tr>' +
            '<tr><td>Add: GST @ ' + d.gst_rate + '%</td><td style="text-align:right;">' +
                formatCurrency(d.gst_amount) + '</td></tr>' +
            '<tr><td>Less: TDS @ ' + d.tds_rate + '% (withheld at source)</td>' +
                '<td style="text-align:right;">(' + formatCurrency(d.tds_amount) + ')</td></tr>' +
            '<tr><td>Net order value payable</td><td style="text-align:right;">' +
                formatCurrency(d.net_order_value) + '</td></tr>' +
        '</tbody></table>' +
        '<div class="wo-band" style="margin-top:8px;font-size:0.78rem;">' +
            '<strong>In words:</strong> ' + esc(d.amount_in_words || '') + '</div>' +

        // Stated under the value rather than inside it: both are about when
        // the money moves, not what it comes to.
        (d.retention_percent ?
            '<p class="wo-muted" style="font-size:0.72rem;margin-top:6px;">' +
            'Retention of ' + d.retention_percent + '% (' +
            formatCurrency(d.retention_amount) + ') shall be withheld from each ' +
            'certified bill and released in accordance with the retention clause.' +
            '</p>' : '') +
        (d.mobilization_advance_percent ?
            '<p class="wo-muted" style="font-size:0.72rem;margin-top:4px;">' +
            'A mobilization advance of ' + d.mobilization_advance_percent + '% (' +
            formatCurrency(d.mobilization_advance_amount) + ') is payable against an ' +
            'equivalent bank guarantee' +
            (d.advance_recovery_percent
                ? ', recovered at ' + d.advance_recovery_percent +
                  '% of each Running Account bill' : '') + '.</p>' : '') +

        '<div class="wo-break"></div>' +
        '<div style="text-align:center;font-weight:700;font-size:0.95rem;">' +
            'Annexure I &mdash; Schedule of work</div>' +
        '<table class="wo-table" style="margin-top:10px;"><thead><tr>' +
            '<th>Activity</th><th>Item code</th><th>Description of work</th><th>UOM</th>' +
            '<th class="num">Qty</th><th class="num">Rate</th><th class="num">Amount</th>' +
            '</tr></thead><tbody>' + items + '</tbody>' +
            '<tfoot><tr><td colspan="6" style="text-align:right;">Total</td>' +
            '<td class="num">' + formatCurrency(d.gross_amount) + '</td></tr></tfoot></table>' +
        '<p class="wo-muted" style="font-size:0.72rem;margin-top:8px;">' +
            'Quantities are provisional and shall be paid for on the basis of work actually ' +
            'executed and jointly recorded in the Measurement Book.</p>' +

        '<div class="wo-break"></div>' +
        '<div style="text-align:center;font-weight:700;font-size:0.95rem;margin-bottom:12px;">' +
            'Annexure II &mdash; Terms and conditions</div>' + clauses +

        '<div class="wo-section" style="margin-top:18px;">Signatures</div>' +
        '<div class="wo-signs">' + signs + '</div>' +
        '<p class="wo-muted" style="font-size:0.7rem;margin-top:8px;">' +
            'This work order is issued in duplicate. The Contractor shall return one copy ' +
            'duly signed and stamped in token of unconditional acceptance within seven days ' +
            'of receipt.</p>' +
    '</div>';
}

async function woPreview(id) {
    var orderId = id || WO.id;
    if (!orderId) { showToast('Save the order first', 'error'); return; }
    var host = document.getElementById('sc-document');
    showView('subcontract-document-view');
    host.innerHTML = '<p style="text-align:center;padding:40px;color:var(--text-secondary);">' +
        'Laying out the document...</p>';
    var res = await fetch('/api/wo/orders/' + orderId + '/document',
        { credentials: 'include' });
    if (!res.ok) {
        host.innerHTML = '<p style="text-align:center;padding:40px;color:var(--text-secondary);">' +
            'Could not load the document.</p>';
        return;
    }
    var doc = await res.json();
    WO.id = orderId;
    var pdf = document.getElementById('sc-doc-pdf');
    if (pdf) pdf.href = '/api/wo/orders/' + orderId + '/document.pdf';
    host.innerHTML = woDocumentHtml(doc);
}
window.woPreview = woPreview;


function renderWizard() {
    var host = document.getElementById('sc-wizard');
    if (!host) return;
    var step = WO.step === 1 ? stepDetails()
             : WO.step === 2 ? stepBoq()
             : WO.step === 3 ? stepBilling() : stepReview();
    host.innerHTML = wizardHeader() + step;
    // The document is fetched after the step is on the screen, so the rest of
    // it is usable while the layout is being fetched.
    if (WO.step === 4) woLoadInlineDocument();
}
window.renderWizard = renderWizard;
