/* ===========================================================================
   mbdims.js - the dimension sheet inside a measurement.

   A measurement book is a book of dimensions: Particulars, No, L, B, D and
   what they come to, line under line, deductions taken away. That is what a
   billing engineer writes, and until now the app took only the answer - so
   the writing happened in a spreadsheet. This is the sheet, in the modal,
   with the arithmetic done as the figures are typed.

   Used by both books, the client's and the gang's.
   =========================================================================== */

var DIMS = {};

var DIM_COLS = ['particulars', 'nos', 'length', 'breadth', 'depth'];

function dimBlank() {
    return { particulars: '', nos: '', length: '', breadth: '', depth: '', deduct: false };
}

function dimQty(row) {
    /* No x L x B x D, over the figures that were given. A blank does not
       apply - an area has no depth - and is not a nought. */
    var has = false, qty = 1;
    if (row.nos !== '' && row.nos !== null) { qty *= parseFloat(row.nos) || 0; has = true; }
    ['length', 'breadth', 'depth'].forEach(function (k) {
        if (row[k] !== '' && row[k] !== null) { qty *= parseFloat(row[k]) || 0; has = true; }
    });
    if (!has) return null;
    return Math.round(qty * 1000) / 1000 * (row.deduct ? -1 : 1);
}

function dimsInit(hostId, uom) {
    DIMS[hostId] = { rows: [dimBlank(), dimBlank()], uom: uom || '' };
    dimsRender(hostId);
}
window.dimsInit = dimsInit;

function dimsRender(hostId, focus) {
    var host = document.getElementById(hostId);
    if (!host) return;
    var st = DIMS[hostId];
    var cell = function (r, key, extra) {
        var isText = key === 'particulars';
        return '<td' + (isText ? '' : ' style="width:86px;padding-left:4px;padding-right:4px;"') + '><input class="form-control dimcell" ' +
            'data-r="' + r + '" data-k="' + key + '" ' +
            (isText ? 'placeholder="' + (r === 0 ? 'Footing F1, grid A-3' : '') + '" style="min-width:150px;" '
                    : 'type="number" step="any" min="0" inputmode="decimal" style="text-align:right;padding:4px 6px;width:82px;min-width:82px;" ') +
            'value="' + esc(String(st.rows[r][key] === null ? '' : st.rows[r][key])) + '" ' +
            'oninput="dimSet(\'' + hostId + '\',' + r + ',\'' + key + '\',this.value)"' + (extra || '') + '></td>';
    };
    var total = 0, any = false;
    var rows = st.rows.map(function (row, r) {
        var q = dimQty(row);
        if (q !== null) { total += q; any = true; }
        return '<tr' + (row.deduct ? ' style="color:var(--warning-color);"' : '') + '>' +
            cell(r, 'particulars') + cell(r, 'nos') + cell(r, 'length') + cell(r, 'breadth') + cell(r, 'depth') +
            '<td style="text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums;padding:4px 6px;">' +
                (q === null ? '' : (q < 0 ? '−' : '') + Math.abs(q).toFixed(3)) + '</td>' +
            '<td style="text-align:center;"><input type="checkbox" title="Deduct" ' + (row.deduct ? 'checked' : '') +
                ' onchange="dimSet(\'' + hostId + '\',' + r + ',\'deduct\',this.checked)"></td>' +
            '<td><button type="button" class="btn btn-sm btn-outline" style="padding:2px 7px;" ' +
                'onclick="dimRemove(\'' + hostId + '\',' + r + ')" tabindex="-1">&times;</button></td>' +
            '</tr>';
    }).join('');
    host.innerHTML =
        '<table class="data-table dims" style="font-size:0.8rem;">' +
        '<thead><tr><th>Particulars</th><th class="text-right">No</th><th class="text-right">L</th>' +
        '<th class="text-right">B</th><th class="text-right">D / H</th><th class="text-right">Qty</th>' +
        '<th title="Deduction - an opening, a void">Ded.</th><th></th></tr></thead>' +
        '<tbody>' + rows + '</tbody>' +
        '<tfoot><tr><td colspan="5" style="text-align:right;padding:6px;">' +
            '<button type="button" class="btn btn-sm btn-outline" onclick="dimAdd(\'' + hostId + '\')">+ Line</button>' +
            ' <strong style="margin-left:10px;">Total</strong></td>' +
            '<td style="text-align:right;font-weight:700;white-space:nowrap;padding:6px;">' +
            (any ? (total < 0 ? '−' : '') + Math.abs(Math.round(total * 1000) / 1000).toFixed(3) : '—') +
            '</td><td colspan="2" style="font-size:0.72rem;color:var(--text-secondary);">' + esc(st.uom) + '</td></tr></tfoot>' +
        '</table>' +
        '<p style="font-size:0.72rem;color:var(--text-secondary);margin:6px 0 0;">' +
        'Leave a dimension blank when it does not apply. Tick <em>Ded.</em> for an opening or a void. ' +
        'Enter on the last line adds one.</p>';
    if (focus) {
        var el = host.querySelector('.dimcell[data-r="' + focus.r + '"][data-k="' + focus.k + '"]');
        if (el) el.focus();
    }
    var totalEl = document.getElementById(hostId + '-total');
    if (totalEl) totalEl.value = any ? Math.round(total * 1000) / 1000 : '';
}

function dimSet(hostId, r, key, value) {
    DIMS[hostId].rows[r][key] = value;
    // Only the figures are redrawn as you type. Redrawing the inputs would
    // take the caret out of the cell being edited, so the row's quantity and
    // the total are patched in place.
    var host = document.getElementById(hostId);
    var tr = host.querySelectorAll('tbody tr')[r];
    var q = dimQty(DIMS[hostId].rows[r]);
    if (tr) {
        tr.children[5].textContent = q === null ? '' : (q < 0 ? '−' : '') + Math.abs(q).toFixed(3);
        tr.style.color = DIMS[hostId].rows[r].deduct ? 'var(--warning-color)' : '';
    }
    var total = 0, any = false;
    DIMS[hostId].rows.forEach(function (row) {
        var x = dimQty(row); if (x !== null) { total += x; any = true; }
    });
    var foot = host.querySelector('tfoot td:nth-child(2)');
    if (foot) foot.textContent = any ? (total < 0 ? '−' : '') + Math.abs(Math.round(total * 1000) / 1000).toFixed(3) : '—';
    var totalEl = document.getElementById(hostId + '-total');
    if (totalEl) totalEl.value = any ? Math.round(total * 1000) / 1000 : '';
}
window.dimSet = dimSet;

function dimAdd(hostId) {
    DIMS[hostId].rows.push(dimBlank());
    dimsRender(hostId, { r: DIMS[hostId].rows.length - 1, k: 'particulars' });
}
window.dimAdd = dimAdd;

function dimRemove(hostId, r) {
    DIMS[hostId].rows.splice(r, 1);
    if (!DIMS[hostId].rows.length) DIMS[hostId].rows.push(dimBlank());
    dimsRender(hostId);
}
window.dimRemove = dimRemove;

function dimsRows(hostId) {
    /* The lines with figures on them, as the API takes them. Blank rows are
       rows nobody used, not measurements of nothing. */
    var st = DIMS[hostId];
    if (!st) return [];
    var num = function (v) { return v === '' || v === null || v === undefined ? null : parseFloat(v); };
    return st.rows.filter(function (row) { return dimQty(row) !== null; }).map(function (row) {
        return { particulars: row.particulars || '', nos: num(row.nos), length: num(row.length),
                 breadth: num(row.breadth), depth: num(row.depth), deduct: !!row.deduct };
    });
}
window.dimsRows = dimsRows;

/* Enter on the last line adds one; Enter elsewhere moves down the column. */
document.addEventListener('keydown', function (e) {
    var cell = e.target.closest ? e.target.closest('.dimcell') : null;
    if (!cell || e.key !== 'Enter') return;
    e.preventDefault();
    var host = cell.closest('[id]');
    while (host && !DIMS[host.id]) host = host.parentElement ? host.parentElement.closest('[id]') : null;
    if (!host) return;
    var r = parseInt(cell.dataset.r), k = cell.dataset.k;
    if (r >= DIMS[host.id].rows.length - 1) { dimAdd(host.id); dimsRender(host.id, { r: r + 1, k: k }); return; }
    var next = host.querySelector('.dimcell[data-r="' + (r + 1) + '"][data-k="' + k + '"]');
    if (next) next.focus();
});

/* How an entry's dimensions read in the book: one line each, the way they
   were written, under the total. */
function dimsSummary(dims) {
    if (!dims || !dims.length) return '';
    var f = function (v) { return v === null || v === undefined ? null : (Math.round(v * 1000) / 1000).toString(); };
    return '<div style="font-size:0.72rem;color:var(--text-secondary);margin-top:3px;text-align:left;' +
        'font-variant-numeric:tabular-nums;">' + dims.map(function (d) {
            var parts = [f(d.nos), f(d.length), f(d.breadth), f(d.depth)].filter(function (x) { return x !== null; });
            return (d.deduct ? '<span style="color:var(--warning-color);">Deduct </span>' : '') +
                (d.particulars ? esc(d.particulars) + ' &nbsp;' : '') +
                parts.join(' × ') + ' = ' + (d.quantity < 0 ? '−' : '') + Math.abs(d.quantity).toFixed(3);
        }).join('<br>') + '</div>';
}
window.dimsSummary = dimsSummary;
