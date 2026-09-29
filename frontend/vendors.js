/* ===========================================================================
   vendors.js - the sub contractor register: every gang with its vendor code
   and its Sub Contractor Registration Form.

   The office kept these as one workbook, a sheet per gang, IV0001 onwards.
   Here each is a row: the form filled in box for box, printed and downloaded
   in the same layout, and signed off before an order is issued to them.
   Somebody on site can register a gang; somebody with the right to approve
   takes them on. The old workbook imports once.
   =========================================================================== */

var VENDORS = { list: [], editing: null, status: '' };
var VENDOR_TONE = { APPROVED: 'good', PENDING: 'wait', REJECTED: 'bad' };
var VENDOR_WORD = { APPROVED: 'Registered', PENDING: 'Awaiting approval', REJECTED: 'Sent back' };
var VENDOR_DOCS = [['gst', 'A) GST Certificate'], ['pan', 'B) PAN Card'], ['aadhaar', 'C) Aadhar Card'],
                   ['photos', 'D) PassPort Size Photos 2Nos'], ['cheque', 'E) Cancelled Cheque'],
                   ['esi_pf', 'F) ESI & PF Reg (if any)']];

async function loadVendors() {
    var body = document.getElementById('vendors-body');
    if (!body) return;
    var q = (document.getElementById('vendors-q') || {}).value || '';
    var status = VENDORS.status || '';
    var res = await fetch('/api/wo/contractors?q=' + encodeURIComponent(q) + '&status=' + encodeURIComponent(status),
                          { credentials: 'include' });
    if (!res.ok) { body.innerHTML = '<tr><td colspan="7">Could not load the register.</td></tr>'; return; }
    var d = await res.json();
    VENDORS.list = d.contractors || [];
    var s = d.summary || {};
    var tabs = [['', 'All vendors', (s.registered || 0) + (s.pending || 0) + (s.sent_back || 0)],
                ['APPROVED', 'Registered', s.registered || 0], ['PENDING', 'Awaiting approval', s.pending || 0],
                ['REJECTED', 'Sent back', s.sent_back || 0]];
    document.getElementById('vendors-tabs').innerHTML = tabs.map(function (t) {
        return '<button class="tab' + (t[0] === status ? ' active' : '') + '" onclick="vendorTab(\'' + t[0] + '\')">' +
            esc(t[1]) + ' <span style="font-size:0.75rem;padding:1px 7px;border-radius:9px;margin-left:4px;' +
            (t[0] === 'PENDING' && t[2] ? 'background:var(--warning-color);color:#fff;' : 'background:var(--border-light);') +
            '">' + t[2] + '</span></button>';
    }).join('');
    body.innerHTML = VENDORS.list.length ? VENDORS.list.map(vendorRow).join('') :
        '<tr><td colspan="7" style="text-align:center;padding:30px;color:var(--text-secondary);">' +
        (q || status ? 'Nobody matches that.' : 'No sub contractors yet. Register one, or import the registration forms workbook.') +
        '</td></tr>';
}
window.loadVendors = loadVendors;

function vendorRow(c) {
    var missing = [];
    if (!c.pan) missing.push('PAN');
    if (!c.bank_account || !c.bank_ifsc) missing.push('bank');
    var act = '';
    if (c.registration_status === 'PENDING' && can('subcontracts.approve'))
        act = '<button class="btn btn-sm btn-primary" onclick="vendorDecide(' + c.id + ',\'approve\')">Approve</button> ' +
              '<button class="btn btn-sm btn-outline" onclick="vendorDecide(' + c.id + ',\'reject\')">Send back</button> ';
    return '<tr>' +
        '<td style="font-family:monospace;font-weight:700;white-space:nowrap;">' + esc(c.vendor_code || '—') + '</td>' +
        '<td><div style="font-weight:600;">' + esc(c.company_name) + '</div>' +
            '<div style="font-size:0.75rem;color:var(--text-secondary);">' +
            esc([c.nature_of_work, [c.city, c.state].filter(Boolean).join(', ')].filter(Boolean).join(' · ')) + '</div></td>' +
        '<td style="font-size:0.82rem;">' + esc(c.registered_project || '') + '</td>' +
        '<td style="font-size:0.8rem;font-family:monospace;">' + esc(c.pan || '') +
            (c.gst_number ? '<div>' + esc(c.gst_number) + '</div>' : '') + '</td>' +
        '<td style="font-size:0.8rem;">' + esc(c.bank_name || '') +
            (c.bank_account ? '<div style="font-family:monospace;">' + esc(c.bank_account) + ' · ' + esc(c.bank_ifsc || '') + '</div>' : '') + '</td>' +
        '<td>' + statusPill(VENDOR_WORD[c.registration_status] || c.registration_status, VENDOR_TONE[c.registration_status] || 'calm') +
            (missing.length ? '<div style="font-size:0.72rem;color:var(--warning-color);margin-top:3px;">No ' + missing.join(' or ') + ' on file</div>' : '') +
            (c.registration_status === 'REJECTED' && c.rejection_reason
                ? '<div style="font-size:0.72rem;color:var(--text-secondary);margin-top:3px;">' + esc(c.rejection_reason) + '</div>' : '') +
            (c.registration_status === 'PENDING' && c.registered_by_name
                ? '<div style="font-size:0.72rem;color:var(--text-secondary);margin-top:3px;">by ' + esc(c.registered_by_name) + '</div>' : '') +
        '</td>' +
        '<td class="text-right"><div style="display:flex;flex-wrap:wrap;gap:4px;justify-content:flex-end;min-width:150px;">' + act +
            '<button class="btn btn-sm btn-outline" onclick="openVendorForm(' + c.id + ')">Form</button>' +
            '<a class="btn btn-sm btn-outline" href="/api/wo/contractors/' + c.id + '/registration.pdf" target="_blank" rel="noopener" ' +
                'title="The registration form as it is signed">PDF</a>' +
            '<a class="btn btn-sm btn-outline" href="/api/wo/contractors/' + c.id + '/registration.xlsx" title="As a workbook">Excel</a>' +
        '</div></td></tr>';
}

function vendorTab(status) {
    VENDORS.status = status;
    loadVendors();
}
window.vendorTab = vendorTab;

var vendorSearchTimer = null;
function vendorSearch() {
    clearTimeout(vendorSearchTimer);
    vendorSearchTimer = setTimeout(loadVendors, 250);
}
window.vendorSearch = vendorSearch;

/* --- The form, box for box ------------------------------------------------- */

function vfInput(id, label, value, opts) {
    opts = opts || {};
    var input = opts.area
        ? '<textarea class="form-control" id="' + id + '" rows="2">' + esc(value || '') + '</textarea>'
        : '<input class="form-control" id="' + id + '" type="' + (opts.type || 'text') + '" value="' + esc(value || '') + '"' +
          (opts.upper ? ' style="text-transform:uppercase;"' : '') + (opts.placeholder ? ' placeholder="' + esc(opts.placeholder) + '"' : '') + '>';
    return '<div class="form-group"' + (opts.full ? ' style="grid-column:1/-1;"' : '') + '><label>' + esc(label) + '</label>' + input + '</div>';
}

function vfVal(id) {
    var el = document.getElementById(id);
    return el ? el.value.trim() : '';
}

function openVendorForm(id) {
    var c = VENDORS.list.filter(function (x) { return x.id === id; })[0] || {};
    VENDORS.editing = c.id || null;
    VENDORS.pendingFiles = {};
    var docs = c.documents || [];
    var files = c.document_files || {};
    var section = function (t) {
        return '<div style="grid-column:1/-1;font-weight:700;font-size:0.85rem;background:var(--bg-secondary,#f1f5f9);' +
            'padding:6px 10px;border-radius:6px;margin:10px 0 6px;">' + esc(t) + '</div>';
    };
    document.getElementById('vendor-form-title').textContent =
        c.id ? 'Registration form - ' + (c.vendor_code || '') + ' ' + c.company_name : 'Sub Contractor Registration Form';
    document.getElementById('vendor-form-body').innerHTML =
        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:0 14px;">' +
        vfInput('vf-project', 'Project', c.registered_project, { full: true, placeholder: 'CONSTRUCTION OF APTIDCO EWS HOUSES' }) +
        vfInput('vf-code', 'Vendor code', c.vendor_code, { upper: true, placeholder: 'Next in the series if left blank' }) +
        vfInput('vf-joining', 'Date of joining', c.joining_date, { type: 'date' }) +
        section('1. Subcontractor Personal Details') +
        vfInput('vf-name', 'Name of the Sub Contractor *', c.company_name, { full: true, placeholder: 'M/s ...' }) +
        vfInput('vf-address', 'Residential address', c.address, { area: true, full: true }) +
        vfInput('vf-pin', 'Pin code', c.pin_code) +
        vfInput('vf-city', 'City', c.city) +
        vfInput('vf-state', 'State', c.state) +
        vfInput('vf-nature', 'Nature of work', c.nature_of_work, { placeholder: 'Putty and Painting works' }) +
        vfInput('vf-phone', 'Tel no.', c.phone_number, { type: 'tel' }) +
        vfInput('vf-email', 'E-mail', c.email, { type: 'email' }) +
        vfInput('vf-contact', 'Name of contact person', c.contact_person) +
        vfInput('vf-entity', 'Type of entity', c.entity_type, { placeholder: 'Individual, proprietorship, firm...' }) +
        vfInput('vf-pan', 'PAN', c.pan, { upper: true, placeholder: 'AFVPF9080M' }) +
        vfInput('vf-gst', 'GST Reg No', c.gst_number, { upper: true, placeholder: '37AAAPR1234C1Z5' }) +
        vfInput('vf-aadhaar', 'Aadhaar', c.aadhaar, { placeholder: 'Twelve digits' }) +
        section('2. Bank details') +
        vfInput('vf-bank', 'Bank name', c.bank_name) +
        vfInput('vf-branch', 'Branch', c.bank_branch) +
        vfInput('vf-account', 'Account no', c.bank_account) +
        vfInput('vf-ifsc', 'IFSC code', c.bank_ifsc, { upper: true }) +
        section('3. Documents Required') +
        '<div style="grid-column:1/-1;display:grid;grid-template-columns:1fr 1fr;gap:8px 14px;font-size:0.85rem;">' +
        VENDOR_DOCS.map(function (d) {
            var fname = files[d[0]] || '';
            var viewLink = c.id && fname
                ? ' <a href="/api/wo/contractors/' + c.id + '/documents/' + d[0] + '" target="_blank" rel="noopener" style="font-size:0.78rem;color:var(--primary-color);text-decoration:underline;">' + esc(fname) + '</a>'
                : '';
            return '<div>' +
                '<label style="display:flex;gap:8px;align-items:center;font-weight:400;"><input type="checkbox" class="vf-doc" value="' +
                d[0] + '"' + (docs.indexOf(d[0]) >= 0 ? ' checked' : '') + '> ' + esc(d[1]) + '</label>' +
                '<div style="display:flex;gap:8px;align-items:center;margin:2px 0 0 24px;">' +
                '<input type="file" accept=".pdf,image/*" id="vf-doc-file-' + d[0] + '" style="font-size:0.78rem;max-width:180px;" ' +
                'onchange="vendorDocFileChosen(\'' + d[0] + '\', this)">' +
                '<span id="vf-doc-file-name-' + d[0] + '" style="font-size:0.78rem;color:var(--text-secondary);">' + viewLink + '</span>' +
                '</div></div>';
        }).join('') + '</div>' +
        section('Declaration') +
        '<label style="grid-column:1/-1;display:flex;gap:8px;align-items:flex-start;font-weight:400;font-size:0.82rem;">' +
            '<input type="checkbox" id="vf-declared"' + (c.declaration_signed ? ' checked' : '') + ' style="margin-top:3px;"> ' +
            'The sub contractor has signed the declaration: the information is correct, they agree to the Contract for ' +
            'Services and the Health &amp; Safety guidance, will report any change of bank, address or contact, and ' +
            'have given the documents and photo ID.</label>' +
        '</div>' +
        (c.id ? '' : '<p style="font-size:0.78rem;color:var(--text-secondary);margin-top:10px;">Registered by a member of staff, ' +
            'the form waits in Approvals until somebody who approves work orders signs it off. No order is issued to a gang ' +
            'whose form is not signed off.</p>');
    openModal('vendor-form-modal');
}
window.openVendorForm = openVendorForm;

function vendorDocFileChosen(key, input) {
    var file = input.files && input.files[0];
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) {
        showToast('That file is too large - keep it under 5 MB.', 'error');
        input.value = '';
        return;
    }
    var reader = new FileReader();
    reader.onload = function () {
        VENDORS.pendingFiles = VENDORS.pendingFiles || {};
        VENDORS.pendingFiles[key] = { name: file.name, data: reader.result };
        var box = document.querySelector('.vf-doc[value="' + key + '"]');
        if (box) box.checked = true;
        var label = document.getElementById('vf-doc-file-name-' + key);
        if (label) label.textContent = file.name;
    };
    reader.onerror = function () { showToast('Could not read that file', 'error'); };
    reader.readAsDataURL(file);
}
window.vendorDocFileChosen = vendorDocFileChosen;

async function saveVendorForm() {
    var body = {
        company_name: vfVal('vf-name'), vendor_code: vfVal('vf-code'), registered_project: vfVal('vf-project'),
        joining_date: vfVal('vf-joining'), address: vfVal('vf-address'), pin_code: vfVal('vf-pin'),
        city: vfVal('vf-city'), state: vfVal('vf-state'), nature_of_work: vfVal('vf-nature'),
        phone_number: vfVal('vf-phone'), email: vfVal('vf-email'), contact_person: vfVal('vf-contact'),
        entity_type: vfVal('vf-entity'), pan: vfVal('vf-pan'), gst_number: vfVal('vf-gst'), aadhaar: vfVal('vf-aadhaar'),
        bank_name: vfVal('vf-bank'), bank_branch: vfVal('vf-branch'), bank_account: vfVal('vf-account'),
        bank_ifsc: vfVal('vf-ifsc'),
        documents: Array.prototype.map.call(document.querySelectorAll('.vf-doc:checked'), function (x) { return x.value; }),
        declaration_signed: !!(document.getElementById('vf-declared') || {}).checked,
    };
    if (VENDORS.pendingFiles && Object.keys(VENDORS.pendingFiles).length) {
        body.document_files = VENDORS.pendingFiles;
    }
    if (!body.company_name) { showToast('The form needs the name of the sub contractor', 'error'); return; }
    var id = VENDORS.editing;
    var res = await fetch('/api/wo/contractors' + (id ? '/' + id : ''), {
        method: id ? 'PUT' : 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Not saved', 'error'); return; }
    closeModal('vendor-form-modal');
    showToast(out.message || 'Saved', 'success');
    loadVendors();
}
window.saveVendorForm = saveVendorForm;

async function vendorDecide(id, decision) {
    var body = {};
    if (decision === 'reject') {
        var why = prompt('What is wrong with the form?');
        if (why === null) return;
        if (!why.trim()) { showToast('Say what needs putting right', 'error'); return; }
        body.comments = why;
    }
    var res = await fetch('/api/wo/contractors/' + id + '/' + decision, {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    var out = await res.json();
    showToast(res.ok ? out.message : (out.detail || 'Could not do that'), res.ok ? 'success' : 'error');
    loadVendors();
    if (typeof refreshApprovalBadge === 'function') refreshApprovalBadge();
}
window.vendorDecide = vendorDecide;

/* --- The old workbook, brought in once ------------------------------------------ */

async function importVendorForms(input) {
    var file = input.files && input.files[0];
    input.value = '';
    if (!file) return;
    var fd = new FormData();
    fd.append('file', file);
    showToast('Reading the registration forms...', 'info');
    var res = await fetch('/api/wo/contractors/import', { method: 'POST', credentials: 'include', body: fd });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not import it', 'error'); return; }
    var notes = (out.skipped || []).concat(out.warnings || []);
    document.getElementById('vendor-import-result').innerHTML =
        '<div class="widget" style="margin-bottom:18px;"><div class="widget-content" style="padding:14px 18px;">' +
        '<strong>' + esc(out.message) + '</strong>' +
        (notes.length ? '<p style="font-size:0.8rem;color:var(--text-secondary);margin:8px 0 4px;">Worth a look - these were ' +
            'left blank or not brought in:</p><ul style="font-size:0.8rem;margin:0 0 0 18px;max-height:220px;overflow:auto;">' +
            notes.map(function (n) { return '<li>' + esc(n) + '</li>'; }).join('') + '</ul>' : '') +
        '</div></div>';
    showToast(out.message, notes.length ? 'warning' : 'success');
    loadVendors();
}
window.importVendorForms = importVendorForms;


/* --- The four steps of subcontract work, across the top of each of its screens ---
   Register the vendor, issue the work order, measure in the book, bill it.
   The same strip on every one of those screens, so it is always plain which
   step this is and where the next one is. */

var SC_STEPS = [['vendors', '1. Vendor Register', "showView('vendors-view')"],
                ['orders', '2. Work Orders', "showView('subcontracts-view')"],
                ['mb', '3. Measurement Book', "openSubTab('mb')"],
                ['bills', '4. RA Bills', "openSubTab('bills')"]];

function renderScFlow(active) {
    document.querySelectorAll('.sc-flow').forEach(function (host) {
        var here = host.dataset.sc === 'bills' ? (active || host.dataset.active || 'bills') : host.dataset.sc;
        host.dataset.active = here;
        host.innerHTML = SC_STEPS.map(function (st) {
            return '<button class="tab' + (st[0] === here ? ' active' : '') + '" onclick="' + st[2] + '">' + esc(st[1]) + '</button>';
        }).join('');
    });
}
window.renderScFlow = renderScFlow;
renderScFlow();
