/* ===========================================================================
   erp-preview.js - reviewing a sheet that came from outside.

   A customer's work order or an estimator's budget carries prices. Letting
   one straight into the books is a price nobody checked, so it lands in the
   same grid on-screen entry uses: read, repaired, shown, corrected, and then
   committed through the very same validated endpoint a typed one goes to.

   Loaded after erp-build.js, whose cellCls and helpers it shares.
   =========================================================================== */

var _woPreview = null;
var _bomPreview = null;

function pill(text, tone) {
    var map = {
        slate: 'bg-slate-100 text-slate-600 ring-slate-200',
        red: 'bg-red-50 text-red-700 ring-red-200',
        green: 'bg-emerald-50 text-emerald-700 ring-emerald-200'
    };
    return '<span class="inline-flex px-2.5 py-1 rounded-full text-xxs font-semibold ring-1 ring-inset ' +
        map[tone] + '">' + esc(text) + '</span>';
}

function previewChips(s) {
    return '<div class="flex flex-wrap gap-2 mb-3">' +
        pill(s.total + ' rows', 'slate') +
        (s.blocked ? pill(s.blocked + ' need you', 'red') : pill('all ready', 'green')) +
        '</div>';
}

/* The column assumption is the one most likely to be wrong on a sheet from
   somebody else, so it is shown rather than hidden. */
function mappingNote(a) {
    var keys = Object.keys(a.mapping || {});
    if (!keys.length) return '';
    return '<details class="mb-3 border border-slate-200 rounded-lg">' +
        '<summary class="cursor-pointer select-none px-3 py-2 text-[13px] font-medium text-ink">' +
        'Columns matched (' + keys.length + ')' +
        ((a.unmapped_headers || []).length ? ' · ' + a.unmapped_headers.length + ' ignored' : '') +
        '</summary><div class="px-3 pb-3 flex flex-wrap gap-1.5">' +
        keys.map(function (h) {
            return '<span class="text-xxs bg-slate-100 rounded px-2 py-1"><span class="font-mono">' +
                esc(h) + '</span> → ' + esc(a.mapping[h]) + '</span>';
        }).join('') + '</div></details>';
}

function recountPreview(a) {
    var blocked = a.lines.filter(function (l) { return l._problems.length; }).length;
    a.summary.blocked = blocked;
    a.summary.ready = a.lines.length - blocked;
}

function problemNote(p, onFix) {
    if (!p) return '';
    return '<div class="text-xxs text-red-700 mt-0.5 leading-tight">' + esc(p.message) +
        (p.fix ? ' <button class="underline font-semibold" onclick="' + onFix +
                 '">use ' + esc(p.fix) + '</button>' : '') + '</div>';
}

/* --- Work order sheet ---------------------------------------------------- */

async function previewWorkOrderSheet() {
    var input = document.getElementById('wo-file');
    if (!input || !input.files.length) { showToast('Choose a file first', 'error'); return; }
    var fd = new FormData();
    fd.append('file', input.files[0]);
    fd.append('sheet', chosenSheet('wo-sheet'));
    try {
        var res = await fetch('/api/erp/work-orders/analyse', { method: 'POST', body: fd });
        var data = await res.json();
        if (!res.ok) { showToast(data.detail || 'Could not read that file', 'error'); return; }
        _woPreview = data;
        renderWoPreview();
    } catch (e) { showToast('Could not read that file', 'error'); }
}
window.previewWorkOrderSheet = previewWorkOrderSheet;

function renderWoPreview() {
    var a = _woPreview;
    var host = document.getElementById('wo-modal-result');
    if (!host) return;
    var value = 0;

    var rows = a.lines.map(function (l, i) {
        var bad = {};
        l._problems.forEach(function (p) { bad[p.field] = p; });
        if (!l._problems.length) value += (l.qty || 0) * (l.rate || 0);

        var codeSel = '<select class="' + cellCls + (bad.code ? ' border-red-400' : '') +
            '" onchange="editWoPreview(' + i + ',\'code\',this.value)"><option value="">&mdash;</option>' +
            a.choices.map(function (c) {
                return '<option value="' + esc(c.code) + '"' + (c.code === l.code ? ' selected' : '') +
                    '>' + esc(c.code + ' — ' + c.name) + '</option>';
            }).join('') + '</select>';

        return '<tr class="' + (l._problems.length ? 'bg-red-50/40 ' : '') + 'border-b border-slate-100">' +
            '<td class="px-2 py-2 text-xxs text-ink-faint align-top">' + l._line + '</td>' +
            '<td class="px-1 py-1 align-top" style="min-width:240px;">' + codeSel +
                problemNote(bad.code, 'editWoPreview(' + i + ',\'code\',\'' +
                    (bad.code && bad.code.fix ? esc(bad.code.fix) : '') + '\')') + '</td>' +
            '<td class="px-1 py-1 align-top" style="width:100px;"><input type="number" step="any" class="' +
                cellCls + ' text-right' + (bad.qty ? ' border-red-400' : '') + '" value="' + (l.qty || 0) +
                '" oninput="editWoPreview(' + i + ',\'qty\',this.value)">' + problemNote(bad.qty, '') + '</td>' +
            '<td class="px-1 py-1 align-top" style="width:110px;"><input type="number" step="any" class="' +
                cellCls + ' text-right' + (bad.rate ? ' border-red-400' : '') + '" value="' + (l.rate || 0) +
                '" oninput="editWoPreview(' + i + ',\'rate\',this.value)">' + problemNote(bad.rate, '') + '</td>' +
            '<td class="px-2 py-2 text-right font-medium align-top">' +
                formatCurrency((l.qty || 0) * (l.rate || 0)) + '</td></tr>';
    }).join('');

    host.innerHTML = previewChips(a.summary) + mappingNote(a) +
        '<div class="border border-slate-200 rounded-lg overflow-x-auto max-h-80 overflow-y-auto">' +
        '<table class="min-w-full text-[13px]"><thead class="bg-slate-50 sticky top-0"><tr>' +
        ['Line', 'Item', 'Qty', 'Rate', 'Amount'].map(function (h) {
            return '<th class="px-2 py-2 text-left font-semibold text-ink-soft">' + esc(h) + '</th>';
        }).join('') + '</tr></thead><tbody>' + rows + '</tbody></table></div>' +
        '<p class="text-right mt-2 text-[13px]">Order value <strong class="ml-2">' +
        formatCurrency(value) + '</strong></p>';
}

function editWoPreview(i, field, value) {
    if (value === '') return;
    var l = _woPreview.lines[i];
    l[field] = (field === 'qty' || field === 'rate') ? (parseFloat(value) || 0) : value;
    l._problems = l._problems.filter(function (p) { return p.field !== field; });
    if (field === 'qty' && l.qty <= 0) {
        l._problems.push({ field: 'qty', message: 'Quantity must be more than zero', fix: null });
    }
    recountPreview(_woPreview);
    renderWoPreview();
}
window.editWoPreview = editWoPreview;

/* Commits through /build, the same endpoint on-screen entry uses, so an
   imported order is validated exactly as a typed one is. */
async function commitWorkOrderPreview() {
    if (!_woPreview) { showToast('Preview the file first', 'error'); return; }
    var jobId = parseInt(document.getElementById('wo-job').value);
    if (!jobId) { showToast('Choose a job', 'error'); return; }
    var lines = _woPreview.lines
        .filter(function (l) { return !l._problems.length; })
        .map(function (l) {
            return { code: l.code, qty: l.qty, rate: l.rate, description: l.description };
        });
    if (!lines.length) { showToast('Every line still needs a correction', 'error'); return; }
    try {
        var res = await fetch('/api/erp/work-orders/build', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ job_id: jobId, lines: lines })
        });
        var data = await res.json();
        if (!res.ok) { showToast(data.detail || 'Could not create it', 'error'); return; }
        showToast(data.message, 'success');
        _woPreview = null;
        closeWorkOrderModal();
        loadWorkOrders();
    } catch (e) { showToast('Could not create it', 'error'); }
}
window.commitWorkOrderPreview = commitWorkOrderPreview;

/* --- Budget sheet -------------------------------------------------------- */

async function previewBomSheet() {
    var input = document.getElementById('bom-file');
    if (!input || !input.files.length) { showToast('Choose a file first', 'error'); return; }
    var fd = new FormData();
    fd.append('file', input.files[0]);
    fd.append('work_order_id', parseInt(document.getElementById('bom-wo-id').value));
    fd.append('sheet', chosenSheet('bom-sheet'));
    try {
        var res = await fetch('/api/erp/bom/analyse', { method: 'POST', body: fd });
        var data = await res.json();
        if (!res.ok) { showToast(data.detail || 'Could not read that file', 'error'); return; }
        _bomPreview = data;
        renderBomPreview();
    } catch (e) { showToast('Could not read that file', 'error'); }
}
window.previewBomSheet = previewBomSheet;

function renderBomPreview() {
    var a = _bomPreview;
    var host = document.getElementById('bom-result');
    if (!host) return;
    var cost = 0;

    var rows = a.lines.map(function (l, i) {
        var bad = {};
        l._problems.forEach(function (p) { bad[p.field] = p; });
        if (!l._problems.length) cost += (l.qty || 0) * (l.rate || 0);

        function chooser(field, list, current) {
            return '<select class="' + cellCls + (bad[field] ? ' border-red-400' : '') +
                '" onchange="editBomPreview(' + i + ',\'' + field + '\',this.value)">' +
                '<option value="">&mdash;</option>' + list.map(function (c) {
                    return '<option value="' + esc(c.code) + '"' + (c.code === current ? ' selected' : '') +
                        '>' + esc(c.code + ' — ' + c.name) + '</option>';
                }).join('') + '</select>' + problemNote(bad[field], '');
        }

        return '<tr class="' + (l._problems.length ? 'bg-red-50/40 ' : '') + 'border-b border-slate-100">' +
            '<td class="px-2 py-2 text-xxs text-ink-faint align-top">' + l._line + '</td>' +
            '<td class="px-1 py-1 align-top" style="min-width:190px;">' + chooser('fg_code', a.sold, l.fg_code) + '</td>' +
            '<td class="px-1 py-1 align-top" style="min-width:210px;">' + chooser('rm_code', a.materials, l.rm_code) + '</td>' +
            '<td class="px-1 py-1 align-top" style="width:100px;"><input type="number" step="any" class="' +
                cellCls + ' text-right' + (bad.qty ? ' border-red-400' : '') + '" value="' + (l.qty || 0) +
                '" oninput="editBomPreview(' + i + ',\'qty\',this.value)">' + problemNote(bad.qty, '') + '</td>' +
            '<td class="px-1 py-1 align-top" style="width:110px;"><input type="number" step="any" class="' +
                cellCls + ' text-right" value="' + (l.rate || 0) +
                '" oninput="editBomPreview(' + i + ',\'rate\',this.value)"></td>' +
            '<td class="px-2 py-2 text-right font-medium align-top">' +
                formatCurrency((l.qty || 0) * (l.rate || 0)) + '</td></tr>';
    }).join('');

    var margin = (a.summary.value || 0) - cost;
    host.innerHTML = previewChips(a.summary) + mappingNote(a) +
        '<div class="border border-slate-200 rounded-lg overflow-x-auto max-h-72 overflow-y-auto">' +
        '<table class="min-w-full text-[13px]"><thead class="bg-slate-50 sticky top-0"><tr>' +
        ['Line', 'Sold line (FG)', 'Consumes (RM)', 'Qty', 'Rate', 'Amount'].map(function (h) {
            return '<th class="px-2 py-2 text-left font-semibold text-ink-soft">' + esc(h) + '</th>';
        }).join('') + '</tr></thead><tbody>' + rows + '</tbody></table></div>' +
        '<div class="grid grid-cols-3 gap-2 mt-3 text-[13px]">' +
        '<div class="border border-slate-200 rounded-lg px-3 py-2"><div class="text-xxs text-ink-soft">Order value</div>' +
            '<div class="font-semibold">' + formatCurrency(a.summary.value) + '</div></div>' +
        '<div class="border border-slate-200 rounded-lg px-3 py-2"><div class="text-xxs text-ink-soft">Budgeted cost</div>' +
            '<div class="font-semibold">' + formatCurrency(cost) + '</div></div>' +
        '<div class="border border-slate-200 rounded-lg px-3 py-2"><div class="text-xxs text-ink-soft">Margin</div>' +
            '<div class="font-semibold ' + (margin < 0 ? 'text-red-600' : 'text-emerald-700') + '">' +
            formatCurrency(margin) + '</div></div></div>';
}

function editBomPreview(i, field, value) {
    if (value === '') return;
    var l = _bomPreview.lines[i];
    l[field] = (field === 'qty' || field === 'rate') ? (parseFloat(value) || 0) : value;
    l._problems = l._problems.filter(function (p) { return p.field !== field; });
    if (field === 'qty' && l.qty <= 0) {
        l._problems.push({ field: 'qty', message: 'Quantity must be more than zero', fix: null });
    }
    recountPreview(_bomPreview);
    renderBomPreview();
}
window.editBomPreview = editBomPreview;

async function commitBomPreview() {
    if (!_bomPreview) { showToast('Preview the file first', 'error'); return; }
    var lines = _bomPreview.lines
        .filter(function (l) { return !l._problems.length; })
        .map(function (l) {
            return { fg_code: l.fg_code, rm_code: l.rm_code, qty: l.qty, rate: l.rate };
        });
    if (!lines.length) { showToast('Every line still needs a correction', 'error'); return; }
    try {
        var res = await fetch('/api/erp/bom/build', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                work_order_id: parseInt(document.getElementById('bom-wo-id').value),
                lines: lines
            })
        });
        var data = await res.json();
        if (!res.ok) { showToast(data.detail || 'Could not save', 'error'); return; }
        showToast(data.message, 'success');
        _bomPreview = null;
        closeBomModal();
        loadWorkOrders();
    } catch (e) { showToast('Could not save', 'error'); }
}
window.commitBomPreview = commitBomPreview;
