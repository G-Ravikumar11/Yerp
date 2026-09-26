/* ===========================================================================
   sheetgrid.js - lines from an Excel sheet, fixed here before they are used.

   One grid for every kind of line the server can read (/api/sheets/<kind>):
   choose the file, see every row with what is wrong beside it, correct it,
   add a row, strike one out - then hand the rows to whatever asked for them.
   Nothing is saved by reading; the document's own save commits the lines.
   =========================================================================== */

var SG = { kind: '', rows: [], cols: [], problems: {}, opts: null, timer: null };

function openSheetGrid(opts) {
    SG.opts = opts; SG.kind = opts.kind; SG.rows = []; SG.cols = []; SG.problems = {};
    var box = document.getElementById('sheetgrid-modal');
    if (!box) {
        box = document.createElement('div');
        box.id = 'sheetgrid-modal';
        box.className = 'modal-overlay';
        box.style.zIndex = '10050';   // above whichever form opened it
        document.body.appendChild(box);
    }
    box.innerHTML = '<div class="modal" style="max-width:980px;width:96%;"><div class="modal-header"><h3>' + esc(opts.title || 'From Excel') +
        '</h3><button class="modal-close" onclick="closeModal(\'sheetgrid-modal\')">&times;</button></div>' +
        '<div class="modal-body">' +
            '<div id="sg-pick" style="display:flex;gap:8px;flex-wrap:wrap;align-items:end;">' +
                '<div class="form-group" style="flex:1;min-width:220px;margin:0;"><label>The sheet (.xlsx or .csv)</label>' +
                    '<input type="file" id="sg-file" accept=".xlsx,.xls,.csv" class="form-control"></div>' +
                '<div class="form-group" style="width:150px;margin:0;"><label>Tab (if not the first)</label>' +
                    '<input id="sg-sheet" class="form-control" placeholder="Sheet1"></div>' +
                '<button class="btn btn-primary" onclick="sheetGridRead()">Read it</button>' +
                '<a class="btn btn-outline" href="/api/sheets/' + encodeURIComponent(opts.kind) + '/template.xlsx">Template</a>' +
            '</div>' +
            '<div id="sg-note" style="font-size:0.82rem;color:var(--text-secondary);margin:10px 0 0;">' +
                esc(opts.intro || 'Nothing is saved by reading the sheet. Every row comes back here to be checked and corrected first.') + '</div>' +
            '<div id="sg-grid" style="margin-top:12px;"></div>' +
        '</div>' +
        '<div class="modal-footer"><button class="btn btn-outline" onclick="closeModal(\'sheetgrid-modal\')">Cancel</button>' +
            '<button class="btn btn-outline" id="sg-add" style="display:none;" onclick="sheetGridAdd()">+ Add a row</button>' +
            '<button class="btn btn-primary" id="sg-go" style="display:none;" onclick="sheetGridConfirm()">' +
                esc(opts.confirmLabel || 'Use these rows') + '</button></div></div>';
    box.style.display = 'flex';
}
window.openSheetGrid = openSheetGrid;

async function sheetGridRead() {
    var f = document.getElementById('sg-file');
    if (!f.files.length) { showToast('Choose the file first', 'error'); return; }
    var fd = new FormData();
    fd.append('file', f.files[0]);
    fd.append('sheet', document.getElementById('sg-sheet').value.trim());
    var res = await fetch('/api/sheets/' + encodeURIComponent(SG.kind) + '/read', { method: 'POST', credentials: 'include', body: fd });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not read that file', 'error'); return; }
    SG.cols = out.columns; SG.rows = out.rows; SG.problems = out.problems || {};
    var read = Object.keys(out.read_as || {}).map(function (h) { return h + ' → ' + out.read_as[h]; }).join(', ');
    document.getElementById('sg-note').innerHTML = esc(out.message) +
        (read ? ' <span title="' + esc(read) + '" style="text-decoration:underline dotted;cursor:help;">Columns read</span>' : '');
    document.getElementById('sg-add').style.display = '';
    document.getElementById('sg-go').style.display = '';
    sheetGridPaint();
}
window.sheetGridRead = sheetGridRead;

function sheetGridPaint() {
    var host = document.getElementById('sg-grid');
    var qtyKey = SG.cols.some(function (c) { return c.key === 'qty'; }) ? 'qty' : null;
    var rateKey = ['rate', 'price', 'unit_rate'].filter(function (k) { return SG.cols.some(function (c) { return c.key === k; }); })[0];
    var total = 0;
    var body = SG.rows.map(function (r, i) {
        var p = SG.problems[String(i)] || [];
        if (qtyKey && rateKey) total += (parseFloat(r[qtyKey]) || 0) * (parseFloat(r[rateKey]) || 0);
        return '<tr style="' + (p.length ? 'background:rgba(220,38,38,0.05);' : '') + '">' +
            '<td style="font-size:0.72rem;color:var(--text-secondary);">' + (r._line || i + 1) + '</td>' +
            SG.cols.map(function (c) {
                // Wide enough to read what was imported: the description most of all.
                var w = c.number ? 90 : (/desc|name|particular/.test(c.key) ? 240 : 100);
                return '<td style="padding:3px;"><input class="form-control input-sm" style="min-width:' + w + 'px;' +
                    (c.number ? 'text-align:right;" type="number" step="any"' : '"') +
                    ' value="' + esc(r[c.key] == null ? '' : r[c.key]) + '" oninput="sheetGridEdit(' + i + ',\'' + c.key + '\',this.value)"></td>';
            }).join('') +
            '<td style="font-size:0.74rem;color:var(--danger-color);min-width:150px;">' + p.map(esc).join('<br>') + '</td>' +
            '<td><button class="btn-icon" title="Leave this row out" onclick="sheetGridDrop(' + i + ')">&times;</button></td></tr>';
    }).join('');
    host.innerHTML = '<div class="table-responsive" style="max-height:52vh;overflow:auto;"><table class="data-table"><thead><tr><th>Row</th>' +
        SG.cols.map(function (c) { return '<th' + (c.number ? ' class="text-right"' : '') + '>' + esc(c.label) + '</th>'; }).join('') +
        '<th>Needs a look</th><th></th></tr></thead><tbody>' +
        (body || '<tr><td colspan="' + (SG.cols.length + 3) + '" style="text-align:center;padding:18px;color:var(--text-secondary);">No rows.</td></tr>') +
        '</tbody></table></div>' +
        '<div style="display:flex;justify-content:space-between;margin-top:8px;font-size:0.85rem;">' +
            '<span id="sg-count">' + sheetGridCount() + '</span>' +
            (qtyKey && rateKey ? '<strong>' + formatCurrency(total) + '</strong>' : '') + '</div>';
}

function sheetGridCount() {
    var bad = Object.keys(SG.problems).length;
    return SG.rows.length + ' row' + (SG.rows.length === 1 ? '' : 's') +
        (bad ? ' &middot; <span style="color:var(--danger-color);">' + bad + ' need a look</span>' : ' &middot; all fine');
}

function sheetGridEdit(i, key, value) {
    var col = SG.cols.filter(function (c) { return c.key === key; })[0];
    SG.rows[i][key] = col && col.number ? (parseFloat(value) || 0) : value;
    clearTimeout(SG.timer);
    SG.timer = setTimeout(sheetGridCheck, 500);
}
window.sheetGridEdit = sheetGridEdit;

async function sheetGridCheck() {
    var res = await fetch('/api/sheets/' + encodeURIComponent(SG.kind) + '/check', { method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ rows: SG.rows }) });
    if (!res.ok) return;
    SG.problems = (await res.json()).problems || {};
    // Repaint the problems only, so the cell being typed in keeps its focus.
    var trs = document.querySelectorAll('#sg-grid tbody tr');
    trs.forEach(function (tr, i) {
        var p = SG.problems[String(i)] || [];
        tr.style.background = p.length ? 'rgba(220,38,38,0.05)' : '';
        var cell = tr.children[SG.cols.length + 1];
        if (cell) cell.innerHTML = p.map(esc).join('<br>');
    });
    var count = document.getElementById('sg-count');
    if (count) count.innerHTML = sheetGridCount();
}

function sheetGridAdd() {
    var row = {};
    SG.cols.forEach(function (c) { row[c.key] = c.number ? 0 : ''; });
    SG.rows.push(row);
    sheetGridPaint();
    sheetGridCheck();
}
window.sheetGridAdd = sheetGridAdd;

function sheetGridDrop(i) {
    SG.rows.splice(i, 1);
    sheetGridPaint();
    sheetGridCheck();
}
window.sheetGridDrop = sheetGridDrop;

async function sheetGridConfirm() {
    if (!SG.rows.length) { showToast('No rows to use', 'error'); return; }
    var done = await SG.opts.onConfirm(SG.rows.map(function (r) { var c = Object.assign({}, r); delete c._line; return c; }), SG.problems);
    if (done !== false) closeModal('sheetgrid-modal');
}
window.sheetGridConfirm = sheetGridConfirm;
