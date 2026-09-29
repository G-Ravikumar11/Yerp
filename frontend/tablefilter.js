/* tablefilter.js - a search box, a status filter and a date range above
   every list in the app. It reads the rows as they are drawn, so any list -
   work orders, bills, RA bills, the MB, registers - can be narrowed without
   each screen building its own. Where a screen already has a search box of
   its own, only the status and date filters are added. */
(function () {
    var MON = { jan: 1, feb: 2, mar: 3, apr: 4, may: 5, jun: 6, jul: 7, aug: 8, sep: 9, oct: 10, nov: 11, dec: 12 };
    var DATE_RE = /\b(\d{4})-(\d{2})-(\d{2})\b|\b(\d{1,2})[-\/.](\d{1,2})[-\/.](\d{4})\b|\b(\d{1,2}) (jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*,? (\d{4})\b/i;
    var tables = [];

    function pad(n) { n = String(n); return n.length < 2 ? '0' + n : n; }

    function rowText(tr) {
        return Array.prototype.map.call(tr.cells, function (c) { return c.textContent; }).join(' ');
    }

    function rowDate(tr) {
        var m = DATE_RE.exec(rowText(tr));
        if (!m) return '';
        if (m[1]) return m[1] + '-' + m[2] + '-' + m[3];
        if (m[4]) return m[6] + '-' + pad(m[5]) + '-' + pad(m[4]);
        return m[9] + '-' + pad(MON[m[8].slice(0, 3).toLowerCase()]) + '-' + pad(m[7]);
    }

    function statusColumn(table) {
        var ths = table.querySelectorAll('thead th');
        for (var i = 0; i < ths.length; i++) if (/status/i.test(ths[i].textContent)) return i;
        return -1;
    }

    function rowStatus(tr, col) {
        var td = tr.cells[col];
        if (!td) return '';
        var pill = td.querySelector('span');
        return ((pill ? pill.textContent : td.textContent) || '').trim().split('\n')[0].trim();
    }

    function dataRows(tbody) {
        return Array.prototype.filter.call(tbody.rows, function (r) {
            return !(r.cells.length === 1 && r.cells[0].colSpan > 1);
        });
    }

    function isEditable(rows) {
        return rows.some(function (r) {
            return r.querySelector('input:not([type=checkbox]):not([type=radio]), select, textarea');
        });
    }

    function control(tag, attrs) {
        var el = document.createElement(tag);
        for (var k in attrs) el.setAttribute(k, attrs[k]);
        el.className = 'form-control';
        return el;
    }

    function attach(table) {
        if (table.getAttribute('data-tf') || !table.tBodies[0]) return;
        if (table.closest('.modal, .modal-overlay, [id$="-modal"], .tf-skip')) return;
        var view = table.closest('.view-section');
        if (!view) return;
        table.setAttribute('data-tf', '1');

        var ownSearch = view.querySelectorAll('table.data-table').length === 1 &&
            !!view.querySelector('input[id*="search"], input[id$="-q"]');
        var bar = document.createElement('div');
        bar.className = 'tf-bar';
        bar.style.display = 'none';

        var q = null;
        if (!ownSearch) {
            q = control('input', { type: 'search', placeholder: 'Search this list...', 'aria-label': 'Search this list' });
            q.style.flex = '2 1 220px';
            bar.appendChild(q);
        }
        var status = control('select', { 'aria-label': 'Filter by status' });
        status.style.flex = '1 1 150px';
        var from = control('input', { type: 'date', title: 'From date', 'aria-label': 'From date' });
        var to = control('input', { type: 'date', title: 'To date', 'aria-label': 'To date' });
        from.style.flex = to.style.flex = '1 1 140px';
        var dates = document.createElement('span');
        dates.className = 'tf-dates';
        dates.appendChild(from);
        dates.appendChild(document.createTextNode(' to '));
        dates.appendChild(to);
        var clear = document.createElement('button');
        clear.type = 'button';
        clear.className = 'btn btn-sm btn-outline';
        clear.textContent = 'Clear';
        var count = document.createElement('span');
        count.className = 'tf-count';
        bar.appendChild(status);
        bar.appendChild(dates);
        bar.appendChild(clear);
        bar.appendChild(count);

        var anchor = table.closest('.table-responsive') || table;
        anchor.parentNode.insertBefore(bar, anchor);

        var t = { table: table, bar: bar, q: q, status: status, from: from, to: to, dates: dates, count: count, sig: '' };
        [q, status, from, to].forEach(function (el) {
            if (el) el.addEventListener(el.tagName === 'SELECT' || el.type === 'date' ? 'change' : 'input', function () { apply(t); });
        });
        clear.addEventListener('click', function () {
            if (q) q.value = '';
            status.value = from.value = to.value = '';
            apply(t);
        });
        tables.push(t);
        refresh(t);
    }

    function active(t) {
        return !!((t.q && t.q.value.trim()) || t.status.value || t.from.value || t.to.value);
    }

    function refresh(t) {
        var tbody = t.table.tBodies[0];
        var rows = dataRows(tbody);
        var col = statusColumn(t.table);
        var editable = isEditable(rows);
        t.bar.style.display = !editable && (rows.length >= 1 || active(t)) ? '' : 'none';
        if (editable) return;

        var seen = {};
        if (col >= 0) rows.forEach(function (r) { var s = rowStatus(r, col); if (s) seen[s] = 1; });
        var names = Object.keys(seen).sort();
        var sig = names.join('|');
        if (sig !== t.sig) {
            var keep = t.status.value;
            t.status.innerHTML = '';
            t.status.appendChild(new Option('All statuses', ''));
            names.forEach(function (n) { t.status.appendChild(new Option(n, n)); });
            t.status.value = names.indexOf(keep) >= 0 ? keep : '';
            t.sig = sig;
        }
        var hasStatus = names.length > 0, hasDates = rows.some(function (r) { return rowDate(r); });
        t.status.style.display = hasStatus ? '' : 'none';
        t.dates.style.display = hasDates ? '' : 'none';
        if (!t.q && !hasStatus && !hasDates && !active(t)) t.bar.style.display = 'none';
        apply(t);
    }

    function apply(t) {
        var rows = dataRows(t.table.tBodies[0]);
        var col = statusColumn(t.table);
        var words = t.q ? t.q.value.toLowerCase().split(/\s+/).filter(Boolean) : [];
        var st = t.status.value, from = t.from.value, to = t.to.value;
        var shown = 0;
        rows.forEach(function (r) {
            var ok = true;
            if (words.length) {
                var text = rowText(r).toLowerCase();
                var hay = text + ' ' + text.replace(/,/g, '');
                ok = words.every(function (w) { return hay.indexOf(w) >= 0; });
            }
            if (ok && st && col >= 0) ok = rowStatus(r, col) === st;
            if (ok && (from || to)) {
                var d = rowDate(r);
                ok = !!d && (!from || d >= from) && (!to || d <= to);
            }
            r.style.display = ok ? '' : 'none';
            if (ok) shown++;
        });
        t.count.textContent = active(t) ? (shown ? shown + ' of ' + rows.length : 'Nothing matches') : rows.length + ' in the list';
    }

    function scan() {
        tables = tables.filter(function (t) { return document.body.contains(t.table); });
        document.querySelectorAll('table.data-table').forEach(attach);
        tables.forEach(refresh);
    }

    var timer = null;
    function later() { clearTimeout(timer); timer = setTimeout(scan, 150); }

    function start() {
        scan();
        new MutationObserver(function (list) {
            for (var i = 0; i < list.length; i++) {
                var n = list[i].target;
                if (!(n.closest && n.closest('.tf-bar'))) { later(); return; }
            }
        }).observe(document.body, { childList: true, subtree: true });
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
    else start();
})();
