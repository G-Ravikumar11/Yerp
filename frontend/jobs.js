/* ===========================================================================
   jobs.js - jobs, job costing and purchase orders.

   A contracting business earns per job, not per month. Everything priced,
   bought or worked can point at one, and these screens are where that adds up
   to the only figure that decides whether to take the next job like it.

   Loaded after app.js and staff-portal.js; shared helpers (esc, showToast,
   formatCurrency, localDate, showView, can, portalUser) come from there.
   =========================================================================== */

var _jobs = [];
var _orders = [];
var _currentJob = null;
var _jobPickerCache = null;

/* --- Shared helpers ---------------------------------------------------- */

var JOB_STATUS_LABELS = {
    quoting: 'Quoting', won: 'Won', in_progress: 'In progress',
    on_hold: 'On hold', complete: 'Complete', cancelled: 'Cancelled'
};

function jobStatusTone(status) {
    if (status === 'complete') return 'good';
    if (status === 'cancelled') return 'bad';
    if (status === 'on_hold') return 'wait';
    return 'calm';
}

/* Margin is the number people scan for, so it carries the colour: red when the
   job is losing money, amber when it is thin, green when it is healthy. */
function marginColour(percent, hasRevenue) {
    if (!hasRevenue) return 'var(--text-secondary)';
    if (percent < 0) return 'var(--danger-color)';
    if (percent < 10) return 'var(--warning-color)';
    return 'var(--success-color)';
}

async function jobOptions() {
    if (_jobPickerCache) return _jobPickerCache;
    try {
        var url = isEmployee() ? '/api/employee/jobs' : '/api/jobs?open_only=true';
        var res = await fetch(url);
        if (!res.ok) return [];
        _jobPickerCache = (await res.json()).jobs || [];
    } catch (e) { _jobPickerCache = []; }
    return _jobPickerCache;
}

async function fillJobPicker(selectId, current) {
    var select = document.getElementById(selectId);
    if (!select) return;
    var jobs = await jobOptions();
    select.innerHTML = '<option value="">Not job-specific</option>' +
        jobs.map(function (j) {
            return '<option value="' + j.id + '">' + esc(j.number + ' — ' + j.name) + '</option>';
        }).join('');
    if (current) select.value = current;
}
window.fillJobPicker = fillJobPicker;

/* --- The jobs board ---------------------------------------------------- */

async function loadJobs() {
    var body = document.getElementById('jobs-body');
    var totals = document.getElementById('jobs-totals');
    if (!body) return;
    try {
        var res = await fetch('/api/jobs-summary');
        if (!res.ok) throw new Error('load failed');
        var data = await res.json();
        _jobs = data.jobs || [];
        _jobPickerCache = null;
        if (totals) {
            var t = data.totals || {};
            totals.innerHTML =
                statCard('Invoiced', formatCurrency(t.invoiced)) +
                statCard('Cost', formatCurrency(t.cost)) +
                statCard('Committed', formatCurrency(t.committed)) +
                statCard('Profit', '<span style="color:' +
                    marginColour(t.profit >= 0 ? 1 : -1, true) + ';">' +
                    formatCurrency(t.profit) + '</span>');
        }
    } catch (e) {
        body.innerHTML = '<tr><td colspan="9" style="text-align:center;padding:30px;color:var(--text-secondary);">Could not load jobs.</td></tr>';
        return;
    }
    if (!_jobs.length) {
        body.innerHTML = '<tr><td colspan="9" style="text-align:center;padding:30px;color:var(--text-secondary);">' +
            'No live jobs. Add one and every quote, bill and order can be filed against it.</td></tr>';
        return;
    }
    body.innerHTML = _jobs.map(function (j) {
        var c = j.costing;
        var colour = marginColour(c.margin_percent, c.invoiced > 0);
        return '<tr style="cursor:pointer;" onclick="openJob(' + j.id + ')">' +
            '<td><strong>' + esc(j.number) + '</strong><div style="font-size:0.8rem;color:var(--text-secondary);">' + esc(j.name) + '</div></td>' +
            '<td>' + esc(j.customer_name || '—') + '</td>' +
            '<td>' + statusPill(JOB_STATUS_LABELS[j.status] || j.status, jobStatusTone(j.status)) +
                (c.over_budget ? ' <span style="font-size:0.72rem;color:var(--danger-color);font-weight:700;">over budget</span>' : '') + '</td>' +
            '<td class="text-right">' + formatCurrency(c.invoiced) + '</td>' +
            '<td class="text-right">' + formatCurrency(c.total_cost) + '</td>' +
            '<td class="text-right">' + (c.committed ? formatCurrency(c.committed) : '—') + '</td>' +
            '<td class="text-right" style="color:' + colour + ';font-weight:600;">' + formatCurrency(c.profit) + '</td>' +
            '<td class="text-right" style="color:' + colour + ';font-weight:600;">' +
                (c.invoiced ? c.margin_percent + '%' : '—') + '</td>' +
            '<td class="text-right"><button class="btn btn-sm" onclick="event.stopPropagation();editJob(' + j.id + ')">Edit</button></td>' +
            '</tr>';
    }).join('');
}
window.loadJobs = loadJobs;

async function openJob(id) {
    try {
        var res = await fetch('/api/jobs/' + id);
        if (!res.ok) { showToast('Could not open that project', 'error'); return; }
        _currentJob = await res.json();
    } catch (e) { showToast('Could not open that project', 'error'); return; }

    var j = _currentJob, c = j.costing;
    showView('job-detail-view');
    document.getElementById('job-detail-name').textContent = j.number + ' — ' + j.name;
    document.getElementById('job-detail-sub').textContent =
        [j.customer_name, j.site_address, JOB_STATUS_LABELS[j.status] || j.status]
            .filter(Boolean).join(' · ');

    var colour = marginColour(c.margin_percent, c.invoiced > 0);
    document.getElementById('job-detail-stats').innerHTML =
        statCard('Quoted', formatCurrency(c.quoted)) +
        statCard('Invoiced', formatCurrency(c.invoiced)) +
        statCard('Received', formatCurrency(c.received)) +
        statCard('Cost so far', formatCurrency(c.total_cost)) +
        statCard('Committed', formatCurrency(c.committed)) +
        statCard('Labour', formatCurrency(c.labour_cost) + ' <span style="font-size:0.75rem;color:var(--text-secondary);">' + c.labour_hours + 'h</span>') +
        statCard('Profit', '<span style="color:' + colour + ';">' + formatCurrency(c.profit) + '</span>') +
        statCard('Margin', '<span style="color:' + colour + ';">' + (c.invoiced ? c.margin_percent + '%' : '—') + '</span>');

    var html = '';
    if (c.over_budget) {
        html += '<p style="color:var(--danger-color);font-weight:600;margin-bottom:12px;">' +
            'Costs and open orders have passed the ' + formatCurrency(c.budget) + ' budget.</p>';
    }
    html += docTable('Invoices', j.invoices, function (i) {
        return [esc(i.number), esc(i.to_contact || ''), esc(i.issue_date),
                formatCurrency(i.total), esc(i.status)];
    }, ['Invoice', 'Customer', 'Date', 'Total', 'Status']);
    html += docTable('Purchase orders', j.purchase_orders, function (o) {
        return [esc(o.number), esc(o.supplier_name), esc(o.issue_date),
                formatCurrency(o.total), esc(o.status)];
    }, ['Order', 'Supplier', 'Date', 'Total', 'Status']);
    html += docTable('Bills', j.bills, function (b) {
        return [esc(b.number), esc(b.vendor_name), esc(b.issue_date),
                formatCurrency(b.total),
                esc(b.status) + (b.over_order ? ' <span style="color:var(--danger-color);">over order</span>' : '')];
    }, ['Bill', 'Supplier', 'Date', 'Total', 'Status']);
    html += docTable('Quotes', j.quotes, function (q) {
        return [esc(q.number), esc(q.issue_date), formatCurrency(q.total), esc(q.status)];
    }, ['Quote', 'Date', 'Total', 'Status']);
    document.getElementById('job-detail-documents').innerHTML =
        html || '<p style="color:var(--text-secondary);">Nothing filed against this project yet.</p>';
}
window.openJob = openJob;

function docTable(title, rows, cells, headers) {
    if (!rows || !rows.length) return '';
    return '<h4 style="font-size:0.9rem;margin:16px 0 8px;">' + esc(title) + '</h4>' +
        '<div class="table-responsive"><table class="data-table"><thead><tr>' +
        headers.map(function (h, i) {
            return '<th' + (i >= headers.length - 2 ? '' : '') + '>' + esc(h) + '</th>';
        }).join('') + '</tr></thead><tbody>' +
        rows.map(function (r) {
            return '<tr>' + cells(r).map(function (c) { return '<td>' + c + '</td>'; }).join('') + '</tr>';
        }).join('') + '</tbody></table></div>';
}

/* --- Creating and editing a job ---------------------------------------- */

function showJobModal() {
    var modal = document.getElementById('job-modal');
    if (!modal) return;
    document.getElementById('job-form').reset();
    document.getElementById('job-id').value = '';
    document.getElementById('job-modal-title').textContent = 'New project';
    document.getElementById('job-start').value = localDate(new Date());
    modal.style.display = 'flex';
}
window.showJobModal = showJobModal;

function closeJobModal() {
    var modal = document.getElementById('job-modal');
    if (modal) modal.style.display = 'none';
}
window.closeJobModal = closeJobModal;

function editJob(id) {
    var job = _jobs.filter(function (j) { return j.id === id; })[0] ||
              (_currentJob && _currentJob.id === id ? _currentJob : null);
    if (!job) return;
    showJobModal();
    document.getElementById('job-modal-title').textContent = 'Edit ' + job.number;
    document.getElementById('job-id').value = job.id;
    document.getElementById('job-name').value = job.name || '';
    document.getElementById('job-customer').value = job.customer_name || '';
    document.getElementById('job-status').value = job.status || 'quoting';
    document.getElementById('job-site').value = job.site_address || '';
    document.getElementById('job-quoted').value = job.quoted_value || 0;
    document.getElementById('job-budget').value = job.budget || 0;
    document.getElementById('job-start').value = job.start_date || '';
    document.getElementById('job-end').value = job.target_end_date || '';
    document.getElementById('job-description').value = job.description || '';
}
window.editJob = editJob;

function editCurrentJob() {
    if (_currentJob) editJob(_currentJob.id);
}
window.editCurrentJob = editCurrentJob;

async function saveJob() {
    var id = document.getElementById('job-id').value;
    var payload = {
        name: document.getElementById('job-name').value.trim(),
        customer_name: document.getElementById('job-customer').value.trim(),
        status: document.getElementById('job-status').value,
        site_address: document.getElementById('job-site').value.trim(),
        quoted_value: parseFloat(document.getElementById('job-quoted').value) || 0,
        budget: parseFloat(document.getElementById('job-budget').value) || 0,
        start_date: document.getElementById('job-start').value,
        target_end_date: document.getElementById('job-end').value,
        description: document.getElementById('job-description').value.trim()
    };
    if (!payload.name) { showToast('Give the project a name', 'error'); return; }

    var btn = document.getElementById('job-save-btn');
    btn.disabled = true;
    try {
        var res = await fetch(id ? '/api/jobs/' + id : '/api/jobs', {
            method: id ? 'PUT' : 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        var data = await res.json();
        if (!res.ok) { showToast(data.detail || 'Could not save', 'error'); return; }
        showToast(id ? 'Project updated' : 'Project created', 'success');
        closeJobModal();
        _jobPickerCache = null;
        if (id && _currentJob && _currentJob.id === parseInt(id)) openJob(_currentJob.id);
        else loadJobs();
    } catch (e) {
        showToast('Could not save', 'error');
    } finally {
        btn.disabled = false;
    }
}
window.saveJob = saveJob;

/* --- Purchase orders --------------------------------------------------- */

function orderTone(order) {
    if (order.approval_status === 'approved') return 'good';
    if (order.approval_status === 'rejected') return 'bad';
    if (order.approval_status === 'pending') return 'wait';
    return 'calm';
}

async function loadOrders() {
    var body = document.getElementById('orders-body');
    if (!body) return;
    try {
        var res = await fetch('/api/purchase-orders');
        if (!res.ok) throw new Error('load failed');
        _orders = (await res.json()).orders || [];
    } catch (e) {
        body.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:30px;color:var(--text-secondary);">Could not load orders.</td></tr>';
        return;
    }
    if (!_orders.length) {
        body.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:30px;color:var(--text-secondary);">' +
            'No orders yet. Raising one gets the spend agreed before it is committed.</td></tr>';
        return;
    }
    body.innerHTML = _orders.map(function (o) {
        return '<tr>' +
            '<td>' + esc(o.number) + '</td>' +
            '<td>' + esc(o.supplier_name) + '</td>' +
            '<td>' + esc(o.job_name || '—') + '</td>' +
            '<td class="text-right">' + formatCurrency(o.total) + '</td>' +
            '<td class="text-right">' + (o.billed_count
                ? formatCurrency(o.billed_total) + ' <span style="font-size:0.75rem;color:var(--text-secondary);">(' + o.billed_count + ')</span>'
                : '—') + '</td>' +
            '<td>' + statusPill(o.status, orderTone(o)) + '</td>' +
            '<td class="text-right">' + (o.approval_status !== 'pending'
                ? '<button class="btn btn-sm" onclick="editOrder(' + o.id + ')">Edit</button> ' : '') +
                // An order is a document that gets sent on, so it can be taken
                // away whatever state it is in.
                '<a class="btn btn-sm btn-outline" href="/api/purchase-orders/' + o.id +
                '/export.xlsx" title="Download this order">Excel</a></td>' +
            '</tr>';
    }).join('');
}
window.loadOrders = loadOrders;

async function showOrderModal() {
    var modal = document.getElementById('order-modal');
    if (!modal) return;
    document.getElementById('order-form').reset();
    document.getElementById('order-id').value = '';
    document.getElementById('order-modal-title').textContent = 'New purchase order';
    document.getElementById('order-date').value = localDate(new Date());
    document.getElementById('order-route').textContent =
        'An order records what you have agreed to spend, before the bill arrives.';
    document.getElementById('order-save-btn').textContent = 'Save';
    await fillJobPicker('order-job');
    modal.style.display = 'flex';
}
window.showOrderModal = showOrderModal;

/* Staff raise an order and it goes straight up the line; the owner's version
   just records it. Same form, different button and different endpoint. */
async function showRaiseOrderModal() {
    await showOrderModal();
    document.getElementById('order-modal-title').textContent = 'Raise an order';
    document.getElementById('order-route').textContent =
        'This goes to your manager for approval before you commit to it.';
    document.getElementById('order-save-btn').textContent = 'Send for approval';
}
window.showRaiseOrderModal = showRaiseOrderModal;

function closeOrderModal() {
    var modal = document.getElementById('order-modal');
    if (modal) modal.style.display = 'none';
}
window.closeOrderModal = closeOrderModal;

async function editOrder(id) {
    var order = _orders.filter(function (o) { return o.id === id; })[0];
    if (!order) return;
    await showOrderModal();
    document.getElementById('order-modal-title').textContent = 'Edit ' + order.number;
    document.getElementById('order-id').value = order.id;
    document.getElementById('order-supplier').value = order.supplier_name || '';
    document.getElementById('order-amount').value = order.amount || '';
    document.getElementById('order-tax').value = order.tax_amount || 0;
    document.getElementById('order-date').value = order.issue_date || '';
    document.getElementById('order-needed').value = order.needed_by || '';
    document.getElementById('order-notes').value = order.notes || '';
    document.getElementById('order-job').value = order.job_id || '';
}
window.editOrder = editOrder;

async function saveOrder() {
    var id = document.getElementById('order-id').value;
    var jobVal = document.getElementById('order-job').value;
    var payload = {
        supplier_name: document.getElementById('order-supplier').value.trim(),
        amount: parseFloat(document.getElementById('order-amount').value) || 0,
        tax_amount: parseFloat(document.getElementById('order-tax').value) || 0,
        issue_date: document.getElementById('order-date').value,
        needed_by: document.getElementById('order-needed').value,
        notes: document.getElementById('order-notes').value.trim(),
        job_id: jobVal ? parseInt(jobVal) : null
    };
    if (!payload.supplier_name) { showToast('Who is this order with?', 'error'); return; }
    if (!(payload.amount > 0)) { showToast('Enter the amount', 'error'); return; }

    var btn = document.getElementById('order-save-btn');
    btn.disabled = true;
    try {
        var url, method;
        if (id) { url = '/api/purchase-orders/' + id; method = 'PUT'; }
        else if (isEmployee()) { url = '/api/employee/purchase-orders'; method = 'POST'; }
        else { url = '/api/purchase-orders'; method = 'POST'; }

        var res = await fetch(url, {
            method: method, headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        var data = await res.json();
        if (!res.ok) { showToast(data.detail || 'Could not save', 'error'); return; }
        showToast(data.message || 'Order saved', 'success');
        closeOrderModal();
        if (isEmployee()) loadMyOrders(); else loadOrders();
    } catch (e) {
        showToast('Could not save', 'error');
    } finally {
        btn.disabled = false;
    }
}
window.saveOrder = saveOrder;

async function loadMyOrders() {
    var body = document.getElementById('my-orders-body');
    if (!body) return;
    try {
        var res = await fetch('/api/employee/purchase-orders');
        if (!res.ok) throw new Error('load failed');
        _orders = (await res.json()).orders || [];
    } catch (e) {
        body.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:30px;color:var(--text-secondary);">Could not load your orders.</td></tr>';
        return;
    }
    if (!_orders.length) {
        body.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:30px;color:var(--text-secondary);">' +
            'Nothing yet. Raise an order to get spend agreed before you commit to it.</td></tr>';
        return;
    }
    body.innerHTML = _orders.map(function (o) {
        var canResend = o.approval_status === 'rejected' || o.approval_status === 'none';
        return '<tr>' +
            '<td>' + esc(o.number) + '</td>' +
            '<td>' + esc(o.supplier_name) + '</td>' +
            '<td>' + esc(o.job_name || '—') + '</td>' +
            '<td class="text-right">' + formatCurrency(o.total) + '</td>' +
            '<td>' + statusPill(o.status, orderTone(o)) +
                (o.rejection_reason ? '<div style="font-size:0.78rem;color:var(--text-secondary);margin-top:4px;">' + esc(o.rejection_reason) + '</div>' : '') +
            '</td>' +
            '<td class="text-right">' + (canResend
                ? '<button class="btn btn-sm" onclick="resendOrder(' + o.id + ')">Send again</button>' : '') + '</td>' +
            '</tr>';
    }).join('');
}
window.loadMyOrders = loadMyOrders;

async function resendOrder(id) {
    try {
        var res = await fetch('/api/employee/purchase-orders/' + id + '/submit', { method: 'POST' });
        var data = await res.json();
        if (!res.ok) { showToast(data.detail || 'Could not send that', 'error'); return; }
        showToast(data.message || 'Sent for approval', 'success');
        loadMyOrders();
    } catch (e) { showToast('Could not send that', 'error'); }
}
window.resendOrder = resendOrder;

/* --- Settings: approval rules and the staff email domain --------------- */

async function loadApprovalRules() {
    var auto = document.getElementById('rule-auto-below');
    if (!auto) return;
    try {
        var res = await fetch('/api/approval-rules');
        if (!res.ok) return;
        var data = await res.json();
        auto.value = data.auto_below || 0;
        document.getElementById('rule-finance-above').value = data.finance_above || 0;
        var note = document.getElementById('rule-finance-note');
        if (note) {
            /* A limit that names nobody does nothing, and silently. Say so. */
            note.textContent = data.has_finance_approver
                ? 'Above this, ' + data.finance_approver + ' is added to the chain as a final approver.'
                : 'Nobody currently has permission to release payment, so this rule will add no one. '
                  + 'Give somebody the Finance access level under People.';
            note.style.color = data.has_finance_approver
                ? 'var(--text-secondary)' : 'var(--warning-color)';
        }
    } catch (e) { /* leave the fields as they are */ }
}
window.loadApprovalRules = loadApprovalRules;

async function saveApprovalRules() {
    try {
        var res = await fetch('/api/approval-rules', {
            method: 'PUT', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                auto_below: parseFloat(document.getElementById('rule-auto-below').value) || 0,
                finance_above: parseFloat(document.getElementById('rule-finance-above').value) || 0
            })
        });
        var data = await res.json();
        if (!res.ok) { showToast(data.detail || 'Could not save', 'error'); return; }
        showToast(data.message || 'Saved', 'success');
        loadApprovalRules();
    } catch (e) { showToast('Could not save', 'error'); }
}
window.saveApprovalRules = saveApprovalRules;

async function loadOrgDomain() {
    var field = document.getElementById('org-domain');
    if (!field) return;
    try {
        var res = await fetch('/api/hr/org-domain');
        if (!res.ok) return;
        var data = await res.json();
        field.value = data.domain || '';
        var note = document.getElementById('org-domain-note');
        if (note) {
            if (!data.domain) {
                note.textContent = 'Leave blank to allow any email address for staff accounts.';
            } else if (data.employees_off_domain) {
                note.textContent = data.employees_off_domain +
                    ' existing ' + (data.employees_off_domain === 1 ? 'person signs' : 'people sign') +
                    ' in with an address off this domain. They keep it; only new accounts are affected.';
            } else {
                note.textContent = 'New staff accounts are created on this domain.';
            }
        }
    } catch (e) { /* leave as is */ }
}
window.loadOrgDomain = loadOrgDomain;

async function saveOrgDomain() {
    try {
        var res = await fetch('/api/hr/org-domain', {
            method: 'PUT', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ domain: document.getElementById('org-domain').value.trim() })
        });
        var data = await res.json();
        if (!res.ok) { showToast(data.detail || 'Could not save', 'error'); return; }
        showToast('Organisation domain saved', 'success');
        loadOrgDomain();
    } catch (e) { showToast('Could not save', 'error'); }
}
window.saveOrgDomain = saveOrgDomain;
