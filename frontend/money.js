/* ===========================================================================
   money.js - who owes what today, and the retention nobody chases.

   Ageing keeps "not due" apart from "0-30" on purpose: money that is not late
   yet is not a problem, and mixing the two makes a healthy ledger read like a
   chase list.
   =========================================================================== */

var BUCKETS = ['Not due', '0-30', '31-60', '61-90', '90+'];

function bucketStrip(buckets, total) {
    // Not due is neutral; everything after it gets warmer as it gets older.
    var tone = { 'Not due': 'var(--text-secondary)', '0-30': 'var(--primary-color)',
                 '31-60': 'var(--warning-color)', '61-90': 'var(--warning-color)',
                 '90+': 'var(--danger-color)' };
    return '<div style="display:grid;gap:10px;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));">' +
        BUCKETS.map(function (b) {
            var v = buckets[b] || 0;
            var pc = total ? Math.round(v / total * 100) : 0;
            return '<div style="padding:10px 12px;border:1px solid var(--border-color);' +
                'border-radius:var(--radius-md);border-top:3px solid ' + tone[b] + ';">' +
                '<div style="font-size:0.72rem;color:var(--text-secondary);">' + b +
                (b === 'Not due' ? '' : ' days') + '</div>' +
                '<div style="font-weight:700;font-size:0.95rem;margin-top:2px;">' +
                formatCurrency(v) + '</div>' +
                '<div style="font-size:0.7rem;color:var(--text-secondary);">' + pc + '%</div>' +
                '</div>';
        }).join('') + '</div>';
}

function agePill(row) {
    if (row.bucket === 'Not due') return statusPill('not due', 'calm');
    return statusPill(row.days_overdue + ' days late',
                      row.days_overdue > 60 ? 'bad' : 'wait');
}

async function loadMoney() {
    await Promise.all([loadReceivables(), loadPayables(), loadRetention()]);
}
window.loadMoney = loadMoney;

async function loadReceivables() {
    var body = document.getElementById('recv-body');
    if (!body) return;
    var d = await (await fetch('/api/money/receivables',
                               { credentials: 'include' })).json();
    var s = d.summary || {};
    document.getElementById('recv-stats').innerHTML =
        statCard('Owed to us', formatCurrency(s.owed || 0)) +
        statCard('Past due', formatCurrency(s.overdue || 0)) +
        statCard('Over 90 days', formatCurrency(s.over_90 || 0)) +
        statCard('Worst debt', (s.worst_days || 0) + ' days');
    document.getElementById('recv-buckets').innerHTML =
        bucketStrip(d.buckets || {}, s.owed || 0);

    body.innerHTML = (d.invoices || []).length ? d.invoices.map(function (r) {
        return '<tr>' +
            '<td style="font-family:monospace;font-weight:600;">' + esc(r.number) + '</td>' +
            '<td>' + esc(r.customer || '—') +
                (r.project ? '<div style="font-size:0.75rem;color:var(--text-secondary);">' +
                 esc(r.project) + '</div>' : '') + '</td>' +
            '<td>' + esc(r.due_date || '—') + '</td>' +
            '<td class="text-right">' + formatCurrency(r.total) + '</td>' +
            '<td class="text-right">' + formatCurrency(r.paid) + '</td>' +
            '<td class="text-right" style="font-weight:700;">' +
                formatCurrency(r.outstanding) + '</td>' +
            '<td>' + agePill(r) +
                (r.doc_type ? ' <button class="btn btn-sm btn-outline" onclick="openPayBox(\'' + r.doc_type +
                    '\',' + r.id + ',loadMoney)">Receive</button>' : '') + '</td></tr>';
    }).join('') : '<tr><td colspan="7" style="text-align:center;padding:26px;' +
        'color:var(--text-secondary);">Nobody owes anything. Nothing to chase.</td></tr>';
}

async function loadPayables() {
    var body = document.getElementById('pay-body');
    if (!body) return;
    var d = await (await fetch('/api/money/payables',
                               { credentials: 'include' })).json();
    var s = d.summary || {};
    document.getElementById('pay-stats').innerHTML =
        statCard('We owe', formatCurrency(s.owed || 0)) +
        statCard('Past due', formatCurrency(s.overdue || 0)) +
        statCard('Waiting on approval', formatCurrency(s.awaiting_approval || 0)) +
        statCard('Over 90 days', formatCurrency(s.over_90 || 0));
    document.getElementById('pay-buckets').innerHTML =
        bucketStrip(d.buckets || {}, s.owed || 0);

    body.innerHTML = (d.bills || []).length ? d.bills.map(function (r) {
        return '<tr>' +
            '<td style="font-family:monospace;font-weight:600;">' + esc(r.number) +
                '<div style="font-size:0.72rem;font-family:inherit;font-weight:400;' +
                'color:var(--text-secondary);">' + esc(r.kind) + '</div></td>' +
            '<td>' + esc(r.party || '—') +
                (r.project ? '<div style="font-size:0.75rem;color:var(--text-secondary);">' +
                 esc(r.project) + '</div>' : '') + '</td>' +
            '<td>' + esc(r.due_date || '—') + '</td>' +
            '<td class="text-right" style="font-weight:700;">' +
                formatCurrency(r.outstanding) + '</td>' +
            '<td>' + (r.approved ? statusPill('approved', 'good')
                                 : statusPill('not approved', 'wait')) + '</td>' +
            '<td>' + agePill(r) +
                (r.doc_type && r.approved !== false ? ' <button class="btn btn-sm btn-outline" onclick="openPayBox(\'' + r.doc_type +
                    '\',' + r.id + ',loadMoney)">Pay</button>' : '') + '</td></tr>';
    }).join('') : '<tr><td colspan="6" style="text-align:center;padding:26px;' +
        'color:var(--text-secondary);">Nothing outstanding.</td></tr>';
}

async function loadRetention() {
    var body = document.getElementById('ret-body');
    if (!body) return;
    var d = await (await fetch('/api/money/retention',
                               { credentials: 'include' })).json();
    var s = d.summary || {};
    document.getElementById('ret-stats').innerHTML =
        statCard('Retention held', formatCurrency(s.held || 0)) +
        statCard('On finished jobs', formatCurrency(s.on_finished_jobs || 0)) +
        statCard('Projects', String(s.projects || 0)) +
        statCard('Across bills', String(s.bills || 0));

    body.innerHTML = (d.projects || []).length ? d.projects.map(function (r) {
        return '<tr>' +
            '<td style="font-weight:600;">' + esc(r.number || '') + ' ' + esc(r.project) +
                '<div style="font-size:0.75rem;font-weight:400;color:var(--text-secondary);">' +
                esc(r.customer || '') + '</div></td>' +
            '<td class="text-right">' + formatCurrency(r.claimed_value) + '</td>' +
            '<td class="text-right" style="font-weight:700;">' +
                formatCurrency(r.held) + '</td>' +
            '<td class="text-right">' + r.effective_percent + '%</td>' +
            '<td class="text-right">' + r.bills.length + '</td>' +
            '<td>' + (r.releasable
                ? statusPill('job finished — chase it', 'bad')
                : statusPill(r.job_status || 'running', 'calm')) + '</td></tr>';
    }).join('') : '<tr><td colspan="6" style="text-align:center;padding:26px;' +
        'color:var(--text-secondary);">Nothing held back yet. Retention appears ' +
        'once a bill is certified.</td></tr>';
}

/* --- What needs a look today ---------------------------------------------- */

var SEVERITY = {
    money:  { tone: 'var(--danger-color)',  label: 'money' },
    wrong:  { tone: 'var(--danger-color)',  label: 'looks wrong' },
    action: { tone: 'var(--warning-color)', label: 'needs a decision' },
    notice: { tone: 'var(--text-secondary)', label: 'when you get a minute' },
};

async function loadAttention() {
    var box = document.getElementById('attention-list');
    if (!box) return;
    var d = await (await fetch('/api/attention', { credentials: 'include' })).json();
    var s = d.summary || {};
    var stats = document.getElementById('attention-stats');
    if (stats) stats.innerHTML =
        statCard('Money at stake', formatCurrency(s.money_at_stake || 0)) +
        statCard('Waiting on a decision', String(s.needs_a_decision || 0)) +
        statCard('Looks wrong', String(s.looks_wrong || 0)) +
        statCard('Things to look at', String(s.items || 0));

    // A business that has not finished setting itself up gets the steps, in
    // order, with the next one to take. "Nothing needs chasing" was true of an
    // empty account in the way an empty ledger balances, and it left a new
    // owner with no idea where to begin.
    var setup = d.setup || {};
    var setupHtml = '';
    if (setup.steps && !setup.complete) {
        setupHtml = '<div class="widget" style="margin-bottom:18px;">' +
            '<div class="widget-header" style="display:flex;justify-content:space-between;align-items:center;">' +
            '<h3>Getting set up</h3><span style="font-size:0.85rem;color:var(--text-secondary);">' +
            setup.done + ' of ' + setup.of + ' done</span></div>' +
            '<div class="widget-content" style="padding:6px 0;">' +
            setup.steps.map(function (st) {
                var isNext = setup.next && setup.next.key === st.key;
                return '<div onclick="showView(&quot;' + st.view + '&quot;)" style="display:flex;gap:14px;' +
                    'align-items:flex-start;padding:12px 20px;cursor:pointer;' +
                    'border-bottom:1px solid var(--border-color);' +
                    (isNext ? 'background:var(--primary-soft);' : '') +
                    (st.done ? 'opacity:.6;' : '') + '">' +
                    '<div style="width:22px;height:22px;border-radius:50%;flex-shrink:0;display:flex;' +
                    'align-items:center;justify-content:center;font-size:0.75rem;font-weight:700;' +
                    (st.done ? 'background:var(--success-color);color:#fff;' :
                     isNext ? 'background:var(--primary-color);color:#fff;' :
                     'border:2px solid var(--border-color);color:var(--text-secondary);') + '">' +
                    (st.done ? '✓' : '') + '</div>' +
                    '<div><div style="font-weight:600;font-size:0.9rem;">' + esc(st.title) +
                    (isNext ? ' <span style="font-size:0.72rem;font-weight:500;color:var(--primary-color);">' +
                     '← start here</span>' : '') + '</div>' +
                    '<div style="font-size:0.8rem;color:var(--text-secondary);margin-top:2px;">' +
                    esc(st.hint) + '</div></div></div>';
            }).join('') + '</div></div>';
    }

    if (!(d.items || []).length) {
        box.innerHTML = setupHtml + (setup.complete
            ? '<div class="widget"><div class="widget-content" ' +
              'style="padding:28px;text-align:center;color:var(--text-secondary);">' +
              'Nothing needs chasing. Everything measured has been billed, every ' +
              'bill has been signed, and the store agrees with itself.</div></div>'
            : '');
        return;
    }
    box.innerHTML = setupHtml;
    box.innerHTML += '<div class="widget"><div class="widget-header">' +
        '<h3>What is worth a look today</h3></div><div class="widget-content" ' +
        'style="padding:6px 0;">' +
        d.items.map(function (i) {
            var sev = SEVERITY[i.severity] || SEVERITY.notice;
            return '<div onclick="showView(\'' + i.view + '\')" ' +
                'style="display:flex;gap:14px;align-items:flex-start;padding:14px 20px;' +
                'border-left:3px solid ' + sev.tone + ';cursor:pointer;' +
                'border-bottom:1px solid var(--border-color);">' +
                '<div style="flex:1;min-width:0;">' +
                '<div style="font-weight:600;font-size:0.92rem;">' + esc(i.title) + '</div>' +
                '<div style="font-size:0.82rem;color:var(--text-secondary);margin-top:2px;">' +
                esc(i.detail) + '</div></div>' +
                (i.value ? '<div style="font-weight:700;white-space:nowrap;color:' +
                 sev.tone + ';">' + formatCurrency(i.value) + '</div>' : '') +
                '</div>';
        }).join('') + '</div></div>';
}
window.loadAttention = loadAttention;


/* --- The dashboard's own figures ------------------------------------------
   What the owner opens the app to see, once the attention panel has said
   what needs a decision: the money both ways, the projects by margin, and
   the store running low. Every number is a link to the screen it came from.
   ------------------------------------------------------------------------ */

async function dashErp() {
    var host = document.getElementById('dash-erp');
    if (!host) return;
    var get = function (url) {
        return fetch(url, { credentials: 'include' }).then(function (r) { return r.ok ? r.json() : {}; })
            .catch(function () { return {}; });
    };
    var out = await Promise.all([get('/api/money/receivables'), get('/api/money/payables'),
                                 get('/api/money/retention'), get('/api/jobs-pnl'),
                                 get('/api/stock?low_only=true')]);
    var rec = out[0].summary || {}, pay = out[1].summary || {}, ret = out[2].summary || {};
    var pnl = out[3], stock = out[4].summary || {};

    var tile = function (label, value, sub, view, tone) {
        return '<button type="button" class="stat-card" style="text-align:left;cursor:pointer;" ' +
            'onclick="showView(\'' + view + '\')">' +
            '<span class="stat-label">' + esc(label) + '</span>' +
            '<span class="stat-value"' + (tone ? ' style="color:var(--' + tone + '-color);"' : '') + '>' + value + '</span>' +
            (sub ? '<span style="display:block;font-size:0.72rem;color:var(--text-secondary);margin-top:2px;">' + sub + '</span>' : '') +
            '</button>';
    };

    var projects = (pnl.projects || []).slice(0, 6);
    var rows = projects.map(function (p) {
        var bad = (p.margin || 0) < 0;
        return '<tr><td><a href="#" onclick="event.preventDefault();showView(\'pnl-view\')" style="font-weight:600;">' +
            esc(p.number + ' ' + p.name) + '</a>' +
            '<div style="font-size:0.72rem;color:var(--text-secondary);">' + esc(p.customer_name || '') + '</div></td>' +
            '<td class="text-right">' + formatCurrency(p.revenue) + '</td>' +
            '<td class="text-right">' + formatCurrency(p.incurred) + '</td>' +
            '<td class="text-right" style="font-weight:700;' + (bad ? 'color:var(--danger-color);' : '') + '">' +
                formatCurrency(p.margin) + '<div style="font-size:0.7rem;font-weight:400;">' + (p.margin_percent || 0) + '%</div></td></tr>';
    }).join('');

    host.innerHTML =
        '<h3 style="font-size:0.95rem;margin:18px 0 10px;">Money, both ways</h3>' +
        '<div class="grid-4 mb-24">' +
        tile('Owed to us', formatCurrency(rec.owed || 0), (rec.overdue ? formatCurrency(rec.overdue) + ' overdue' : 'nothing overdue'), 'money-view', rec.overdue ? 'warning' : '') +
        tile('We owe', formatCurrency(pay.owed || 0), (pay.overdue ? formatCurrency(pay.overdue) + ' overdue' : 'nothing overdue'), 'money-view', pay.overdue ? 'danger' : '') +
        tile('Retention held on us', formatCurrency(ret.held || 0), (ret.on_finished_jobs ? formatCurrency(ret.on_finished_jobs) + ' on finished jobs' : ''), 'money-view') +
        tile('Store below reorder', String(stock.below_reorder || 0) + ' item' + (stock.below_reorder === 1 ? '' : 's'),
             (stock.value_on_hand ? formatCurrency(stock.value_on_hand) + ' on hand' : ''), 'stock-view', stock.below_reorder ? 'warning' : '') +
        '</div>' +
        '<div class="widget" style="margin-bottom:24px;"><div class="widget-header"><h3>Projects, worst margin first</h3>' +
        '<button class="btn btn-sm btn-outline" onclick="showView(\'pnl-view\')">All projects</button></div>' +
        '<div class="table-responsive"><table class="data-table">' +
        '<thead><tr><th>Project</th><th class="text-right">Revenue</th><th class="text-right">Cost</th><th class="text-right">Margin</th></tr></thead>' +
        '<tbody>' + (rows || '<tr><td colspan="4" style="text-align:center;padding:20px;color:var(--text-secondary);">No live projects yet.</td></tr>') +
        '</tbody></table></div></div>';
}
window.dashErp = dashErp;
