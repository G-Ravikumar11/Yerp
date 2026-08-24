/* ===========================================================================
   contracts.js - the two ends of the contracts flow.

   Customers at one end: the party a project belongs to, with the detail a
   contract needs rather than the name and phone number billing got by on.

   Work Order Inquiry at the other: every order on one screen with what it is
   worth, whether its budget has been allocated, and where its approval stands.
   That is where the flow finishes, because that is where the managing
   director signs a project off.
   =========================================================================== */

/* --- Customers ----------------------------------------------------------- */

var CUSTOMERS = [];
var CUSTOMER_FIELDS = ['name', 'contact_person', 'email', 'phone_number', 'gstin',
                       'address', 'city', 'state', 'pincode', 'notes'];

async function loadCustomers(query) {
    var body = document.getElementById('customers-body');
    if (!body) return;
    body.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:30px;color:var(--text-secondary);">Loading customers...</td></tr>';
    try {
        var res = await fetch('/api/customers?q=' + encodeURIComponent(query || ''),
                              { credentials: 'include' });
        CUSTOMERS = (await res.json()).customers || [];
    } catch (e) {
        body.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:30px;color:var(--text-secondary);">Could not load customers.</td></tr>';
        return;
    }
    renderCustomers();
}
window.loadCustomers = loadCustomers;

function searchCustomers() {
    var box = document.getElementById('customer-search');
    loadCustomers(box ? box.value : '');
}
window.searchCustomers = searchCustomers;

function renderCustomers() {
    var body = document.getElementById('customers-body');
    if (!body) return;
    if (!CUSTOMERS.length) {
        body.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:30px;color:var(--text-secondary);">' +
            'No customers yet. Add the first one to start a project against it.' +
            '</td></tr>';
        return;
    }
    body.innerHTML = CUSTOMERS.map(function (c) {
        var place = [c.city, c.state].filter(Boolean).join(', ');
        return '<tr>' +
            '<td><code>' + esc(c.code) + '</code></td>' +
            '<td><strong>' + esc(c.name) + '</strong>' +
                (c.contact_person ? '<br><small>' + esc(c.contact_person) + '</small>' : '') + '</td>' +
            '<td>' + (esc(c.email) || '&mdash;') +
                (c.phone_number ? '<br><small>' + esc(c.phone_number) + '</small>' : '') + '</td>' +
            '<td>' + (esc(c.gstin) || '&mdash;') +
                (place ? '<br><small>' + esc(place) + '</small>' : '') + '</td>' +
            '<td class="text-right">' + (c.projects || 0) + '</td>' +
            '<td class="text-right"><button class="btn btn-sm btn-outline" ' +
                'onclick="showCustomerModal(' + c.id + ')">Edit</button></td>' +
            '</tr>';
    }).join('');
}

function showCustomerModal(id) {
    var c = id ? CUSTOMERS.filter(function (x) { return x.id === id; })[0] : null;
    document.getElementById('customer-modal-title').textContent =
        c ? 'Edit customer' : 'Add new customer';
    document.getElementById('customer-id').value = c ? c.id : '';
    CUSTOMER_FIELDS.forEach(function (f) {
        var el = document.getElementById('cust-' + f);
        if (el) el.value = c ? (c[f] || '') : '';
    });
    document.getElementById('customer-modal').style.display = 'flex';
    var first = document.getElementById('cust-name');
    if (first) first.focus();
}
window.showCustomerModal = showCustomerModal;

function closeCustomerModal() {
    document.getElementById('customer-modal').style.display = 'none';
}
window.closeCustomerModal = closeCustomerModal;

async function saveCustomer() {
    var id = document.getElementById('customer-id').value;
    var payload = {};
    CUSTOMER_FIELDS.forEach(function (f) {
        var el = document.getElementById('cust-' + f);
        payload[f] = el ? el.value.trim() : '';
    });
    if (!payload.name) { showToast('A customer name is required', 'error'); return; }

    var res = await fetch('/api/customers' + (id ? '/' + id : ''), {
        method: id ? 'PUT' : 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not save the customer', 'error'); return; }
    closeCustomerModal();
    showToast(out.message || 'Saved', 'success');
    searchCustomers();
}
window.saveCustomer = saveCustomer;

/* --- Work Order Inquiry --------------------------------------------------
   The screen the flow ends on. One row per order, carrying the three things
   somebody signing a project off actually needs side by side: what it sells
   for, whether a cost has been put behind it, and who has approved it.
   ------------------------------------------------------------------------ */

var INQUIRY = { rows: [], filter: 'all' };

async function loadInquiry() {
    var body = document.getElementById('inquiry-body');
    if (!body) return;
    body.innerHTML = '<tr><td colspan="8" style="text-align:center;padding:30px;color:var(--text-secondary);">Loading work orders...</td></tr>';
    try {
        var res = await fetch('/api/erp/inquiry', { credentials: 'include' });
        var data = await res.json();
        INQUIRY.rows = data.rows || [];
        renderInquiryStats(data.summary || {});
    } catch (e) {
        body.innerHTML = '<tr><td colspan="8" style="text-align:center;padding:30px;color:var(--text-secondary);">Could not load work orders.</td></tr>';
        return;
    }
    renderInquiry();
}
window.loadInquiry = loadInquiry;

function renderInquiryStats(s) {
    var host = document.getElementById('inquiry-stats');
    if (!host) return;
    host.innerHTML = [
        ['Work orders', s.orders || 0],
        ['Value', formatCurrency(s.total_value || 0)],
        ['Expected margin', formatCurrency(s.total_margin || 0)],
        ['Awaiting approval', s.awaiting_approval || 0],
        ['Budget not allocated', s.not_budgeted || 0],
    ].map(function (pair) {
        return statCard(pair[0], pair[1]);
    }).join('');
}

function setInquiryFilter(which, el) {
    INQUIRY.filter = which;
    document.querySelectorAll('#inquiry-tabs .tab').forEach(function (t) {
        t.classList.remove('active');
    });
    if (el) el.classList.add('active');
    renderInquiry();
}
window.setInquiryFilter = setInquiryFilter;

function inquiryVisible() {
    var f = INQUIRY.filter;
    return INQUIRY.rows.filter(function (r) {
        if (f === 'awaiting') return r.can_approve && !r.can_place;
        if (f === 'approved') return r.approval_status === 'approved';
        if (f === 'draft') return r.can_place;
        if (f === 'unbudgeted') return !r.budgeted;
        return true;
    });
}

var APPROVAL_TONE = {
    'Approved': 'good', 'Rejected': 'bad',
    'Awaiting': 'wait', 'Not sent': 'calm',
};

function renderInquiry() {
    var body = document.getElementById('inquiry-body');
    if (!body) return;
    var rows = inquiryVisible();
    if (!rows.length) {
        body.innerHTML = '<tr><td colspan="8" style="text-align:center;padding:30px;color:var(--text-secondary);">' +
            'Nothing here. Build a work order and allocate its budget, then it ' +
            'comes to this screen for approval.</td></tr>';
        return;
    }
    body.innerHTML = rows.map(function (r) {
        // Only ever one thing to do next, so the row offers that and not a
        // row of buttons where all but one are refused on the way in.
        var actions;
        if (r.can_place) {
            actions = '<button class="btn btn-sm btn-primary" onclick="placeOrder(' +
                r.id + ')">Place order</button>';
        } else if (r.can_approve) {
            actions = '<button class="btn btn-sm btn-primary" onclick="mdDecide(' +
                r.id + ',true)">Approve</button> ' +
                '<button class="btn btn-sm btn-outline" onclick="mdDecide(' +
                r.id + ',false)">Send back</button>';
        } else if (!r.budgeted) {
            // Placed, but with no cost behind it, so that is what it is short
            // of and what the row offers.
            actions = '<button class="btn btn-sm btn-primary" onclick="startBomBuilder(' +
                r.id + ')">Allocate budget</button>';
        } else {
            // Signed off. Nothing is asked of anyone, and offering an action
            // anyway would suggest the order was still short of something.
            actions = '';
        }
        // The report reads the budget back, so it is offered wherever there
        // is a budget to read - including on an order still waiting to be
        // approved, which is exactly when somebody wants to look at it.
        if (r.budgeted) {
            actions += ' <button class="btn btn-sm btn-outline" onclick="openBudgetReport(' +
                r.id + ')">Report</button>';
        }
        return '<tr>' +
            '<td style="font-family:monospace;font-weight:600;">' + esc(r.number) +
                (r.reference ? '<div style="font-size:0.75rem;font-family:inherit;' +
                    'font-weight:400;color:var(--text-secondary);">' +
                    esc(r.reference) + '</div>' : '') + '</td>' +
            '<td>' + esc(r.job_name) +
                '<div style="font-size:0.75rem;color:var(--text-secondary);">' +
                esc(r.customer_name) + '</div></td>' +
            '<td class="text-right">' + formatCurrency(r.total_value) + '</td>' +
            '<td class="text-right">' + (r.budgeted
                ? formatCurrency(r.budget_cost) + '</td>'
                : '<span style="color:var(--text-muted);">&mdash;</span></td>') +
            '<td class="text-right">' + (r.budgeted
                ? formatCurrency(r.margin) +
                    '<div style="font-size:0.72rem;color:var(--text-secondary);">' +
                    r.margin_percent + '%</div>'
                : '&mdash;') + '</td>' +
            '<td>' + statusPill(r.bom_status, r.budgeted ? 'good' : 'calm') + '</td>' +
            '<td>' + statusPill(r.md_approval, APPROVAL_TONE[r.md_approval] || 'calm') +
                (r.rejection_reason ? '<div style="font-size:0.72rem;color:var(--text-secondary);">' +
                    esc(r.rejection_reason) + '</div>' : '') +
            '</td>' +
            '<td class="text-right">' + actions + '</td>' +
            '</tr>';
    }).join('');
}

async function placeOrder(id) {
    var res = await fetch('/api/erp/work-orders/' + id + '/place-order',
                          { method: 'POST', credentials: 'include' });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not place the order', 'error'); return; }
    showToast(out.message, 'success');
    loadInquiry();
    if (typeof loadWorkOrders === 'function') loadWorkOrders();
}
window.placeOrder = placeOrder;

/* --- The Budget Entry Report ---------------------------------------------
   The allocation read back under the lines it was allocated against, laid
   out as it is printed. Sold lines with nothing budgeted against them are
   shown rather than skipped: an order that looks complete because the gaps
   were left off the page is the one failure this report cannot afford.
   ------------------------------------------------------------------------ */

var BUDGET_REPORT_ID = 0;

async function openBudgetReport(id) {
    BUDGET_REPORT_ID = id;
    showView('budget-report-view');
    var host = document.getElementById('budget-report-sheet');
    if (!host) return;
    host.innerHTML = '<p style="text-align:center;padding:30px;color:var(--text-secondary);">Loading the report...</p>';
    var res = await fetch('/api/erp/work-orders/' + id + '/budget-report',
                          { credentials: 'include' });
    if (!res.ok) {
        host.innerHTML = '<p style="text-align:center;padding:30px;color:var(--text-secondary);">Could not load the report.</p>';
        return;
    }
    renderBudgetReport(await res.json());
}
window.openBudgetReport = openBudgetReport;

function downloadBudgetReport() {
    if (BUDGET_REPORT_ID) {
        window.location = '/api/erp/work-orders/' + BUDGET_REPORT_ID +
                          '/budget-report.xlsx';
    }
}
window.downloadBudgetReport = downloadBudgetReport;

function reportHeading(r) {
    return '<div class="report-head">' +
        '<div class="report-head-top">' +
            '<h2>' + esc(r.title) + '</h2>' +
            '<strong>' + esc(r.company) + '</strong>' +
        '</div>' +
        '<div class="report-meta">' +
            '<span>Print Out Date: ' + esc(r.printed_at) + '</span>' +
            '<span>Fiscal Year: ' + esc(r.fiscal_year) + '</span>' +
            '<span>Sale order No: ' + esc(r.sale_order_no) + '</span>' +
            '<span>Project: ' + esc(r.project) + '</span>' +
        '</div></div>';
}

function renderBudgetReport(r) {
    var host = document.getElementById('budget-report-sheet');
    var rows = r.groups.map(function (g) {
        // The ordered line first, then what it consumes, so the cost is read
        // against the price rather than on its own.
        var head = '<tr class="report-group">' +
            '<td><code>' + esc(g.fg_code) + '</code></td>' +
            '<td colspan="4">' + esc((g.item_name || '').split('\n')[0]) + '</td>' +
            '<td class="text-right">' + formatCurrency(g.value) + '</td>' +
            '<td class="text-right">' + (g.budgeted
                ? formatCurrency(g.cost)
                : statusPill('Not budgeted', 'calm')) + '</td>' +
            '</tr>';
        var lines = g.lines.map(function (m) {
            return '<tr>' +
                '<td></td>' +
                '<td>' + esc(m.description.split('\n')[0]) + '</td>' +
                '<td class="text-right">' + m.qty + '</td>' +
                '<td>' + esc(m.uom) + '</td>' +
                '<td class="text-right">' + m.rate + '</td>' +
                '<td class="text-right">' + m.wo_qty + '</td>' +
                '<td class="text-right">' + formatCurrency(m.amount) + '</td>' +
                '</tr>';
        }).join('');
        return head + lines;
    }).join('');

    var t = r.totals;
    host.innerHTML = reportHeading(r) +
        '<div class="table-responsive"><table class="data-table report-table">' +
        '<thead><tr><th>Ordered Items</th><th>RM code - Description</th>' +
        '<th class="text-right">Quantity</th><th>Units</th>' +
        '<th class="text-right">Price</th><th class="text-right">WO Qty</th>' +
        '<th class="text-right">Total Amount</th></tr></thead>' +
        '<tbody>' + (rows || '<tr><td colspan="7" style="text-align:center;padding:30px;color:var(--text-secondary);">' +
            'Nothing on this order yet.</td></tr>') + '</tbody>' +
        '<tfoot><tr>' +
            '<td colspan="5"><strong>' + t.ordered_lines + ' ordered line(s), ' +
                t.material_lines + ' material line(s)' +
                (t.unbudgeted_lines
                    ? ', <strong>' + t.unbudgeted_lines + ' not budgeted</strong>'
                    : '') + '</strong></td>' +
            '<td class="text-right"><strong>' + formatCurrency(t.value) + '</strong></td>' +
            '<td class="text-right"><strong>' + formatCurrency(t.cost) + '</strong></td>' +
        '</tr><tr>' +
            '<td colspan="6" class="text-right">Margin</td>' +
            '<td class="text-right"><strong>' + formatCurrency(t.margin) +
                ' (' + t.margin_percent + '%)</strong></td>' +
        '</tr></tfoot></table></div>';
}

async function mdDecide(id, approve) {
    // A rejection has to say why. The order goes back to whoever raised it,
    // and "rejected" on its own tells them nothing they can act on.
    var notes = '';
    if (!approve) {
        notes = prompt('Why is this going back?');
        if (notes === null) return;
        if (!notes.trim()) { showToast('Give a reason so it can be corrected', 'error'); return; }
    }
    var res = await fetch('/api/erp/inquiry/' + id + '/md-approval', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ approve: approve, notes: notes }),
    });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not record the decision', 'error'); return; }
    showToast(out.message, 'success');
    loadInquiry();
    if (typeof loadWorkOrders === 'function') loadWorkOrders();
}
window.mdDecide = mdDecide;
