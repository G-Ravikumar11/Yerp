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

var DIM_COLS = ['particulars', 'nos', 'nom', 'length', 'breadth', 'depth'];

function dimBlank() {
    return { particulars: '', nos: '', nom: '', length: '', breadth: '', depth: '', deduct: false, is_heading: false };
}

function dimQty(row) {
    /* No's x NoM x L x B x D, over the figures that were given. A blank does
       not apply - an area has no depth - and is not a nought. A heading
       ("Living Room", "Deductions") measures nothing. */
    if (row.is_heading) return null;
    var has = false, qty = 1;
    if (row.nos !== '' && row.nos !== null) { qty *= parseFloat(row.nos) || 0; has = true; }
    ['nom', 'length', 'breadth', 'depth'].forEach(function (k) {
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
        var heading = st.rows[r].is_heading;
        if (heading && !isText) return '<td></td>';
        return '<td' + (isText ? '' : ' style="width:72px;padding-left:3px;padding-right:3px;"') + '><input class="form-control dimcell" ' +
            'data-r="' + r + '" data-k="' + key + '" ' +
            (isText ? 'placeholder="' + (r === 0 ? 'Ceiling - Hall, or a heading: Living Room' : '') + '" style="min-width:150px;' +
                      (heading ? 'font-weight:700;font-style:italic;' : '') + '" '
                    : 'type="number" step="any" min="0" inputmode="decimal" style="text-align:right;padding:4px 5px;width:68px;min-width:68px;" ') +
            'value="' + esc(String(st.rows[r][key] === null ? '' : st.rows[r][key])) + '" ' +
            'oninput="dimSet(\'' + hostId + '\',' + r + ',\'' + key + '\',this.value)"' + (extra || '') + '></td>';
    };
    var total = 0, any = false;
    var rows = st.rows.map(function (row, r) {
        var q = dimQty(row);
        if (q !== null) { total += q; any = true; }
        return '<tr' + (row.deduct ? ' style="color:var(--warning-color);"' : '') + '>' +
            cell(r, 'particulars') + cell(r, 'nos') + cell(r, 'nom') + cell(r, 'length') + cell(r, 'breadth') + cell(r, 'depth') +
            '<td style="text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums;padding:4px 6px;">' +
                (q === null ? '' : (q < 0 ? '−' : '') + Math.abs(q).toFixed(3)) + '</td>' +
            '<td style="text-align:center;"><input type="checkbox" title="A heading - groups the lines under it" ' +
                (row.is_heading ? 'checked' : '') +
                ' onchange="dimSet(\'' + hostId + '\',' + r + ',\'is_heading\',this.checked);dimsRender(\'' + hostId + '\')"></td>' +
            '<td style="text-align:center;"><input type="checkbox" title="Deduct" ' + (row.deduct ? 'checked' : '') +
                (row.is_heading ? ' disabled' : '') +
                ' onchange="dimSet(\'' + hostId + '\',' + r + ',\'deduct\',this.checked)"></td>' +
            '<td><button type="button" class="btn btn-sm btn-outline" style="padding:2px 7px;" ' +
                'onclick="dimRemove(\'' + hostId + '\',' + r + ')" tabindex="-1">&times;</button></td>' +
            '</tr>';
    }).join('');
    host.innerHTML =
        '<table class="data-table dims" style="font-size:0.8rem;">' +
        '<thead><tr><th>Particulars</th><th class="text-right">No\'s</th><th class="text-right" title="Number of members in each">NoM</th>' +
        '<th class="text-right">L</th><th class="text-right">B / W</th><th class="text-right">D / H</th><th class="text-right">Qty</th>' +
        '<th title="A heading line - Living Room, Deductions">Head</th>' +
        '<th title="Deduction - an opening, a void">Ded.</th><th></th></tr></thead>' +
        '<tbody>' + rows + '</tbody>' +
        '<tfoot><tr><td colspan="6" style="text-align:right;padding:6px;">' +
            '<button type="button" class="btn btn-sm btn-outline" onclick="dimAdd(\'' + hostId + '\')">+ Line</button>' +
            ' <strong style="margin-left:10px;">Total</strong></td>' +
            '<td style="text-align:right;font-weight:700;white-space:nowrap;padding:6px;">' +
            (any ? (total < 0 ? '−' : '') + Math.abs(Math.round(total * 1000) / 1000).toFixed(3) : '—') +
            '</td><td colspan="3" style="font-size:0.72rem;color:var(--text-secondary);">' + esc(st.uom) + '</td></tr></tfoot>' +
        '</table>' +
        '<p style="font-size:0.72rem;color:var(--text-secondary);margin:6px 0 0;">' +
        'Leave a dimension blank when it does not apply. Tick <em>Head</em> for a heading line, <em>Ded.</em> for an opening or a void. ' +
        'Enter on the last line adds one. Lines copied from the MB sheet in Excel (Description, UoM, No\'s, NoM, Length, Width, Height) ' +
        'paste straight in - a negative No\'s is a deduction.</p>';
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
        tr.children[6].textContent = q === null ? '' : (q < 0 ? '−' : '') + Math.abs(q).toFixed(3);
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
    var rows = st.rows.filter(function (row) {
        return row.is_heading ? !!(row.particulars || '').trim() : dimQty(row) !== null;
    });
    // Headings alone are not a measurement.
    if (!rows.some(function (row) { return !row.is_heading; })) return [];
    return rows.map(function (row) {
        if (row.is_heading) return { particulars: row.particulars.trim(), is_heading: true };
        return { particulars: row.particulars || '', nos: num(row.nos), nom: num(row.nom), length: num(row.length),
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

/* Lines copied out of the MB sheet in Excel paste in as lines. The columns
   are read in the book's order - Description, UoM, No's, NoM, Length, Width,
   Height - with the UoM column skipped when there is one, and a row with
   words and no figures becomes a heading. A negative No's is a deduction, as
   the sheet writes it. Pasting a single value is left to the browser. */
document.addEventListener('paste', function (e) {
    var cell = e.target.closest ? e.target.closest('.dimcell') : null;
    if (!cell) return;
    var text = (e.clipboardData || window.clipboardData).getData('text');
    if (!text || (text.indexOf('\t') < 0 && text.indexOf('\n') < 0)) return;
    var host = cell.closest('[id]');
    while (host && !DIMS[host.id]) host = host.parentElement ? host.parentElement.closest('[id]') : null;
    if (!host) return;
    e.preventDefault();
    var st = DIMS[host.id], start = parseInt(cell.dataset.r), fromText = cell.dataset.k === 'particulars';
    var lines = text.replace(/\r/g, '').split('\n').filter(function (l) { return l.trim() !== ''; });
    var parsed = lines.map(function (line) {
        var cols = line.split('\t').map(function (c) { return c.trim(); });
        var row = dimBlank();
        if (fromText) row.particulars = cols.shift() || '';
        if (cols.length && cols[0] !== '' && isNaN(parseFloat(cols[0].replace(/,/g, '')))) cols.shift();   // the UoM
        var keys = ['nos', 'nom', 'length', 'breadth', 'depth'];
        if (!fromText) keys = keys.slice(Math.max(0, keys.indexOf(cell.dataset.k)));
        var neg = 1;
        keys.forEach(function (k, i) {
            var v = (cols[i] || '').replace(/,/g, '');
            if (v === '' || isNaN(parseFloat(v))) return;
            var n = parseFloat(v);
            if (n < 0) { neg = -neg; n = -n; }
            row[k] = String(n);
        });
        row.deduct = neg < 0;
        row.is_heading = fromText && !!row.particulars && keys.every(function (k) { return row[k] === ''; });
        return row;
    });
    parsed.forEach(function (row, i) {
        var at = start + i;
        if (at < st.rows.length && !fromText) {
            ['nos', 'nom', 'length', 'breadth', 'depth'].forEach(function (k) { if (row[k] !== '') st.rows[at][k] = row[k]; });
            st.rows[at].deduct = st.rows[at].deduct || row.deduct;
        } else if (at < st.rows.length && !st.rows[at].particulars && dimQty(st.rows[at]) === null) {
            st.rows[at] = row;
        } else {
            st.rows.splice(at, 0, row);
        }
    });
    dimsRender(host.id);
});

/* How an entry's dimensions read in the book: one line each, the way they
   were written, under the total. */
function dimsSummary(dims) {
    if (!dims || !dims.length) return '';
    var f = function (v) { return v === null || v === undefined ? null : (Math.round(v * 1000) / 1000).toString(); };
    return '<div style="font-size:0.72rem;color:var(--text-secondary);margin-top:3px;text-align:left;' +
        'font-variant-numeric:tabular-nums;">' + dims.map(function (d) {
            if (d.is_heading) return '<strong><em>' + esc(d.particulars) + '</em></strong>';
            var parts = [f(d.nos), f(d.nom), f(d.length), f(d.breadth), f(d.depth)].filter(function (x) { return x !== null; });
            return (d.deduct ? '<span style="color:var(--warning-color);">Deduct </span>' : '') +
                (d.particulars ? esc(d.particulars) + ' &nbsp;' : '') +
                parts.join(' × ') + ' = ' + (d.quantity < 0 ? '−' : '') + Math.abs(d.quantity).toFixed(3);
        }).join('<br>') + '</div>';
}
window.dimsSummary = dimsSummary;
