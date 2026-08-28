/* ===========================================================================
   erp.js - item master, work orders and budget allocation.

   The contracting side of the ledger:

     Item master (RM/FG)  ->  Work order (what was sold, in FG codes)
                          ->  Budget/BOM (what it consumes, in RM codes)
                          ->  Approval, on the same chain as everything else

   Loaded after app.js; shared helpers (esc, showToast, formatCurrency,
   showView, statusPill, statCard) come from there and staff-portal.js.
   =========================================================================== */

var _items = [];
var _workOrders = [];

/* Uploads are multipart. No Content-Type header is set on purpose: the
   browser has to add it so it can include the multipart boundary. */
async function postSheet(url, fileInputId, extra) {
    var input = document.getElementById(fileInputId);
    if (!input || !input.files.length) { showToast('Choose a file first', 'error'); return null; }
    var fd = new FormData();
    fd.append('file', input.files[0]);
    Object.keys(extra || {}).forEach(function (k) { fd.append(k, extra[k]); });
    var res = await fetch(url, { method: 'POST', body: fd });
    var data = await res.json().catch(function () { return {}; });
    if (!res.ok) { showToast(data.detail || 'Upload failed', 'error'); return null; }
    return data;
}

/* Line numbers match what Excel shows, so a person can go straight to the
   offending row rather than counting. */
function sheetIssues(result) {
    var html = '';
    if (result.errors && result.errors.length) {
        html += '<div style="border:1px solid var(--danger-color);background:rgba(239,68,68,0.06);' +
            'border-radius:8px;padding:12px;margin-bottom:10px;">' +
            '<strong style="color:var(--danger-color);font-size:0.85rem;">' +
            result.errors.length + ' error(s) — nothing was saved</strong><ul style="margin:6px 0 0 16px;">' +
            result.errors.map(function (e) {
                return '<li style="font-size:0.78rem;color:var(--text-secondary);">Line ' +
                    e.line + ' · ' + esc(e.field) + ' · ' + esc(e.message) + '</li>';
            }).join('') + '</ul></div>';
    }
    if (result.warnings && result.warnings.length) {
        html += '<div style="border:1px solid var(--warning-color);background:rgba(245,158,11,0.06);' +
            'border-radius:8px;padding:12px;margin-bottom:10px;">' +
            '<strong style="color:var(--warning-color);font-size:0.85rem;">' +
            result.warnings.length + ' reused</strong><ul style="margin:6px 0 0 16px;">' +
            result.warnings.map(function (w) {
                return '<li style="font-size:0.78rem;color:var(--text-secondary);">Line ' +
                    w.line + ' · ' + esc(w.message) + '</li>';
            }).join('') + '</ul></div>';
    }
    if (!html && result.ok) {
        html = '<div style="border:1px solid var(--success-color);background:rgba(16,185,129,0.06);' +
            'border-radius:8px;padding:12px;margin-bottom:10px;font-size:0.85rem;' +
            'color:var(--success-color);font-weight:600;">Validated — no duplicate codes, no missing fields.</div>';
    }
    return html;
}

/* --- Item master -------------------------------------------------------- */

function downloadItemTemplate(kind) {
    window.location = '/api/erp/items/template?kind=' + kind;
}
window.downloadItemTemplate = downloadItemTemplate;

/* ===========================================================================
   Reading a sheet somebody actually sent.

   The old pair of drop zones made you declare RM or FG up front and refused
   the file if the declaration disagreed with its contents - which is what the
   sheet already stated. This reads the file, says what it assumed, repairs
   what has one right answer, and lets the rest be corrected on screen rather
   than back in Excel.
   =========================================================================== */

var _analysis = null;

var ITEM_FIELDS = [
    { key: 'item_code', label: 'Code', width: '110px' },
    { key: 'item_name', label: 'Name', width: '220px' },
    { key: 'description', label: 'Description', width: '200px' },
    { key: 'item_type', label: 'Type', width: '110px', options: ['Purchased', 'Service'] },
    { key: 'units_of_measure', label: 'UOM', width: '100px',
      options: ['Meters', 'Nos', 'Kgs', 'Litres', 'Sets', 'Lot'] },
    { key: 'hsn_code', label: 'HSN', width: '90px' },
    { key: 'item_tax_type', label: 'Tax', width: '80px' }
];

async function analyseItemSheet() {
    var input = document.getElementById('item-file');
    if (!input.files.length) return;
    document.getElementById('item-file-name').textContent = input.files[0].name;
    var host = document.getElementById('item-analysis');
    host.innerHTML = '<p class="text-[13px] text-ink-soft">Reading the sheet…</p>';

    var fd = new FormData();
    fd.append('file', input.files[0]);
    fd.append('sheet', typeof chosenSheet === 'function' ? chosenSheet('item-sheet') : '');
    try {
        var res = await fetch('/api/erp/items/analyse', { method: 'POST', body: fd });
        var data = await res.json();
        if (!res.ok) {
            host.innerHTML = '<div class="border border-red-300 bg-red-50 rounded-lg p-3 text-[13px] text-red-800">' +
                esc(data.detail || 'That file could not be read') + '</div>';
            return;
        }
        _analysis = data;
        renderAnalysis();
    } catch (e) {
        host.innerHTML = '<div class="border border-red-300 bg-red-50 rounded-lg p-3 text-[13px] text-red-800">Could not read that file.</div>';
    }
}
window.analyseItemSheet = analyseItemSheet;

function renderAnalysis() {
    var a = _analysis, s = a.summary;
    var kinds = Object.keys(a.detected).map(function (k) {
        return a.detected[k] + ' ' + k;
    }).join(' · ') || 'none';

    var html = '';

    /* What the sheet was taken to be. Stated plainly, because every row below
       was interpreted through it. */
    html += '<div class="flex flex-wrap items-center gap-2 mb-3">' +
        chip(kinds + ' detected', 'brand') +
        chip(s.total + ' rows', 'slate') +
        (s.repaired ? chip(s.repaired + ' repaired', 'amber') : '') +
        (s.blocked ? chip(s.blocked + ' need you', 'red') : chip('all ready', 'green')) +
        '</div>';

    /* Which column was read as what. The one assumption most likely to be
       wrong on an unfamiliar sheet, so it is shown, not hidden. */
    html += '<details class="mb-3 border border-slate-200 rounded-lg"><summary class="cursor-pointer select-none px-3 py-2 text-[13px] font-medium text-ink">' +
        'Columns matched (' + Object.keys(a.mapping).length + ')' +
        (a.unmapped_headers.length ? ' · ' + a.unmapped_headers.length + ' ignored' : '') +
        '</summary><div class="px-3 pb-3 flex flex-wrap gap-1.5">' +
        Object.keys(a.mapping).map(function (h) {
            return '<span class="text-xxs bg-slate-100 rounded px-2 py-1"><span class="font-mono">' +
                esc(h) + '</span> <span class="text-ink-faint">→</span> ' + esc(a.mapping[h]) + '</span>';
        }).join('') +
        a.unmapped_headers.map(function (h) {
            return '<span class="text-xxs bg-slate-50 text-ink-faint line-through rounded px-2 py-1">' + esc(h) + '</span>';
        }).join('') + '</div></details>';

    if (a.repairs.length) html += repairLog(a.repairs);

    html += analysisGrid();

    html += '<div class="flex items-center gap-3 mt-4">' +
        '<button class="btn btn-primary" onclick="commitItemSheet()">' +
        (s.blocked ? 'Save the ' + s.ready + ' ready row(s)' : 'Save ' + s.ready + ' code(s)') + '</button>' +
        '<button class="btn" onclick="discardAnalysis()">Discard</button>' +
        (s.blocked ? '<span class="text-xxs text-red-700">' + s.blocked +
            ' row(s) still need a correction below</span>' : '') + '</div>';

    document.getElementById('item-analysis').innerHTML = html;
}

function chip(text, tone) {
    var map = {
        brand: 'bg-blue-50 text-blue-700 ring-blue-200',
        green: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
        amber: 'bg-amber-50 text-amber-700 ring-amber-200',
        red:   'bg-red-50 text-red-700 ring-red-200',
        slate: 'bg-slate-100 text-slate-600 ring-slate-200'
    };
    return '<span class="inline-flex items-center px-2.5 py-1 rounded-full text-xxs font-semibold ring-1 ring-inset ' +
        map[tone] + '">' + esc(text) + '</span>';
}

/* Every automatic change, itemised. A silent correction to a price list is
   indistinguishable from a bug. */
function repairLog(repairs) {
    return '<details class="mb-3 border border-amber-200 bg-amber-50/60 rounded-lg">' +
        '<summary class="cursor-pointer select-none px-3 py-2 text-[13px] font-medium text-amber-900">' +
        repairs.length + ' correction(s) applied automatically</summary>' +
        '<div class="px-3 pb-3 max-h-52 overflow-y-auto">' +
        repairs.map(function (r) {
            return '<div class="text-xxs text-amber-900 py-0.5">Line ' + r.line + ' · ' +
                esc(r.field) + ': <span class="line-through opacity-60">' + (esc(r.from) || '(blank)') +
                '</span> → <strong>' + esc(r.to) + '</strong> <span class="opacity-70">(' +
                esc(r.note) + ')</span></div>';
        }).join('') + '</div></details>';
}

/* The rows as read, editable in place. A sheet with two bad cells should cost
   two keystrokes, not a round trip through Excel. */
function analysisGrid() {
    var rows = _analysis.rows;
    var head = '<th class="px-2 py-2 text-left font-semibold text-ink-soft">Line</th>' +
        '<th class="px-2 py-2 text-left font-semibold text-ink-soft">Kind</th>' +
        ITEM_FIELDS.map(function (f) {
            return '<th class="px-2 py-2 text-left font-semibold text-ink-soft" style="min-width:' + f.width + '">' +
                esc(f.label) + '</th>';
        }).join('');

    var body = rows.map(function (row, i) {
        var problems = row._problems || [];
        var bad = {};
        problems.forEach(function (p) { bad[p.field] = p; });
        var reused = (_analysis.reused || []).indexOf(row._line) >= 0;

        var cells = ITEM_FIELDS.map(function (f) {
            var p = bad[f.key];
            var cls = 'w-full bg-transparent px-1.5 py-1 rounded text-[13px] border ' +
                (p ? 'border-red-400 bg-red-50' : 'border-transparent hover:border-slate-300 focus:border-brand') +
                ' focus:outline-none';
            var control;
            if (f.options) {
                control = '<select class="' + cls + '" onchange="editCell(' + i + ',\'' + f.key + '\',this.value)">' +
                    f.options.map(function (o) {
                        return '<option' + (o === row[f.key] ? ' selected' : '') + '>' + esc(o) + '</option>';
                    }).join('') + '</select>';
            } else {
                control = '<input class="' + cls + '" value="' + esc(row[f.key] || '') +
                    '" oninput="editCell(' + i + ',\'' + f.key + '\',this.value)">';
            }
            return '<td class="px-1 py-1 align-top">' + control +
                (p ? '<div class="text-xxs text-red-700 mt-0.5 leading-tight">' + esc(p.message) +
                     (p.fix ? ' <button class="underline font-semibold" onclick="applyFix(' + i +
                              ',\'' + f.key + '\',\'' + esc(p.fix) + '\')">use ' + esc(p.fix) + '</button>' : '') +
                     '</div>' : '') + '</td>';
        }).join('');

        return '<tr class="' + (problems.length ? 'bg-red-50/40' : '') + ' border-b border-slate-100">' +
            '<td class="px-2 py-1 text-xxs text-ink-faint align-top pt-3">' + row._line + '</td>' +
            '<td class="px-2 py-1 align-top pt-2">' +
                '<select class="text-xxs border border-slate-300 rounded px-1 py-0.5" ' +
                'onchange="editCell(' + i + ',\'_kind\',this.value)">' +
                ['', 'RM', 'FG'].map(function (k) {
                    return '<option value="' + k + '"' + (k === row._kind ? ' selected' : '') + '>' +
                        (k || '?') + '</option>';
                }).join('') + '</select>' +
                (reused ? '<div class="text-xxs text-ink-faint mt-0.5">reused</div>' : '') +
            '</td>' + cells + '</tr>';
    }).join('');

    return '<div class="border border-slate-200 rounded-lg overflow-x-auto max-h-[26rem] overflow-y-auto">' +
        '<table class="min-w-full text-[13px]"><thead class="bg-slate-50 sticky top-0"><tr>' +
        head + '</tr></thead><tbody>' + body + '</tbody></table></div>';
}

function editCell(index, field, value) {
    _analysis.rows[index][field] = value;
}
window.editCell = editCell;

function applyFix(index, field, value) {
    _analysis.rows[index][field] = value;
    // Clear the problem it solved, then redraw so the counts follow.
    _analysis.rows[index]._problems =
        (_analysis.rows[index]._problems || []).filter(function (p) { return p.field !== field; });
    recount();
    renderAnalysis();
}
window.applyFix = applyFix;

function recount() {
    var blocked = _analysis.rows.filter(function (r) {
        return (r._problems || []).length;
    }).length;
    _analysis.summary.blocked = blocked;
    _analysis.summary.ready = _analysis.rows.length - blocked;
}

function discardAnalysis() {
    _analysis = null;
    document.getElementById('item-file').value = '';
    document.getElementById('item-file-name').textContent = '';
    document.getElementById('item-analysis').innerHTML = '';
}
window.discardAnalysis = discardAnalysis;

async function commitItemSheet() {
    if (!_analysis) return;
    // Only send what is clean; a partly-bad sheet still gets its good rows in.
    var rows = _analysis.rows.filter(function (r) { return !(r._problems || []).length; });
    if (!rows.length) { showToast('Every row still needs a correction', 'error'); return; }
    try {
        var res = await fetch('/api/erp/items/commit', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ rows: rows })
        });
        var data = await res.json();
        if (!data.ok) {
            (data.errors || []).forEach(function (e) {
                var row = _analysis.rows.filter(function (r) { return r._line === e.line; })[0];
                if (row) row._problems = (row._problems || []).concat([e]);
            });
            recount(); renderAnalysis();
            showToast(data.message || 'Some rows were refused', 'error');
            return;
        }
        showToast(data.message, 'success');
        discardAnalysis();
        loadItems();
    } catch (e) { showToast('Could not save those rows', 'error'); }
}
window.commitItemSheet = commitItemSheet;

async function validateItemSheet(kind) {
    var r = await postSheet('/api/erp/items/validate', kind.toLowerCase() + '-file', { kind: kind });
    if (!r) return;
    document.getElementById(kind.toLowerCase() + '-result').innerHTML = sheetIssues(r) +
        '<p style="font-size:0.78rem;color:var(--text-secondary);">' +
        r.total_rows + ' row(s) read · ' + r.importable + ' ready</p>';
    showToast(r.ok ? 'Validation passed' : r.errors.length + ' error(s)', r.ok ? 'success' : 'error');
}
window.validateItemSheet = validateItemSheet;

async function uploadItemSheet(kind) {
    var r = await postSheet('/api/erp/items/upload', kind.toLowerCase() + '-file', { kind: kind });
    if (!r) return;
    document.getElementById(kind.toLowerCase() + '-result').innerHTML =
        sheetIssues(r) + '<p style="font-size:0.85rem;font-weight:600;">' + esc(r.message) + '</p>';
    showToast(r.message, r.ok ? 'success' : 'error');
    if (r.created) loadItems();
}
window.uploadItemSheet = uploadItemSheet;

async function loadItems() {
    var body = document.getElementById('items-body');
    if (!body) return;
    var q = (document.getElementById('item-search') || {}).value || '';

    // Only the fetch is guarded. It used to wrap the rendering as well, so a
    // missing element on the page - a counter that had been taken out of the
    // markup - threw, was caught here, and reported itself as "could not load
    // items" under a panel that was plainly showing the counts it had just
    // loaded. The failure to say what actually broke cost more than the break.
    var data;
    try {
        data = await (await fetch('/api/erp/items?q=' + encodeURIComponent(q))).json();
    } catch (e) {
        body.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:30px;color:var(--text-secondary);">Could not load items.</td></tr>';
        return;
    }

    _items = data.items || [];
    var counts = data.counts || { RM: 0, FG: 0 };
    var stats = document.getElementById('items-stats');
    if (stats) {
        stats.innerHTML = statCard('Raw material codes', counts.RM) +
            statCard('Finished goods codes', counts.FG) +
            statCard('Total items', counts.RM + counts.FG);
    }
    var counter = document.getElementById('item-count');
    if (counter) counter.textContent = _items.length + ' items';
    body.innerHTML = _items.length ? _items.map(function (i) {
        return '<tr><td style="font-family:monospace;font-weight:600;">' + esc(i.item_code) + '</td>' +
            '<td>' + esc(i.item_name) + '</td>' +
            '<td>' + statusPill(i.kind, i.kind === 'FG' ? 'good' : 'calm') + '</td>' +
            '<td>' + esc(i.item_type) + '</td><td>' + esc(i.units_of_measure) + '</td>' +
            '<td>' + esc(i.hsn_code) + '</td><td>' + esc(i.item_tax_type) + '</td></tr>';
    }).join('') : '<tr><td colspan="7" style="text-align:center;padding:30px;color:var(--text-secondary);">' +
        'No codes yet. Upload a sheet above — a work order cannot reference a code that is not here.</td></tr>';
}
window.loadItems = loadItems;

/* --- Work orders -------------------------------------------------------- */

function workOrderTone(w) {
    if (w.approval_status === 'approved') return 'good';
    if (w.approval_status === 'rejected') return 'bad';
    if (w.approval_status === 'pending') return 'wait';
    return 'calm';
}

async function loadWorkOrders() {
    var body = document.getElementById('wo-body');
    if (!body) return;
    try {
        var data = await (await fetch('/api/erp/work-orders')).json();
        _workOrders = data.work_orders || [];
        var stats = document.getElementById('wo-stats');
        if (stats) {
            stats.innerHTML = statCard('Work orders', data.summary.count) +
                statCard('Awaiting approval', data.summary.awaiting_approval) +
                statCard('Order value', formatCurrency(data.summary.total_value)) +
                statCard('Expected margin', formatCurrency(data.summary.total_margin));
        }
    } catch (e) {
        body.innerHTML = '<tr><td colspan="8" style="text-align:center;padding:30px;color:var(--text-secondary);">Could not load work orders.</td></tr>';
        return;
    }
    body.innerHTML = _workOrders.length ? _workOrders.map(function (w) {
        /* The action offered is whatever the order needs next: budget it,
           then send it for approval. Nothing else is worth a button. */
        var action = !w.budgeted
            ? '<button class="btn btn-sm btn-primary" onclick="startBomBuilder(' + w.id + ')">Allocate budget</button>'
            : (w.approval_status === 'none' || w.approval_status === 'rejected'
                ? '<button class="btn btn-sm btn-primary" onclick="submitWorkOrder(' + w.id + ')">Send for approval</button>'
                : '<button class="btn btn-sm" onclick="startBomBuilder(' + w.id + ')">Budget</button>');
        action += ' <a class="btn btn-sm btn-outline" href="/api/erp/work-orders/' +
            w.id + '/export.xlsx" title="Download this order">Excel</a>';
        return '<tr><td style="font-family:monospace;font-weight:600;">' + esc(w.number) + '</td>' +
            '<td>' + esc(w.job_name) +
                '<div style="font-size:0.75rem;color:var(--text-secondary);">' + esc(w.customer_name) + '</div></td>' +
            '<td>' + w.line_count + '</td>' +
            '<td class="text-right">' + formatCurrency(w.total_value) + '</td>' +
            '<td class="text-right">' + (w.budgeted ? formatCurrency(w.budget_cost)
                : '<span style="color:var(--text-muted);">not budgeted</span>') + '</td>' +
            '<td class="text-right" style="font-weight:600;color:' +
                (w.margin < 0 ? 'var(--danger-color)' : 'var(--success-color)') + ';">' +
                (w.budgeted ? formatCurrency(w.margin) +
                    '<div style="font-size:0.72rem;font-weight:400;color:var(--text-secondary);">' +
                    w.margin_percent + '%</div>' : '—') + '</td>' +
            '<td>' + statusPill(w.status, workOrderTone(w)) +
                (w.rejection_reason ? '<div style="font-size:0.72rem;color:var(--text-secondary);">' +
                    esc(w.rejection_reason) + '</div>' : '') + '</td>' +
            '<td class="text-right">' + action + '</td></tr>';
    }).join('') : '<tr><td colspan="8" style="text-align:center;padding:30px;color:var(--text-secondary);">' +
        'No work orders yet.</td></tr>';
}
window.loadWorkOrders = loadWorkOrders;

async function showWorkOrderModal() {
    var modal = document.getElementById('wo-modal');
    if (!modal) return;
    document.getElementById('wo-file').value = '';
    document.getElementById('wo-modal-result').innerHTML = '';
    var select = document.getElementById('wo-job');
    var jobs = await jobOptions();
    select.innerHTML = jobs.length
        ? jobs.map(function (j) {
            return '<option value="' + j.id + '">' + esc(j.number + ' — ' + j.name) + '</option>';
          }).join('')
        : '<option value="">Create a job first</option>';
    modal.style.display = 'flex';
}
window.showWorkOrderModal = showWorkOrderModal;

function closeWorkOrderModal() {
    var m = document.getElementById('wo-modal');
    if (m) m.style.display = 'none';
}
window.closeWorkOrderModal = closeWorkOrderModal;

async function validateWorkOrderSheet() {
    var r = await postSheet('/api/erp/work-orders/validate', 'wo-file',
                            { sheet: chosenSheet('wo-sheet') });
    if (!r) return;
    document.getElementById('wo-modal-result').innerHTML = sheetIssues(r) +
        (r.ok ? '<p style="font-size:0.85rem;">Order value <strong>' +
            formatCurrency(r.total_value) + '</strong> across ' + r.lines.length + ' line(s)</p>' : '');
    showToast(r.ok ? 'Validated — ' + formatCurrency(r.total_value) : r.errors.length + ' error(s)',
              r.ok ? 'success' : 'error');
}
window.validateWorkOrderSheet = validateWorkOrderSheet;

async function uploadWorkOrderSheet() {
    var jobId = parseInt(document.getElementById('wo-job').value);
    if (!jobId) { showToast('Create a job first', 'error'); return; }
    var r = await postSheet('/api/erp/work-orders', 'wo-file',
                            { job_id: jobId, sheet: chosenSheet('wo-sheet') });
    if (!r) return;
    document.getElementById('wo-modal-result').innerHTML = sheetIssues(r);
    showToast(r.message, r.ok ? 'success' : 'error');
    if (r.work_order) { closeWorkOrderModal(); loadWorkOrders(); }
}
window.uploadWorkOrderSheet = uploadWorkOrderSheet;

async function submitWorkOrder(id) {
    try {
        var res = await fetch('/api/erp/work-orders/' + id + '/submit', { method: 'POST' });
        var data = await res.json();
        if (!res.ok) { showToast(data.detail || 'Could not send that', 'error'); return; }
        showToast(data.message || 'Sent for approval', 'success');
        loadWorkOrders();
    } catch (e) { showToast('Could not send that', 'error'); }
}
window.submitWorkOrder = submitWorkOrder;

/* --- Budget allocation --------------------------------------------------- */

function showBomModal(woId) {
    var wo = _workOrders.filter(function (w) { return w.id === woId; })[0];
    document.getElementById('bom-wo-id').value = woId;
    document.getElementById('bom-file').value = '';
    document.getElementById('bom-result').innerHTML = '';
    document.getElementById('bom-modal-title').textContent =
        'Allocate budget — ' + (wo ? wo.number : '');
    document.getElementById('bom-context').textContent = wo
        ? wo.job_name + ' · order value ' + formatCurrency(wo.total_value)
        : '';
    document.getElementById('bom-modal').style.display = 'flex';
}
window.showBomModal = showBomModal;

function closeBomModal() {
    var m = document.getElementById('bom-modal');
    if (m) m.style.display = 'none';
}
window.closeBomModal = closeBomModal;

async function uploadBomSheet() {
    var id = parseInt(document.getElementById('bom-wo-id').value);
    var r = await postSheet('/api/erp/bom', 'bom-file',
                            { work_order_id: id, sheet: chosenSheet('bom-sheet') });
    if (!r) return;
    document.getElementById('bom-result').innerHTML = sheetIssues(r) +
        (r.ok ? '<p style="font-size:0.85rem;">Budgeted cost <strong>' +
            formatCurrency(r.total_cost) + '</strong></p>' : '');
    showToast(r.message, r.ok ? 'success' : 'error');
    if (r.created) { closeBomModal(); loadWorkOrders(); }
}
window.uploadBomSheet = uploadBomSheet;
