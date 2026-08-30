/* ===========================================================================
   costs.js - where the money is, per project.

   Every figure here already existed somewhere: a work order on one screen, a
   purchase order on another, bills on a third. What nobody could do was see
   them on one line and answer the only question a running job asks - are we
   still making money on it.

   Sold is what the work orders promise. Cost is what has actually been
   committed to somebody, which is not the same as the budget: the budget is
   the estimate, and the commitments are the promises.
   =========================================================================== */

var COSTS = { rows: [], summary: {} };

/* How far through, by cost. The only progress measure available to a contract
   with no milestone schedule, and better than none. */
function progressBar(percent) {
    var pc = Math.max(0, Math.min(100, percent || 0));
    return '<div style="min-width:70px;">' +
        '<div style="height:6px;background:var(--border-color,#e2e8f0);border-radius:3px;overflow:hidden;">' +
        '<div style="width:' + pc + '%;height:100%;background:var(--primary-color);"></div></div>' +
        '<div style="font-size:0.72rem;color:var(--text-secondary);margin-top:2px;">' +
        pc + '%</div></div>';
}

async function loadCosts() {
    var body = document.getElementById('costs-body');
    if (!body) return;
    body.innerHTML = '<tr><td colspan="10" style="text-align:center;padding:30px;' +
        'color:var(--text-secondary);">Working out where the money is...</td></tr>';
    var data;
    try {
        data = await (await fetch('/api/costs/by-project', { credentials: 'include' })).json();
    } catch (e) {
        body.innerHTML = '<tr><td colspan="10" style="text-align:center;padding:30px;' +
            'color:var(--text-secondary);">Could not load the figures.</td></tr>';
        return;
    }
    COSTS.rows = data.projects || [];
    COSTS.summary = data.summary || {};
    renderCostStats();
    renderCosts();
}
window.loadCosts = loadCosts;

function renderCostStats() {
    var host = document.getElementById('costs-stats');
    if (!host) return;
    var s = COSTS.summary;
    // Incurred and committed are kept apart on purpose: one is money already
    // owed, the other money promised, and a business that cannot see the gap
    // between them finds out about it when the invoices arrive.
    host.innerHTML =
        statCard('Sold', formatCurrency(s.sold || 0)) +
        statCard('Incurred', formatCurrency(s.incurred || 0)) +
        statCard('Committed', formatCurrency(s.commitment || 0)) +
        statCard('Forecast cost', formatCurrency(s.forecast_cost || 0)) +
        statCard('Forecast margin', formatCurrency(s.margin || 0)) +
        statCard('Retention held', formatCurrency(s.retention_held || 0)) +
        statCard('Owed to us', formatCurrency(s.outstanding || 0)) +
        statCard('Over budget', (s.over_budget || 0) + ' project(s)');
    renderCostMix(s.categories || []);
}

/* Where the money went, by heading. A single cost total says a job is losing
   money; the split says whether it was bought badly or built slowly. */
function renderCostMix(categories) {
    var host = document.getElementById('costs-mix');
    if (!host) return;
    var total = categories.reduce(function (t, c) { return t + (c.amount || 0); }, 0);
    if (!total) { host.innerHTML = ''; return; }

    var colours = { labour: '#4f46e5', materials: '#0ea5e9', subcontract: '#f59e0b',
                    plant: '#8b5cf6', other: '#94a3b8' };
    host.innerHTML =
        '<div style="display:flex;height:12px;border-radius:6px;overflow:hidden;margin-bottom:12px;">' +
        categories.filter(function (c) { return c.amount > 0; }).map(function (c) {
            return '<div title="' + esc(c.label) + '" style="width:' +
                (c.amount / total * 100) + '%;background:' + (colours[c.key] || '#94a3b8') + ';"></div>';
        }).join('') + '</div>' +
        '<div style="display:flex;flex-wrap:wrap;gap:16px;">' +
        categories.map(function (c) {
            return '<div style="font-size:0.8rem;">' +
                '<span style="display:inline-block;width:9px;height:9px;border-radius:2px;' +
                'background:' + (colours[c.key] || '#94a3b8') + ';margin-right:6px;"></span>' +
                esc(c.label) + ' <strong>' + formatCurrency(c.amount) + '</strong> ' +
                '<span style="color:var(--text-secondary);">' +
                Math.round(c.amount / total * 100) + '%</span></div>';
        }).join('') + '</div>';
}

function renderCosts() {
    var body = document.getElementById('costs-body');
    if (!body) return;
    if (!COSTS.rows.length) {
        body.innerHTML = '<tr><td colspan="10" style="text-align:center;padding:30px;' +
            'color:var(--text-secondary);">No projects yet. Raise a job, then the orders ' +
            'and bills against it, and the money appears here on its own.</td></tr>';
        return;
    }
    body.innerHTML = COSTS.rows.map(function (r) {
        // A margin that has gone negative is the whole reason to look at this
        // screen, so it is coloured rather than left as one number among many.
        var tone = r.margin < 0 ? 'var(--danger-color)'
                 : r.margin > 0 ? 'var(--success-color)' : 'var(--text-secondary)';
        return '<tr>' +
            '<td><a href="#" onclick="event.preventDefault();openProjectCosts(' + r.job_id + ')">' +
                '<strong>' + esc(r.number) + '</strong></a>' +
                '<div style="font-size:0.75rem;color:var(--text-secondary);">' +
                esc(r.name) + '</div></td>' +
            '<td>' + esc(r.customer_name || '—') + '</td>' +
            '<td class="text-right">' + formatCurrency(r.contract_value) + '</td>' +
            '<td class="text-right">' + progressBar(r.percent_complete) + '</td>' +
            '<td class="text-right">' + formatCurrency(r.incurred) +
                (r.commitment
                    ? '<div style="font-size:0.72rem;color:var(--text-secondary);">+ ' +
                      formatCurrency(r.commitment) + ' committed</div>' : '') + '</td>' +
            '<td class="text-right">' + formatCurrency(r.forecast_cost) +
                (r.over_budget > 0
                    ? '<div style="font-size:0.72rem;color:var(--danger-color);">' +
                      formatCurrency(r.over_budget) + ' over estimate</div>' : '') + '</td>' +
            '<td class="text-right" style="color:' + tone + ';font-weight:600;">' +
                formatCurrency(r.margin) +
                '<div style="font-size:0.72rem;font-weight:400;color:var(--text-secondary);">' +
                r.margin_percent + '%</div></td>' +
            '<td class="text-right">' + formatCurrency(r.invoiced) +
                (Math.abs(r.over_billed) >= 1
                    ? '<div style="font-size:0.72rem;color:' +
                      (r.over_billed > 0 ? 'var(--warning-color)' : 'var(--text-secondary)') + ';">' +
                      (r.over_billed > 0 ? 'ahead by ' : 'behind by ') +
                      formatCurrency(Math.abs(r.over_billed)) + '</div>' : '') + '</td>' +
            '<td class="text-right">' + (r.unpaid
                ? '<span style="color:var(--warning-color);font-weight:600;">' +
                  formatCurrency(r.unpaid) + '</span>' : '—') +
                (r.bills_awaiting_approval
                    ? '<div style="font-size:0.72rem;color:var(--text-secondary);">' +
                      r.bills_awaiting_approval + ' awaiting approval</div>' : '') + '</td>' +
            '<td class="text-right"><button class="btn btn-sm btn-outline" ' +
                'onclick="openProjectCosts(' + r.job_id + ')">Open</button></td>' +
            '</tr>';
    }).join('');
}

/* --- One project, and the papers behind each figure ---------------------- */

async function openProjectCosts(jobId) {
    showView('project-costs-view');
    var host = document.getElementById('project-costs');
    if (!host) return;
    host.innerHTML = '<p style="padding:30px;text-align:center;color:var(--text-secondary);">Loading...</p>';
    var res = await fetch('/api/costs/by-project/' + jobId, { credentials: 'include' });
    if (!res.ok) {
        host.innerHTML = '<p style="padding:30px;text-align:center;color:var(--text-secondary);">' +
            'Could not load that project.</p>';
        return;
    }
    renderProjectCosts(await res.json());
}
window.openProjectCosts = openProjectCosts;

function figure(label, value, tone) {
    return '<div style="flex:1;min-width:150px;">' +
        '<div style="font-size:0.72rem;text-transform:uppercase;letter-spacing:0.5px;' +
        'color:var(--text-secondary);margin-bottom:4px;">' + esc(label) + '</div>' +
        '<div style="font-size:1.35rem;font-weight:700;' +
        (tone ? 'color:' + tone + ';' : '') + '">' + value + '</div></div>';
}

function docTable(title, cols, rows, empty) {
    return '<div class="widget" style="margin-top:16px;">' +
        '<div class="widget-header"><h3>' + esc(title) + '</h3></div>' +
        '<div class="table-responsive"><table class="data-table">' +
        '<thead><tr>' + cols.map(function (c) {
            return '<th' + (c[1] ? ' class="text-right"' : '') + '>' + esc(c[0]) + '</th>';
        }).join('') + '</tr></thead><tbody>' +
        (rows || '<tr><td colspan="' + cols.length + '" style="text-align:center;' +
         'padding:20px;color:var(--text-secondary);">' + esc(empty) + '</td></tr>') +
        '</tbody></table></div></div>';
}

function renderProjectCosts(r) {
    var host = document.getElementById('project-costs');
    var tone = r.margin < 0 ? 'var(--danger-color)' : 'var(--success-color)';

    var head = '<div style="display:flex;justify-content:space-between;align-items:baseline;' +
        'gap:12px;flex-wrap:wrap;margin-bottom:6px;">' +
        '<div><h2 style="margin:0;">' + esc(r.number) + ' ' + esc(r.name) + '</h2>' +
        '<p style="color:var(--text-secondary);margin:2px 0 0;">' +
        esc(r.customer_name || 'No customer set') + '</p></div>' +
        '<button class="btn btn-outline" onclick="showView(\'costs-view\');loadCosts()">Back</button>' +
        '</div>';

    var money = '<div class="widget" style="margin-top:14px;"><div class="widget-content" ' +
        'style="display:flex;gap:20px;flex-wrap:wrap;padding:20px;">' +
        figure('Sold', formatCurrency(r.sold)) +
        figure('Budgeted cost', formatCurrency(r.budgeted_cost)) +
        figure('Committed to suppliers', formatCurrency(r.committed)) +
        figure('Subcontracted', formatCurrency(r.subcontracted)) +
        figure('Margin', formatCurrency(r.margin) + ' <span style="font-size:0.85rem;' +
               'font-weight:400;color:var(--text-secondary);">' + r.margin_percent + '%</span>', tone) +
        '</div></div>';

    var billing = '<div class="widget" style="margin-top:14px;"><div class="widget-content" ' +
        'style="display:flex;gap:20px;flex-wrap:wrap;padding:20px;">' +
        figure('Billed', formatCurrency(r.billed)) +
        figure('Paid', formatCurrency(r.paid)) +
        figure('Unpaid', formatCurrency(r.unpaid),
               r.unpaid ? 'var(--warning-color)' : null) +
        figure('Invoiced out', formatCurrency(r.invoiced)) +
        figure('Awaiting approval', String(r.bills_awaiting_approval)) +
        '</div></div>';

    var warn = r.over_budget > 0
        ? '<div class="widget" style="margin-top:14px;border-left:3px solid var(--danger-color);">' +
          '<div class="widget-content" style="padding:16px 20px;">' +
          '<strong style="color:var(--danger-color);">' + formatCurrency(r.over_budget) +
          ' more committed than budgeted.</strong> <span style="color:var(--text-secondary);">' +
          'What has been promised to suppliers and subcontractors is above what the ' +
          'budget said this work would take.</span></div></div>'
        : '';

    host.innerHTML = head + money + billing + warn +
        docTable('Work orders  ·  what was sold',
            [['Number', 0], ['Status', 0], ['Approval', 0], ['Value', 1]],
            (r.work_order_list || []).map(function (w) {
                return '<tr><td>' + esc(w.number) + '</td><td>' + esc(w.status) +
                    '</td><td>' + esc(w.approval) + '</td>' +
                    '<td class="text-right">' + formatCurrency(w.value) + '</td></tr>';
            }).join(''), 'Nothing sold on this project yet.') +
        docTable('Purchase orders  ·  committed to suppliers',
            [['Number', 0], ['Supplier', 0], ['Status', 0], ['Total', 1]],
            (r.purchase_order_list || []).map(function (p) {
                return '<tr><td>' + esc(p.number) + '</td><td>' + esc(p.supplier) +
                    '</td><td>' + esc(p.status) + '</td>' +
                    '<td class="text-right">' + formatCurrency(p.total) + '</td></tr>';
            }).join(''), 'Nothing ordered from a supplier for this project.') +
        docTable('Subcontract orders  ·  work issued out',
            [['Number', 0], ['Status', 0], ['Net value', 1]],
            (r.subcontract_list || []).map(function (s) {
                return '<tr><td>' + esc(s.number) + '</td><td>' + esc(s.status) + '</td>' +
                    '<td class="text-right">' + formatCurrency(s.net) + '</td></tr>';
            }).join(''), 'Nothing issued to a subcontractor.') +
        docTable('Bills  ·  what is owed and paid',
            [['Number', 0], ['Supplier', 0], ['Status', 0], ['Approval', 0], ['Total', 1]],
            (r.bill_list || []).map(function (b) {
                return '<tr><td>' + esc(b.number) + '</td><td>' + esc(b.supplier) +
                    '</td><td>' + esc(b.status) + '</td><td>' + esc(b.approval) + '</td>' +
                    '<td class="text-right">' + formatCurrency(b.total) + '</td></tr>';
            }).join(''), 'No bills against this project.');
}
