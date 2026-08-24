/* ===========================================================================
   sheet-viewer.js - open any workbook and look at it.

   Every other upload on this system asks you to declare what a file is before
   it will open it. Get that wrong and you are told about a missing column, on
   a sheet you never chose, in a workbook with eight tabs. This opens the file
   first and says what it found: which tabs it has, which one it is showing,
   where the headings actually are, and what the sheet looks like it is.

   Nothing here saves anything. Once you can see the file, the buttons at the
   bottom hand it to whichever importer it turns out to belong to.
   =========================================================================== */

var VIEWER = { file: null, sheet: '', data: null };

var VIEWER_TARGETS = {
    items: { label: 'Item master', view: 'items-view' },
    work_order: { label: 'Work order', view: 'workorders-view' },
    bom: { label: 'Budget / BOM', view: 'workorders-view' },
};


/* --- The sheet picker on the import forms --------------------------------
   An importer used to read whichever tab happened to be saved first, with no
   way to say otherwise. A workbook with one sheet still asks nothing; the
   picker appears only when there is a genuine choice to make.
   ------------------------------------------------------------------------ */

async function offerSheets(input, rowId, selectId) {
    var row = document.getElementById(rowId);
    var select = document.getElementById(selectId);
    if (!row || !select) return;
    row.style.display = 'none';
    select.innerHTML = '';

    var file = input.files && input.files[0];
    if (!file) return;

    var form = new FormData();
    form.append('file', file);
    try {
        var res = await fetch('/api/erp/sheets/inspect',
                              { method: 'POST', credentials: 'include', body: form });
        if (!res.ok) return;                 // the importer will say why
        var data = await res.json();
    } catch (e) {
        return;
    }
    if (!data.sheets || data.sheets.length < 2) return;

    select.innerHTML = data.sheets.map(function (s) {
        return '<option value="' + esc(s.name) + '">' + esc(s.name) +
            ' (' + s.rows + ' rows)</option>';
    }).join('');
    select.value = data.sheet;
    row.style.display = '';
}
window.offerSheets = offerSheets;


function chosenSheet(selectId) {
    var el = document.getElementById(selectId);
    var row = el && el.closest('.form-group');
    return (row && row.style.display !== 'none' && el.value) ? el.value : '';
}
window.chosenSheet = chosenSheet;


function viewerPick(input) {
    VIEWER.file = input.files && input.files[0];
    VIEWER.sheet = '';
    if (VIEWER.file) inspectSheet();
}
window.viewerPick = viewerPick;


async function inspectSheet(sheet) {
    var host = document.getElementById('viewer-body');
    if (!host || !VIEWER.file) return;
    if (typeof sheet === 'string') VIEWER.sheet = sheet;

    host.innerHTML = '<p style="text-align:center;padding:30px;color:var(--text-secondary);">' +
        'Opening ' + esc(VIEWER.file.name) + '...</p>';

    var form = new FormData();
    form.append('file', VIEWER.file);
    form.append('sheet', VIEWER.sheet || '');

    var res, data;
    try {
        res = await fetch('/api/erp/sheets/inspect',
                          { method: 'POST', credentials: 'include', body: form });
        data = await res.json();
    } catch (e) {
        host.innerHTML = '<p style="text-align:center;padding:30px;color:var(--danger-color);">' +
            'That file could not be read.</p>';
        return;
    }
    if (!res.ok) {
        host.innerHTML = '<p style="text-align:center;padding:30px;color:var(--danger-color);">' +
            esc(data.detail || 'That file could not be read.') + '</p>';
        return;
    }
    VIEWER.data = data;
    VIEWER.sheet = data.sheet;
    renderSheetViewer();
}
window.inspectSheet = inspectSheet;


function viewerTabs(d) {
    if (d.sheets.length < 2) return '';
    return '<div class="invoices-tabs" style="margin-bottom:14px;">' +
        d.sheets.map(function (s) {
            var on = s.name === d.sheet;
            return '<button class="tab' + (on ? ' active' : '') + '" ' +
                'onclick="inspectSheet(' + JSON.stringify(s.name).replace(/"/g, '&quot;') + ')">' +
                esc(s.name) +
                '<span style="opacity:0.6;font-weight:400;"> · ' + s.rows + '</span>' +
                '</button>';
        }).join('') + '</div>';
}


function viewerSummary(d) {
    var known = d.guess.kind;
    var what = known
        ? statusPill('Looks like a ' + d.guess.label, 'good')
        : statusPill('Not a format this system imports', 'calm');

    var facts = [
        d.total_rows + ' row' + (d.total_rows === 1 ? '' : 's') + ' of data',
        'headings on row ' + d.header_row,
        d.columns + ' column' + (d.columns === 1 ? '' : 's') +
            (d.truncated_columns ? ' shown' : ''),
    ].join(' · ');

    return '<div style="display:flex;justify-content:space-between;align-items:center;' +
        'gap:12px;flex-wrap:wrap;margin-bottom:12px;">' +
        '<div>' + what +
            '<div style="font-size:0.8rem;color:var(--text-secondary);margin-top:6px;">' +
            esc(facts) + '</div></div>' +
        '<div>' + viewerActions(d) + '</div></div>';
}


function viewerActions(d) {
    // The likely target first, but never the only one on offer - the guess is
    // read off the headings, and the person holding the file knows better.
    var order = Object.keys(VIEWER_TARGETS).sort(function (a, b) {
        return (b === d.guess.kind) - (a === d.guess.kind);
    });
    return order.map(function (kind, i) {
        var t = VIEWER_TARGETS[kind];
        return '<button class="btn btn-sm ' +
            (i === 0 && d.guess.kind ? 'btn-primary' : 'btn-outline') + '" ' +
            'style="margin-left:6px;" onclick="viewerSendTo(\'' + kind + '\')">' +
            'Import as ' + esc(t.label) + '</button>';
    }).join('');
}


function viewerMapping(d) {
    var keys = Object.keys(d.mapping || {});
    if (!keys.length) return '';
    return '<div style="font-size:0.78rem;color:var(--text-secondary);margin-bottom:10px;">' +
        '<strong>' + keys.length + ' column' + (keys.length === 1 ? '' : 's') +
        ' recognised:</strong> ' +
        keys.map(function (h) {
            return esc(h) + ' → ' + esc(d.mapping[h]);
        }).join(' · ') + '</div>';
}


function renderSheetViewer() {
    var d = VIEWER.data;
    var host = document.getElementById('viewer-body');
    if (!d || !host) return;

    if (!d.total_rows) {
        host.innerHTML = viewerTabs(d) +
            '<p style="text-align:center;padding:30px;color:var(--text-secondary);">' +
            'There is nothing under the headings on this sheet.</p>';
        return;
    }

    var fields = d.fields || [];
    var head = '<tr><th style="width:52px;">#</th>' + d.header.map(function (h, i) {
        // By position: this sheet may head two different columns the same way.
        var field = fields[i];
        return '<th>' + (esc(h) || '<span style="opacity:0.4;">col ' + (i + 1) + '</span>') +
            (field ? '<div style="font-weight:400;font-size:0.68rem;text-transform:none;' +
                'letter-spacing:0;color:var(--primary-color);">' + esc(field) + '</div>' : '') +
            '</th>';
    }).join('') + '</tr>';

    var rows = d.rows.map(function (r, i) {
        return '<tr><td style="color:var(--text-secondary);font-family:monospace;">' +
            (d.header_row + 1 + i) + '</td>' +
            r.map(function (c) {
                // One line per cell. These descriptions run to a paragraph
                // with newlines in them, and a grid is for scanning.
                var flat = String(c || '').replace(/\s+/g, ' ').trim();
                return '<td title="' + esc(flat) + '" style="max-width:220px;overflow:hidden;' +
                    'text-overflow:ellipsis;white-space:nowrap;">' + esc(flat) + '</td>';
            }).join('') + '</tr>';
    }).join('');

    host.innerHTML = viewerTabs(d) + viewerSummary(d) + viewerMapping(d) +
        '<div class="table-responsive" style="max-height:60vh;overflow:auto;">' +
        '<table class="data-table"><thead>' + head + '</thead><tbody>' + rows + '</tbody></table></div>' +
        (d.total_rows > d.rows.length
            ? '<p style="font-size:0.78rem;color:var(--text-secondary);margin-top:10px;">' +
              'Showing the first ' + d.rows.length + ' of ' + d.total_rows + ' rows' +
              (d.truncated_columns ? ', and the first ' + d.columns + ' columns' : '') +
              '. The whole sheet is read on import.</p>'
            : '');
}


function viewerSendTo(kind) {
    var target = VIEWER_TARGETS[kind];
    if (!target) return;
    // The file is handed over by taking the person to the screen that imports
    // it, rather than importing from here. That screen asks for the job or the
    // work order the sheet belongs to, and those are not questions a file
    // viewer should be answering on somebody's behalf.
    showView(target.view);
    showToast('Choose the file again on this screen to import it as a ' +
              target.label.toLowerCase() + '.', 'success');
}
window.viewerSendTo = viewerSendTo;
