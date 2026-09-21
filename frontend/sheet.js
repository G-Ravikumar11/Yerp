/* ===========================================================================
   sheet.js - every table does what a sheet was being opened for.

   The three things somebody downloads a list to a spreadsheet to do: sort it,
   filter it, total a column. So every table in the app does them itself -
   click a heading to sort, type to filter, and the totals of the money
   columns sit under what is on the screen. Nothing to configure per screen:
   it watches for tables as they are drawn.

   Grids that are being typed into (the schedule, the item sheet) are left
   alone: sorting a row of inputs would shuffle somebody's work.
   =========================================================================== */

(function () {
    var MIN_ROWS = 6;

    function cellNumber(text) {
        /* "₹12,34,567.50" -> 1234567.5; "(68,600.00)" -> -68600; "18%" -> 18.
           Anything else is not a number. */
        var t = String(text || '').replace(/[₹,\s%]/g, '');
        if (!t) return null;
        var neg = /^\(.*\)$/.test(t) || /^[−-]/.test(t);
        t = t.replace(/[()−-]/g, '');
        if (!/^\d*\.?\d+$/.test(t)) return null;
        var n = parseFloat(t);
        return neg ? -n : n;
    }

    function cellText(td) {
        // The first line of a cell is what it is; the small print under it is
        // not what anybody sorts on.
        var first = td.childNodes[0];
        var t = (first && first.nodeType === 3 ? first.textContent : td.textContent) || '';
        return t.trim();
    }

    function editable(table) {
        return !!table.querySelector('tbody input, tbody select, tbody textarea');
    }

    function rowsOf(table) {
        var tb = table.tBodies[0];
        return tb ? Array.prototype.slice.call(tb.rows) : [];
    }

    function dataRows(table) {
        // A one-cell row is a message ("Nothing yet"), not data.
        return rowsOf(table).filter(function (r) { return r.cells.length > 1; });
    }

    /* --- Sort ------------------------------------------------------------- */

    document.addEventListener('click', function (e) {
        var th = e.target.closest ? e.target.closest('table.data-table thead th') : null;
        if (!th || th.querySelector('input,button,select')) return;
        var table = th.closest('table');
        if (editable(table)) return;
        var rows = dataRows(table);
        if (rows.length < 2) return;
        var idx = Array.prototype.indexOf.call(th.parentNode.children, th);
        var dir = th.getAttribute('data-sort') === 'asc' ? 'desc' : 'asc';
        Array.prototype.forEach.call(th.parentNode.children, function (h) {
            h.removeAttribute('data-sort');
            h.textContent = h.textContent.replace(/\s[▲▼]$/, '');
        });
        th.setAttribute('data-sort', dir);
        th.textContent = th.textContent + (dir === 'asc' ? ' ▲' : ' ▼');

        var keyed = rows.map(function (r) {
            var td = r.cells[idx];
            var text = td ? cellText(td) : '';
            var n = cellNumber(text);
            return { r: r, n: n, t: text.toLowerCase() };
        });
        var numeric = keyed.every(function (k) { return k.n !== null || k.t === '' || k.t === '—'; });
        keyed.sort(function (a, b) {
            var c;
            if (numeric) c = (a.n === null ? -Infinity : a.n) - (b.n === null ? -Infinity : b.n);
            else c = a.t < b.t ? -1 : a.t > b.t ? 1 : 0;
            return dir === 'asc' ? c : -c;
        });
        var tb = table.tBodies[0];
        keyed.forEach(function (k) { tb.appendChild(k.r); });
        // Anything that was a message row goes back to the bottom.
        rowsOf(table).filter(function (r) { return r.cells.length <= 1; }).forEach(function (r) { tb.appendChild(r); });
        refreshTotals(table);
    });

    /* --- Filter and totals ----------------------------------------------- */

    function barFor(table) {
        var wrap = table.closest('.table-responsive') || table.parentElement;
        if (!wrap) return null;
        var bar = wrap.previousElementSibling;
        if (bar && bar.classList && bar.classList.contains('sheet-bar')) return bar;
        bar = document.createElement('div');
        bar.className = 'sheet-bar no-print';
        bar.innerHTML = '<input class="form-control sheet-filter" placeholder="Filter these rows" ' +
            'style="max-width:260px;font-size:0.8rem;padding:5px 9px;">' +
            '<span class="sheet-count" style="font-size:0.74rem;color:var(--text-secondary);"></span>' +
            '<label style="font-size:0.74rem;color:var(--text-secondary);display:flex;align-items:center;gap:5px;cursor:pointer;margin-left:auto;">' +
            '<input type="checkbox" class="sheet-totals-toggle"> Totals</label>';
        wrap.parentNode.insertBefore(bar, wrap);
        bar.querySelector('.sheet-filter').addEventListener('input', function () { applyFilter(table); });
        bar.querySelector('.sheet-totals-toggle').addEventListener('change', function () { refreshTotals(table); });
        return bar;
    }

    function applyFilter(table) {
        var bar = barFor(table);
        if (!bar) return;
        var q = bar.querySelector('.sheet-filter').value.trim().toLowerCase();
        var rows = dataRows(table), shown = 0;
        rows.forEach(function (r) {
            var hit = !q || r.textContent.toLowerCase().indexOf(q) >= 0;
            r.style.display = hit ? '' : 'none';
            if (hit) shown++;
        });
        // Written only when it changes: the observer that draws these bars
        // would otherwise see its own writing and draw them again, for ever.
        var count = bar.querySelector('.sheet-count');
        var label = q ? shown + ' of ' + rows.length + ' rows' : rows.length + ' rows';
        if (count.textContent !== label) count.textContent = label;
        refreshTotals(table);
    }

    function totalable(head) {
        /* A column is summed when its heading says it holds a quantity of
           something. An HSN code, a phone number or a serial is digits too,
           and a total of those is a number that means nothing. */
        var h = String(head || '').toLowerCase();
        if (!h || /code|hsn|no\.|number|#|date|phone|gstin|pan|year|ref|sac|%|rate|status|by/.test(h)) return false;
        return /₹|amount|value|total|qty|quantity|measured|billed|balance|hours|days|mandays|weight|cost|net|gross|due|paid|held|claimed|advance|retention|tax|gst|tds|cess|stock|issued|received|accepted|rejected|ordered|unbilled|items|lines|entries|count|bills|orders/.test(h);
    }

    function refreshTotals(table) {
        var bar = barFor(table);
        var old = table.querySelector('tfoot.sheet-totals');
        var wanted = bar && bar.querySelector('.sheet-totals-toggle').checked;
        if (!wanted) { if (old) old.parentNode.removeChild(old); return; }
        if (old) old.parentNode.removeChild(old);
        var rows = dataRows(table).filter(function (r) { return r.style.display !== 'none'; });
        if (!rows.length) return;
        var cols = rows[0].cells.length;
        var heads = table.tHead && table.tHead.rows[0] ? Array.prototype.map.call(
            table.tHead.rows[0].cells, function (h) { return h.textContent.replace(/\s[▲▼]$/, '').trim(); }) : [];
        var sums = [], counts = [];
        for (var c = 0; c < cols; c++) { sums[c] = 0; counts[c] = 0; }
        rows.forEach(function (r) {
            for (var c = 0; c < cols; c++) {
                var td = r.cells[c];
                if (!td || !totalable(heads[c])) continue;
                var text = cellText(td);
                if (/%$/.test(text)) continue;                      // a rate is not summed
                var n = cellNumber(text);
                if (n !== null) { sums[c] += n; counts[c]++; }
            }
        });
        var foot = document.createElement('tfoot');
        foot.className = 'sheet-totals';
        var tr = document.createElement('tr');
        for (var i = 0; i < cols; i++) {
            var td = document.createElement('td');
            td.style.fontWeight = '700';
            td.style.borderTop = '2px solid var(--border-color)';
            if (counts[i] >= Math.max(2, rows.length * 0.6)) {
                var head = rows[0].cells[i];
                var money = /₹/.test(head ? head.textContent : '');
                td.textContent = money ? formatCurrency(sums[i])
                    : sums[i].toLocaleString('en-IN', { maximumFractionDigits: 3 });
                td.className = 'text-right';
                td.style.whiteSpace = 'nowrap';
            } else if (i === 0) {
                td.textContent = 'Total of ' + rows.length + ' row' + (rows.length === 1 ? '' : 's');
                td.style.fontSize = '0.74rem';
                td.style.color = 'var(--text-secondary)';
            }
            tr.appendChild(td);
        }
        foot.appendChild(tr);
        table.appendChild(foot);
    }

    function attach() {
        var tables = document.querySelectorAll('table.data-table');
        Array.prototype.forEach.call(tables, function (table) {
            if (editable(table)) return;
            if (table.closest('#document-view, .wo-sheet, .modal')) return;
            var rows = dataRows(table);
            var bar = (table.closest('.table-responsive') || table.parentElement || {}).previousElementSibling;
            var has = bar && bar.classList && bar.classList.contains('sheet-bar');
            if (rows.length < MIN_ROWS) {
                if (has) bar.style.display = 'none';
                return;
            }
            bar = barFor(table);
            if (bar) { bar.style.display = ''; applyFilter(table); }
        });
    }

    // Tables are drawn and redrawn by every screen; watch for them rather
    // than asking every screen to say so. Debounced with a timer, not a
    // frame, because a background tab never gets a frame.
    var pending = null;
    function schedule() {
        if (pending) return;
        pending = setTimeout(function () { pending = null; attach(); }, 120);
    }
    if (window.MutationObserver) {
        new MutationObserver(schedule).observe(document.body, { childList: true, subtree: true });
    }
    document.addEventListener('DOMContentLoaded', schedule);
    schedule();
})();
