/* What prints on the company's documents, kept up in one place.

   The letterhead of each business unit (name, address, GSTIN, PAN, logo),
   a gang's particulars (PAN, GSTIN, address, contact, bank), the company's
   own general conditions for work orders, and the signatures and seal. Each
   could be typed once and never corrected; these screens let them be. */

/* --- Pictures: a logo, a signature, a seal ------------------------------- */

/* Read a picture file into a small PNG carried in the page. A photographed
   signature on white paper has its white made see-through, so it sits on the
   form like ink rather than as a white patch. */
function readPicture(file, maxW, maxH, clearWhite, done) {
    if (!file) return;
    if (!/^image\/(png|jpe?g|gif|webp|bmp)$/i.test(file.type)) {
        showToast('Choose a picture - PNG or JPEG', 'error');
        return;
    }
    var reader = new FileReader();
    reader.onload = function () {
        var img = new Image();
        img.onload = function () {
            var scale = Math.min(1, maxW / img.width, maxH / img.height);
            var canvas = document.createElement('canvas');
            canvas.width = Math.max(1, Math.round(img.width * scale));
            canvas.height = Math.max(1, Math.round(img.height * scale));
            var ctx = canvas.getContext('2d');
            ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
            if (clearWhite) {
                var data = ctx.getImageData(0, 0, canvas.width, canvas.height);
                for (var i = 0; i < data.data.length; i += 4) {
                    var d = data.data;
                    if (d[i] > 225 && d[i + 1] > 225 && d[i + 2] > 225) d[i + 3] = 0;
                }
                ctx.putImageData(data, 0, 0);
            }
            done(canvas.toDataURL('image/png'));
        };
        img.onerror = function () { showToast('That picture could not be read', 'error'); };
        img.src = reader.result;
    };
    reader.readAsDataURL(file);
}
window.readPicture = readPicture;

function pictureField(id, label, value, hint, maxW, maxH, clearWhite) {
    return '<div class="form-group"><label>' + esc(label) + '</label>' +
        '<div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap;">' +
        '<div id="' + id + '-box" style="width:170px;height:70px;border:1px dashed var(--border-color);border-radius:8px;' +
            'display:flex;align-items:center;justify-content:center;background:#fff;overflow:hidden;">' +
            (value ? '<img src="' + value + '" style="max-width:100%;max-height:100%;">'
                   : '<span style="font-size:0.75rem;color:var(--text-secondary);">None</span>') + '</div>' +
        '<input type="hidden" id="' + id + '" value="' + esc(value || '') + '">' +
        '<label class="btn btn-sm btn-outline" style="margin:0;cursor:pointer;">Choose picture' +
            '<input type="file" accept="image/*" style="display:none;" onchange="pictureChosen(\'' + id + '\',this,' +
            maxW + ',' + maxH + ',' + (clearWhite ? 'true' : 'false') + ')"></label>' +
        '<button type="button" class="btn btn-sm btn-outline" onclick="pictureCleared(\'' + id + '\')">Remove</button>' +
        '</div>' + (hint ? '<p style="font-size:0.75rem;color:var(--text-secondary);margin-top:4px;">' + esc(hint) + '</p>' : '') +
        '</div>';
}

function pictureChosen(id, input, maxW, maxH, clearWhite) {
    readPicture(input.files && input.files[0], maxW, maxH, clearWhite, function (url) {
        document.getElementById(id).value = url;
        document.getElementById(id + '-box').innerHTML = '<img src="' + url + '" style="max-width:100%;max-height:100%;">';
    });
}
window.pictureChosen = pictureChosen;

function pictureCleared(id) {
    document.getElementById(id).value = '';
    document.getElementById(id + '-box').innerHTML = '<span style="font-size:0.75rem;color:var(--text-secondary);">None</span>';
}
window.pictureCleared = pictureCleared;

/* --- One editor for a letterhead or a gang -------------------------------- */

var LH = { kind: '', id: null, after: null };

function lhModal(title, body) {
    var modal = document.getElementById('lh-modal');
    if (!modal) {
        modal = document.createElement('div');
        modal.id = 'lh-modal';
        modal.className = 'modal-overlay';
        modal.style.cssText = 'display:none;z-index:10040;';
        modal.innerHTML = '<div class="modal" style="max-width:640px;width:96%;max-height:92vh;display:flex;flex-direction:column;">' +
            '<div class="modal-header"><h3 id="lh-title"></h3><button class="modal-close" onclick="lhClose()">&times;</button></div>' +
            '<div class="modal-body" id="lh-body" style="overflow:auto;"></div>' +
            '<div class="modal-footer"><button class="btn btn-outline" onclick="lhClose()">Cancel</button>' +
            '<button class="btn btn-primary" id="lh-save" onclick="lhSave()">Save</button></div></div>';
        document.body.appendChild(modal);
    }
    document.getElementById('lh-title').textContent = title;
    document.getElementById('lh-body').innerHTML = body;
    modal.style.display = 'flex';
}

function lhClose() {
    var modal = document.getElementById('lh-modal');
    if (modal) modal.style.display = 'none';
}
window.lhClose = lhClose;

function lhInput(id, label, value, opts) {
    opts = opts || {};
    var input = opts.area
        ? '<textarea class="form-control" id="' + id + '" rows="3">' + esc(value || '') + '</textarea>'
        : '<input class="form-control" id="' + id + '" value="' + esc(value || '') + '"' +
          (opts.upper ? ' style="text-transform:uppercase;"' : '') + (opts.placeholder ? ' placeholder="' + esc(opts.placeholder) + '"' : '') + '>';
    return '<div class="form-group"' + (opts.full ? ' style="grid-column:1/-1;"' : '') + '><label>' + esc(label) + '</label>' + input +
        (opts.hint ? '<p style="font-size:0.75rem;color:var(--text-secondary);margin-top:4px;">' + esc(opts.hint) + '</p>' : '') + '</div>';
}

function lhVal(id) {
    var el = document.getElementById(id);
    return el ? el.value.trim() : '';
}

async function openUnitEditor(unitId, after) {
    var res = await fetch('/api/wo/business-units', { credentials: 'include' });
    var units = (await res.json()).business_units || [];
    var u = units.filter(function (x) { return x.id === unitId; })[0] || {};
    LH = { kind: 'unit', id: u.id || null, after: after };
    lhModal(u.id ? 'Letterhead - ' + u.name : 'New business unit',
        '<p style="font-size:0.8rem;color:var(--text-secondary);margin-bottom:12px;">Printed at the top of every work order, bill and ' +
        'purchase order this company issues.</p>' +
        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:0 14px;">' +
        lhInput('lh-name', 'Company name *', u.name, { full: true }) +
        lhInput('lh-code', 'Short code', u.code, { upper: true, placeholder: 'YPPL' }) +
        '<div></div>' +
        lhInput('lh-gstin', 'GSTIN', u.gstin, { upper: true, placeholder: '36AABCY1234H1ZX', hint: 'The state and the PAN are read from it.' }) +
        lhInput('lh-pan', 'PAN', u.pan, { upper: true, placeholder: 'AABCY1234H' }) +
        lhInput('lh-address', 'Address', u.address, { area: true, full: true }) +
        '<div style="grid-column:1/-1;">' + pictureField('lh-logo', 'Logo', u.logo_url, 'PNG or JPEG. Printed beside the company name.', 600, 240, false) + '</div>' +
        '</div>');
}
window.openUnitEditor = openUnitEditor;

async function openContractorEditor(conId, after) {
    var res = await fetch('/api/wo/contractors', { credentials: 'include' });
    var list = (await res.json()).contractors || [];
    var c = list.filter(function (x) { return x.id === conId; })[0];
    if (!c) { showToast('That contractor was not found', 'error'); return; }
    LH = { kind: 'contractor', id: c.id, after: after };
    lhModal('Contractor - ' + c.company_name,
        '<p style="font-size:0.8rem;color:var(--text-secondary);margin-bottom:12px;">Printed on the work order and the gang\'s bills. ' +
        'The PAN and bank are needed before a bill can be paid.</p>' +
        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:0 14px;">' +
        lhInput('lh-cname', 'Company name *', c.company_name, { full: true }) +
        lhInput('lh-contact', 'Contact person', c.contact_person) +
        lhInput('lh-phone', 'Mobile', c.phone_number) +
        lhInput('lh-email', 'Email', c.email) +
        '<div></div>' +
        lhInput('lh-cgstin', 'GSTIN', c.gst_number, { upper: true, placeholder: '36AAAPR1234C1Z5' }) +
        lhInput('lh-cpan', 'PAN', c.pan, { upper: true, placeholder: 'AAAPR1234C', hint: 'Filled from the GSTIN if left blank.' }) +
        lhInput('lh-caddress', 'Address', c.address, { area: true, full: true }) +
        lhInput('lh-bank', 'Bank', c.bank_name) +
        lhInput('lh-ifsc', 'IFSC', c.bank_ifsc, { upper: true }) +
        lhInput('lh-account', 'Account number', c.bank_account, { full: true }) +
        '</div>');
}
window.openContractorEditor = openContractorEditor;

async function lhSave() {
    var url, method = 'PUT', body;
    if (LH.kind === 'unit') {
        body = { name: lhVal('lh-name'), code: lhVal('lh-code'), gstin: lhVal('lh-gstin'), pan: lhVal('lh-pan'),
                 address: lhVal('lh-address'), logo_url: lhVal('lh-logo') };
        if (!body.name) { showToast('The company needs a name', 'error'); return; }
        url = '/api/wo/business-units' + (LH.id ? '/' + LH.id : '');
        if (!LH.id) method = 'POST';
    } else {
        body = { company_name: lhVal('lh-cname'), contact_person: lhVal('lh-contact'), phone_number: lhVal('lh-phone'),
                 email: lhVal('lh-email'), gst_number: lhVal('lh-cgstin'), pan: lhVal('lh-cpan'),
                 address: lhVal('lh-caddress'), bank_name: lhVal('lh-bank'), bank_ifsc: lhVal('lh-ifsc'),
                 bank_account: lhVal('lh-account') };
        if (!body.company_name) { showToast('The contractor needs a name', 'error'); return; }
        url = '/api/wo/contractors/' + LH.id;
    }
    var btn = document.getElementById('lh-save');
    btn.disabled = true;
    try {
        var res = await fetch(url, { method: method, credentials: 'include',
            headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
        var out = await res.json();
        if (!res.ok) { showToast(out.detail || 'Not saved', 'error'); return; }
        showToast(out.message || 'Saved', 'success');
        lhClose();
        if (typeof LH.after === 'function') LH.after(out);
    } finally {
        btn.disabled = false;
    }
}
window.lhSave = lhSave;

/* --- Settings: the letterheads -------------------------------------------- */

async function loadLetterheads() {
    var host = document.getElementById('letterhead-list');
    if (!host) return;
    var res = await fetch('/api/wo/business-units', { credentials: 'include' });
    if (!res.ok) return;
    var units = (await res.json()).business_units || [];
    host.innerHTML = units.map(function (u) {
        var missing = [!u.gstin && 'GSTIN', !u.pan && 'PAN', !u.address && 'address', !u.logo_url && 'logo'].filter(Boolean);
        return '<div style="display:flex;gap:14px;align-items:center;padding:12px 0;border-bottom:1px solid var(--border-color);">' +
            '<div style="width:110px;height:48px;display:flex;align-items:center;justify-content:center;background:#fff;border:1px solid var(--border-color);border-radius:6px;overflow:hidden;flex-shrink:0;">' +
                (u.logo_url ? '<img src="' + u.logo_url + '" style="max-width:100%;max-height:100%;">'
                            : '<span style="font-size:0.7rem;color:var(--text-secondary);">No logo</span>') + '</div>' +
            '<div style="flex:1;min-width:0;"><div style="font-weight:700;">' + esc(u.name) + (u.code ? ' <span style="color:var(--text-secondary);font-weight:400;">(' + esc(u.code) + ')</span>' : '') + '</div>' +
                '<div style="font-size:0.78rem;color:var(--text-secondary);">' +
                [u.gstin && 'GSTIN ' + esc(u.gstin), u.pan && 'PAN ' + esc(u.pan)].filter(Boolean).join(' &middot; ') + '</div>' +
                (u.address ? '<div style="font-size:0.78rem;color:var(--text-secondary);white-space:pre-line;">' + esc(u.address) + '</div>' : '') +
                (missing.length ? '<div style="font-size:0.75rem;color:var(--warning-color);">No ' + esc(missing.join(', ')) + ' on file</div>' : '') +
            '</div>' +
            '<button class="btn btn-sm btn-outline" onclick="openUnitEditor(' + u.id + ', loadLetterheads)">Edit</button></div>';
    }).join('') +
    '<button class="btn btn-sm btn-outline" style="margin-top:12px;" onclick="openUnitEditor(null, loadLetterheads)">+ Another company</button>';
}
window.loadLetterheads = loadLetterheads;

/* --- Settings: the company's general conditions ---------------------------- */

var TERMS = { list: [], custom: false };

async function loadTermsLibrary() {
    var host = document.getElementById('terms-library');
    if (!host) return;
    var res = await fetch('/api/wo/terms/library', { credentials: 'include' });
    if (!res.ok) return;
    var data = await res.json();
    TERMS.list = (data.library || []).map(function (t) { return { clause_category: t.clause_category || '', clause_text: t.clause_text || '' }; });
    TERMS.custom = !!data.custom;
    drawTerms();
}
window.loadTermsLibrary = loadTermsLibrary;

function drawTerms() {
    var host = document.getElementById('terms-library');
    host.innerHTML = '<p style="font-size:0.8rem;color:var(--text-secondary);margin-bottom:10px;">' +
        (TERMS.custom ? 'Your own conditions.' : 'The standard conditions - change any of them and save to make them yours.') +
        ' They print as the General Contract Conditions on every work order that has none of its own, and are offered ' +
        'when an order\'s terms are written.</p>' +
        TERMS.list.map(function (t, i) {
            // Number, then the heading over its text, then the buttons: the text
            // keeps the width on a phone instead of being squeezed beside a heading.
            return '<div style="display:grid;grid-template-columns:24px minmax(0,1fr) auto;gap:8px;align-items:start;margin-bottom:10px;">' +
                '<span style="padding-top:8px;font-weight:700;color:var(--text-secondary);">' + (i + 1) + '.</span>' +
                '<div><input class="form-control" style="margin-bottom:4px;font-size:0.8rem;" value="' + esc(t.clause_category) +
                    '" placeholder="Heading (for filing - not printed)" oninput="TERMS.list[' + i + '].clause_category=this.value">' +
                '<textarea class="form-control" rows="3" oninput="TERMS.list[' + i + '].clause_text=this.value">' + esc(t.clause_text) + '</textarea></div>' +
                '<div style="display:flex;flex-direction:column;gap:4px;">' +
                    '<button class="btn btn-sm btn-outline" title="Move up" onclick="termMove(' + i + ',-1)">&uarr;</button>' +
                    '<button class="btn btn-sm btn-outline" title="Remove" onclick="termRemove(' + i + ')">&times;</button></div></div>';
        }).join('') +
        '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:6px;">' +
        '<button class="btn btn-sm btn-outline" onclick="termAdd()">+ Condition</button>' +
        '<button class="btn btn-primary" onclick="saveTermsLibrary()">Save conditions</button>' +
        (TERMS.custom ? '<button class="btn btn-sm btn-outline" onclick="resetTermsLibrary()">Go back to the standard</button>' : '') +
        '</div>';
}

function termAdd() { TERMS.list.push({ clause_category: '', clause_text: '' }); drawTerms(); }
function termRemove(i) { TERMS.list.splice(i, 1); drawTerms(); }
function termMove(i, by) {
    var j = i + by;
    if (j < 0 || j >= TERMS.list.length) return;
    var t = TERMS.list[i]; TERMS.list[i] = TERMS.list[j]; TERMS.list[j] = t;
    drawTerms();
}
window.termAdd = termAdd; window.termRemove = termRemove; window.termMove = termMove;

async function saveTermsLibrary(reset) {
    var res = await fetch('/api/wo/terms/library', { method: 'PUT', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ terms: reset ? [] : TERMS.list.filter(function (t) { return t.clause_text.trim(); }) }) });
    var out = await res.json();
    showToast(res.ok ? out.message : (out.detail || 'Not saved'), res.ok ? 'success' : 'error');
    if (res.ok) loadTermsLibrary();
}
window.saveTermsLibrary = saveTermsLibrary;
function resetTermsLibrary() {
    if (confirm('Go back to the standard conditions? Your own will be replaced.')) saveTermsLibrary(true);
}
window.resetTermsLibrary = resetTermsLibrary;

/* --- A supplier's particulars, from the purchase order ------------------- */

async function openSupplierEditor(name, after) {
    var res = await fetch('/api/suppliers', { credentials: 'include' });
    var data = res.ok ? await res.json() : {};
    var list = data.suppliers || data || [];
    var key = String(name || '').trim().toLowerCase();
    var s = (Array.isArray(list) ? list : []).filter(function (x) {
        return String(x.name || '').trim().toLowerCase() === key;
    })[0] || { name: name || '', payment_days: 30, is_active: true };
    LH = { kind: 'supplier', id: s.id || null, after: after, keep: s };
    lhModal((s.id ? 'Supplier - ' : 'New supplier - ') + (s.name || ''),
        '<p style="font-size:0.8rem;color:var(--text-secondary);margin-bottom:12px;">Printed on the purchase order: the ' +
        'supplier\'s PAN, GSTIN, address and contact.' + (s.id ? '' : ' Not on the supplier list yet - saving adds it.') + '</p>' +
        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:0 14px;">' +
        lhInput('lh-sname', 'Supplier name *', s.name, { full: true }) +
        lhInput('lh-scontact', 'Contact person', s.contact_person) +
        lhInput('lh-sphone', 'Mobile', s.phone) +
        lhInput('lh-semail', 'Email', s.email, { full: true }) +
        lhInput('lh-sgstin', 'GSTIN', s.gstin, { upper: true }) +
        lhInput('lh-span', 'PAN', s.pan, { upper: true, hint: 'Filled from the GSTIN if left blank.' }) +
        lhInput('lh-saddress', 'Address', s.address, { area: true, full: true }) +
        lhInput('lh-sbank', 'Bank', s.bank_name) +
        lhInput('lh-sifsc', 'IFSC', s.bank_ifsc, { upper: true }) +
        lhInput('lh-saccount', 'Account number', s.bank_account, { full: true }) +
        '</div>');
}
window.openSupplierEditor = openSupplierEditor;

var _lhSaveBase = lhSave;
lhSave = async function () {
    if (LH.kind !== 'supplier') return _lhSaveBase();
    var k = LH.keep || {};
    var body = { name: lhVal('lh-sname'), contact_person: lhVal('lh-scontact'), phone: lhVal('lh-sphone'),
                 email: lhVal('lh-semail'), gstin: lhVal('lh-sgstin'), pan: lhVal('lh-span'),
                 address: lhVal('lh-saddress'), bank_name: lhVal('lh-sbank'), bank_ifsc: lhVal('lh-sifsc'),
                 bank_account: lhVal('lh-saccount'), payment_days: k.payment_days || 30,
                 supplies: k.supplies || '', is_active: k.is_active !== false };
    if (!body.name) { showToast('The supplier needs a name', 'error'); return; }
    var res = await fetch('/api/suppliers' + (LH.id ? '/' + LH.id : ''), {
        method: LH.id ? 'PUT' : 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Not saved', 'error'); return; }
    showToast(out.message || 'Saved', 'success');
    lhClose();
    if (typeof LH.after === 'function') LH.after(out);
};
window.lhSave = lhSave;
