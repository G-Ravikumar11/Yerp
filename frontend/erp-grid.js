/* ===========================================================================
   erp-grid.js - a spreadsheet, in the application.

   People know how to work a spreadsheet. Taking the file away and replacing it
   with a form is not an improvement, it is a demotion: you lose the keyboard,
   you lose paste, you lose being able to see twenty rows at once.

   So this is a grid that behaves like one. Tab and Enter move, the arrows
   move, a block copied out of Excel pastes straight in and grows the sheet to
   fit, and the last row makes another as soon as you type in it. What it does
   not do is let you enter something invalid: the columns that have a fixed set
   of answers are pickers, and the code is issued rather than typed.
   =========================================================================== */

var GRID = {
    columns: [],
    rows: [],
    host: null,
    onChange: null,
    minRows: 8,
};

/* A blank row shaped by the column definitions. */
function gridBlankRow() {
    var row = {};
    GRID.columns.forEach(function (c) {
        row[c.key] = typeof c.def === 'function' ? c.def() : (c.def || '');
    });
    return row;
}

function gridIsBlank(row) {
    return GRID.columns.every(function (c) {
        if (c.options) return true;              // a picker always has a value
        return !String(row[c.key] || '').trim();
    });
}

function mountGrid(hostId, columns, options) {
    options = options || {};
    GRID.host = document.getElementById(hostId);
    GRID.columns = columns;
    GRID.onChange = options.onChange || null;
    GRID.minRows = options.minRows || 8;
    GRID.rows = [];
    while (GRID.rows.length < GRID.minRows) GRID.rows.push(gridBlankRow());
    renderGrid();
}
window.mountGrid = mountGrid;

function renderGrid(focus) {
    if (!GRID.host) return;

    var head = '<th class="w-10 px-2 py-2 text-right text-xxs font-semibold text-ink-faint ' +
               'bg-slate-50 border-b border-slate-200 sticky left-0 z-10">#</th>' +
        GRID.columns.map(function (c) {
            return '<th class="px-2 py-2 text-left text-xxs font-semibold uppercase tracking-wide ' +
                'text-ink-soft bg-slate-50 border-b border-slate-200" ' +
                'style="min-width:' + (c.width || '150px') + '">' + esc(c.label) +
                (c.hint ? '<span class="block font-normal normal-case text-ink-faint">' +
                          esc(c.hint) + '</span>' : '') + '</th>';
        }).join('') +
        '<th class="w-8 bg-slate-50 border-b border-slate-200"></th>';

    var body = GRID.rows.map(function (row, r) {
        var filled = !gridIsBlank(row);
        var cells = GRID.columns.map(function (c, col) {
            var common = 'data-r="' + r + '" data-c="' + col + '" ' +
                'class="gridcell w-full bg-transparent px-2 py-1.5 text-[13px] border-0 ' +
                'focus:outline-none focus:ring-2 focus:ring-brand focus:bg-white rounded-sm"';
            if (c.readonly) {
                return '<td class="border-b border-r border-slate-100 px-2 py-1.5 text-[13px] ' +
                    'font-mono text-ink-faint">' + esc(row[c.key] || c.placeholder || '') + '</td>';
            }
            if (c.options) {
                return '<td class="border-b border-r border-slate-100 p-0">' +
                    '<select ' + common + ' onchange="gridSet(' + r + ',' + col + ',this.value)">' +
                    c.options.map(function (o) {
                        return '<option' + (o === row[c.key] ? ' selected' : '') + '>' + esc(o) + '</option>';
                    }).join('') + '</select></td>';
            }
            return '<td class="border-b border-r border-slate-100 p-0">' +
                '<input ' + common + ' value="' + esc(row[c.key] || '') + '"' +
                (c.placeholder ? ' placeholder="' + esc(c.placeholder) + '"' : '') +
                ' oninput="gridSet(' + r + ',' + col + ',this.value)"></td>';
        }).join('');

        return '<tr class="' + (filled ? 'bg-white' : '') + '">' +
            '<td class="px-2 py-1.5 text-right text-xxs text-ink-faint bg-slate-50/70 ' +
                'border-b border-r border-slate-200 sticky left-0">' + (r + 1) + '</td>' +
            cells +
            '<td class="border-b border-slate-100 text-center">' +
                (filled ? '<button class="text-ink-faint hover:text-red-600 px-1" ' +
                          'onclick="gridClearRow(' + r + ')" title="Clear this row">&times;</button>' : '') +
            '</td></tr>';
    }).join('');

    var used = GRID.rows.filter(function (r) { return !gridIsBlank(r); }).length;

    GRID.host.innerHTML =
        '<div class="flex items-center justify-between mb-2">' +
            '<p class="text-xxs text-ink-soft">' +
                'Tab or Enter to move · paste a block straight from Excel · ' +
                'the last row makes another as you type</p>' +
            '<p class="text-xxs font-semibold text-ink">' + used + ' row' +
                (used === 1 ? '' : 's') + ' ready</p>' +
        '</div>' +
        '<div id="grid-scroll" class="border border-slate-200 rounded-lg overflow-auto max-h-[28rem]">' +
        '<table class="min-w-full border-collapse"><thead class="sticky top-0 z-20"><tr>' +
        head + '</tr></thead><tbody>' + body + '</tbody></table></div>';

    if (GRID.onChange) GRID.onChange(used);
    if (focus) gridFocus(focus.r, focus.c);
}

function gridCell(r, c) {
    return GRID.host.querySelector('.gridcell[data-r="' + r + '"][data-c="' + c + '"]');
}

function gridFocus(r, c) {
    var el = gridCell(r, c);
    if (el) { el.focus(); if (el.select) el.select(); }
}
window.gridFocus = gridFocus;

function gridSet(r, c, value) {
    var col = GRID.columns[c];
    GRID.rows[r][col.key] = value;
    // Typing in the last row makes another, the way a sheet always has one
    // more line waiting underneath.
    if (r === GRID.rows.length - 1 && !gridIsBlank(GRID.rows[r])) {
        GRID.rows.push(gridBlankRow());
        renderGrid({ r: r, c: c });
        var el = gridCell(r, c);
        if (el && el.setSelectionRange) {
            try { el.setSelectionRange(value.length, value.length); } catch (e) {}
        }
        return;
    }
    var counter = GRID.host.querySelector('p.text-xxs.font-semibold');
    if (counter) {
        var used = GRID.rows.filter(function (x) { return !gridIsBlank(x); }).length;
        counter.textContent = used + ' row' + (used === 1 ? '' : 's') + ' ready';
    }
}
window.gridSet = gridSet;

function gridClearRow(r) {
    GRID.rows[r] = gridBlankRow();
    renderGrid({ r: r, c: 0 });
}
window.gridClearRow = gridClearRow;

/* --- Keyboard ------------------------------------------------------------ */

document.addEventListener('keydown', function (e) {
    var cell = e.target.closest ? e.target.closest('.gridcell') : null;
    if (!cell || !GRID.host || !GRID.host.contains(cell)) return;

    var r = parseInt(cell.dataset.r), c = parseInt(cell.dataset.c);
    var lastCol = GRID.columns.length - 1;
    var move = null;

    if (e.key === 'Tab') {
        move = e.shiftKey
            ? (c > 0 ? { r: r, c: c - 1 } : (r > 0 ? { r: r - 1, c: lastCol } : null))
            : (c < lastCol ? { r: r, c: c + 1 } : { r: r + 1, c: 0 });
    } else if (e.key === 'Enter') {
        move = { r: r + 1, c: c };
    } else if (e.key === 'ArrowDown') {
        move = { r: r + 1, c: c };
    } else if (e.key === 'ArrowUp') {
        move = { r: r - 1, c: c };
    } else if (e.key === 'ArrowLeft' && cell.selectionStart === 0) {
        move = { r: r, c: Math.max(0, c - 1) };
    } else if (e.key === 'ArrowRight' && cell.selectionStart === (cell.value || '').length) {
        move = { r: r, c: Math.min(lastCol, c + 1) };
    }
    if (!move) return;

    e.preventDefault();
    // Walking off the bottom makes a row, rather than trapping the cursor.
    while (move.r >= GRID.rows.length) {
        GRID.rows.push(gridBlankRow());
        renderGrid();
    }
    if (move.r < 0) move.r = 0;
    gridFocus(move.r, move.c);
});

/* --- Paste ---------------------------------------------------------------
   The point of the whole thing. A block copied out of Excel arrives as tab
   separated lines, so it drops in from wherever the cursor is and grows the
   sheet to fit rather than truncating at whatever was already there.
   ------------------------------------------------------------------------ */

document.addEventListener('paste', function (e) {
    var cell = e.target.closest ? e.target.closest('.gridcell') : null;
    if (!cell || !GRID.host || !GRID.host.contains(cell)) return;

    var text = (e.clipboardData || window.clipboardData).getData('text/plain') || '';
    if (text.indexOf('\t') < 0 && text.indexOf('\n') < 0) return;   // a plain value: let it be

    e.preventDefault();
    var startR = parseInt(cell.dataset.r), startC = parseInt(cell.dataset.c);
    var lines = text.replace(/\r/g, '').split('\n').filter(function (l, i, all) {
        return l.length || i < all.length - 1;     // keep interior blanks, drop a trailing one
    });

    var landed = 0;
    lines.forEach(function (line, dr) {
        var values = line.split('\t');
        var r = startR + dr;
        while (r >= GRID.rows.length) GRID.rows.push(gridBlankRow());
        values.forEach(function (value, dc) {
            var col = GRID.columns[startC + dc];
            if (!col || col.readonly) return;
            value = String(value).trim();
            // A picker only accepts what it offers; anything else is matched
            // case-insensitively and otherwise left at its default.
            if (col.options) {
                var hit = col.options.filter(function (o) {
                    return o.toLowerCase() === value.toLowerCase();
                })[0];
                if (hit) GRID.rows[r][col.key] = hit;
            } else {
                GRID.rows[r][col.key] = value;
            }
        });
        landed++;
    });

    while (GRID.rows.length && gridIsBlank(GRID.rows[GRID.rows.length - 1]) &&
           GRID.rows.length > GRID.minRows) {
        GRID.rows.pop();
    }
    GRID.rows.push(gridBlankRow());
    renderGrid({ r: startR, c: startC });
    if (typeof showToast === 'function') {
        showToast(landed + ' row' + (landed === 1 ? '' : 's') + ' pasted in', 'success');
    }
});

/* Everything typed in, minus the rows nobody touched. */
function gridData() {
    return GRID.rows.filter(function (r) { return !gridIsBlank(r); });
}
window.gridData = gridData;

function gridReset() {
    GRID.rows = [];
    while (GRID.rows.length < GRID.minRows) GRID.rows.push(gridBlankRow());
    renderGrid();
}
window.gridReset = gridReset;
