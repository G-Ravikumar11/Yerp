/* ===========================================================================
   staff-portal.js - the staff side of the single portal.

   These screens used to be a separate page behind a separate login. They are
   views in the same shell now, so one person signs in once and sees their own
   work plus whatever else their access allows.

   Every call here goes to an /api/employee/* endpoint, which authenticates the
   employee session and checks the permission itself. Nothing in this file is a
   security boundary: it only decides what to draw. Shared helpers (esc,
   showToast, formatCurrency, localDate, showView, can, portalUser) come from
   app.js, which is loaded first.
   =========================================================================== */

var _myCosts = [];
var _myApprovals = [];
var _pendingDecision = null;

function paintUserChip() {
    var info = document.getElementById('user-info');
    var loginBtn = document.getElementById('login-btn');
    var avatar = document.getElementById('user-avatar');
    if (loginBtn) loginBtn.style.display = 'none';
    if (info) info.style.display = 'flex';
    if (avatar && portalUser.name) {
        // Initials rather than one letter: two people whose names start the
        // same are otherwise identical on screen.
        avatar.textContent = portalUser.name.split(/\s+/).filter(Boolean)
            .slice(0, 2).map(function (p) { return p.charAt(0).toUpperCase(); }).join('');
        avatar.title = portalUser.name + (portalUser.roleLabel ? ' — ' + portalUser.roleLabel : '');
    }
    var nameEl = document.getElementById('user-name');
    if (nameEl) nameEl.textContent = portalUser.name || '';
    var roleEl = document.getElementById('user-role');
    if (roleEl) roleEl.textContent = portalUser.roleLabel || (isEmployee() ? 'Staff' : 'Owner');
}
window.paintUserChip = paintUserChip;

/* Signing out has to end whichever kind of session this is. */
async function handleStaffLogout() {
    try { await fetch('/api/employee/auth/logout', { method: 'POST' }); } catch (e) {}
    window.location.href = '/login.html';
}
window.handleStaffLogout = handleStaffLogout;

async function bootStaffPortal() {
    var greeting = document.getElementById('my-greeting');
    if (greeting) greeting.textContent = 'Hello, ' + String(portalUser.name || '').split(' ')[0];
    var roleLabel = document.getElementById('my-role-label');
    if (roleLabel) {
        roleLabel.textContent = [portalUser.jobTitle, portalUser.roleLabel]
            .filter(Boolean).join(' · ');
    }
    var logoutBtn = document.querySelector('#user-info .btn-icon');
    if (logoutBtn) logoutBtn.setAttribute('onclick', 'handleStaffLogout()');

    showView('my-overview-view');
    var work = [];
    if (can('bills.submit')) work.push(loadMyCosts);
    if (can('bills.approve')) work.push(loadStaffApprovals);
    await Promise.all(work.map(function (fn) { return fn(); }));
    await loadMyOverview();
}
window.bootStaffPortal = bootStaffPortal;

function statusPill(text, tone) {
    var colours = {
        good: 'var(--success-color)', bad: 'var(--danger-color)',
        wait: 'var(--warning-color)', calm: 'var(--text-secondary)'
    };
    var c = colours[tone] || colours.calm;
    return '<span style="display:inline-block;padding:2px 10px;border-radius:10px;font-size:0.75rem;' +
        'font-weight:600;background:' + c + ';color:#fff;opacity:0.9;">' + esc(text) + '</span>';
}
window.statusPill = statusPill;

function costTone(bill) {
    if (bill.status === 'Paid') return 'good';
    if (bill.approval_status === 'approved') return 'good';
    if (bill.approval_status === 'rejected') return 'bad';
    if (bill.approval_status === 'pending') return 'wait';
    return 'calm';
}

/* The raw status is accurate but not informative: "approved" does not tell
   somebody whether they are getting paid. These say where it actually is. */
function costStatusLabel(bill) {
    if (bill.status === 'Paid') return 'Paid';
    if (bill.approval_status === 'pending') return 'Waiting for approval';
    if (bill.approval_status === 'approved') return 'Approved — with finance';
    if (bill.approval_status === 'rejected') return 'Sent back';
    return bill.status || 'Draft';
}

function statCard(label, value) {
    return '<div class="stat-card"><div class="stat-label">' + esc(label) + '</div>' +
        '<div class="stat-value" style="font-size:1.3rem;">' + value + '</div></div>';
}

async function loadMyOverview() {
    var stats = document.getElementById('my-stats');
    var todo = document.getElementById('my-todo');
    var today = portalUser.today || {};
    if (stats) {
        stats.innerHTML =
            statCard('Today', today.today_clock_in ? ('In at ' + esc(today.today_clock_in)) : 'Not clocked in') +
            statCard('Hours today', (today.today_hours || 0).toFixed(2)) +
            statCard('Status', esc(today.today_status || 'absent')) +
            statCard('Access', esc(portalUser.roleLabel || 'Staff'));
    }
    if (!todo) return;

    var items = [];
    if (can('bills.approve') && _myApprovals.length) {
        var n = _myApprovals.length;
        items.push('<a href="#" onclick="event.preventDefault();showView(\'approvals-view\')">' +
            n + ' ' + (n === 1 ? 'cost is' : 'costs are') + ' waiting for your approval</a>');
    }
    if (can('bills.submit')) {
        var sentBack = _myCosts.filter(function (b) { return b.approval_status === 'rejected'; });
        if (sentBack.length) {
            items.push('<a href="#" onclick="event.preventDefault();showView(\'my-costs-view\')">' +
                sentBack.length + ' of your costs ' + (sentBack.length === 1 ? 'was' : 'were') +
                ' sent back to fix</a>');
        }
    }
    todo.innerHTML = items.length
        ? '<ul style="margin:0;padding-left:18px;line-height:1.9;">' +
          items.map(function (i) { return '<li>' + i + '</li>'; }).join('') + '</ul>'
        : '<p style="color:var(--text-secondary);">Nothing right now.</p>';
}
window.loadMyOverview = loadMyOverview;

/* --- My costs ---------------------------------------------------------- */

async function loadMyCosts() {
    var body = document.getElementById('my-costs-body');
    if (!body) return;
    try {
        var res = await fetch('/api/employee/bills');
        if (!res.ok) throw new Error('load failed');
        var data = await res.json();
        _myCosts = data.bills || [];
    } catch (e) {
        body.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:30px;color:var(--text-secondary);">Could not load your costs.</td></tr>';
        return;
    }
    if (!_myCosts.length) {
        body.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:30px;color:var(--text-secondary);">' +
            'Nothing yet. Raise a cost and it goes to your manager for approval.</td></tr>';
        return;
    }
    body.innerHTML = _myCosts.map(function (b) {
        /* Only something not currently in somebody's queue can be edited. */
        var canEdit = b.approval_status === 'rejected' || b.approval_status === 'none';
        return '<tr>' +
            '<td>' + esc(b.number) +
                (b.purchase_order_number
                    ? '<div style="font-size:0.75rem;color:var(--text-secondary);">vs ' +
                      esc(b.purchase_order_number) + '</div>' : '') + '</td>' +
            '<td>' + esc(b.vendor_name) +
                (b.job_name ? '<div style="font-size:0.75rem;color:var(--text-secondary);">' +
                              esc(b.job_name) + '</div>' : '') + '</td>' +
            '<td>' + esc(b.issue_date) + '</td>' +
            '<td class="text-right">' + formatCurrency(b.total) +
                (b.over_order
                    ? '<div style="font-size:0.72rem;color:var(--danger-color);font-weight:700;">over order</div>'
                    : '') + '</td>' +
            '<td>' + statusPill(costStatusLabel(b), costTone(b)) +
                (b.rejection_reason
                    ? '<div style="font-size:0.78rem;color:var(--text-secondary);margin-top:4px;">' +
                      esc(b.rejection_reason) + '</div>'
                    : '') +
            '</td>' +
            '<td class="text-right">' + (canEdit
                ? '<button class="btn btn-sm" onclick="editCost(' + b.id + ')">Fix &amp; resend</button>'
                : '') + '</td>' +
            '</tr>';
    }).join('');
}
window.loadMyCosts = loadMyCosts;

async function showRaiseCostModal() {
    var modal = document.getElementById('raise-cost-modal');
    if (!modal) return;
    document.getElementById('cost-id').value = '';
    document.getElementById('raise-cost-form').reset();
    document.getElementById('cost-date').value = localDate(new Date());
    document.getElementById('cost-submit-btn').textContent = 'Send for approval';
    document.getElementById('raise-cost-route').textContent =
        'This goes to your manager first, then up the line. Nothing is paid until it is approved.';
    if (typeof fillJobPicker === 'function') await fillJobPicker('cost-job');
    await fillOrderPicker();
    modal.style.display = 'flex';
}
window.showRaiseCostModal = showRaiseCostModal;

/* Only approved orders can be settled, so only those are offered. An order
   still waiting on somebody is not something a bill can be matched to. */
async function fillOrderPicker(current) {
    var select = document.getElementById('cost-order');
    if (!select) return;
    try {
        var res = await fetch('/api/employee/purchase-orders');
        var orders = res.ok ? ((await res.json()).orders || []) : [];
        var open = orders.filter(function (o) {
            return o.approval_status === 'approved' && o.status !== 'Closed';
        });
        select.innerHTML = '<option value="">No order</option>' + open.map(function (o) {
            return '<option value="' + o.id + '">' +
                esc(o.number + ' — ' + o.supplier_name) + ' (' + formatCurrency(o.total) + ')</option>';
        }).join('');
        if (current) select.value = current;
    } catch (e) { /* the picker stays on "No order" */ }
}
window.fillOrderPicker = fillOrderPicker;

function closeRaiseCostModal() {
    var modal = document.getElementById('raise-cost-modal');
    if (modal) modal.style.display = 'none';
}
window.closeRaiseCostModal = closeRaiseCostModal;

async function editCost(id) {
    var bill = _myCosts.filter(function (b) { return b.id === id; })[0];
    if (!bill) return;
    await showRaiseCostModal();
    document.getElementById('cost-id').value = bill.id;
    if (typeof fillJobPicker === 'function') await fillJobPicker('cost-job', bill.job_id);
    await fillOrderPicker(bill.purchase_order_id);
    document.getElementById('cost-vendor').value = bill.vendor_name || '';
    document.getElementById('cost-amount').value = bill.amount || '';
    document.getElementById('cost-tax').value = bill.tax_amount || 0;
    document.getElementById('cost-date').value = bill.issue_date || localDate(new Date());
    document.getElementById('cost-reference').value = bill.reference || '';
    document.getElementById('cost-notes').value = bill.notes || '';
    document.getElementById('cost-submit-btn').textContent = 'Fix and resend';
    document.getElementById('raise-cost-route').textContent = bill.rejection_reason
        ? 'Sent back: ' + bill.rejection_reason
        : 'This will go back up the line for approval.';
}
window.editCost = editCost;

async function submitCost() {
    var id = document.getElementById('cost-id').value;
    var payload = {
        vendor_name: document.getElementById('cost-vendor').value.trim(),
        amount: parseFloat(document.getElementById('cost-amount').value) || 0,
        tax_amount: parseFloat(document.getElementById('cost-tax').value) || 0,
        issue_date: document.getElementById('cost-date').value,
        reference: document.getElementById('cost-reference').value.trim(),
        category: document.getElementById('cost-category').value,
        notes: document.getElementById('cost-notes').value.trim(),
        job_id: parseInt(document.getElementById('cost-job').value) || null,
        purchase_order_id: parseInt(document.getElementById('cost-order').value) || null
    };
    if (!payload.vendor_name) { showToast('Who is this owed to?', 'error'); return; }
    if (!(payload.amount > 0)) { showToast('Enter what this cost', 'error'); return; }

    var btn = document.getElementById('cost-submit-btn');
    btn.disabled = true;
    try {
        var res;
        if (id) {
            /* Correcting something that was sent back: save the fix, then put
               it back on the ladder. */
            res = await fetch('/api/employee/bills/' + id, {
                method: 'PUT', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            if (res.ok) {
                res = await fetch('/api/employee/bills/' + id + '/submit', { method: 'POST' });
            }
        } else {
            res = await fetch('/api/employee/bills', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
        }
        var data = await res.json();
        if (!res.ok) { showToast(data.detail || 'Could not send that', 'error'); return; }
        showToast(data.message || 'Sent for approval', 'success');
        closeRaiseCostModal();
        await loadMyCosts();
        loadMyOverview();
    } catch (e) {
        showToast('Could not send that', 'error');
    } finally {
        btn.disabled = false;
    }
}
window.submitCost = submitCost;

/* --- Approving other people's costs ------------------------------------ */

async function loadStaffApprovals() {
    var box = document.getElementById('approvals-content');
    try {
        var res = await fetch('/api/employee/approvals');
        if (!res.ok) throw new Error('load failed');
        var data = await res.json();
        _myApprovals = data.pending || [];
        setStaffApprovalBadge(_myApprovals.length);
        if (box) box.innerHTML = renderApprovalQueue(_myApprovals, data.upcoming || []);
    } catch (e) {
        if (box) box.innerHTML = '<p style="text-align:center;padding:40px;color:var(--text-secondary);">Could not load approvals.</p>';
    }
}
window.loadStaffApprovals = loadStaffApprovals;

function setStaffApprovalBadge(count) {
    var badge = document.getElementById('nav-approvals-count');
    if (!badge) return;
    badge.textContent = count;
    badge.hidden = count === 0;
}

function renderApprovalQueue(pending, upcoming) {
    if (!pending.length && !upcoming.length) {
        return '<p style="text-align:center;padding:40px;color:var(--text-secondary);">Nothing waiting on you.</p>';
    }
    var html = '';
    if (pending.length) {
        html += '<div class="table-responsive"><table class="data-table"><thead><tr>' +
            '<th>Ref</th><th>From</th><th>Supplier</th><th class="text-right">Total</th><th>For</th><th></th>' +
            '</tr></thead><tbody>';
        html += pending.map(function (p) {
            return '<tr>' +
                '<td>' + esc(p.number) +
                    '<div style="font-size:0.75rem;color:var(--text-secondary);">' +
                    esc(p.kind || '') + '</div></td>' +
                '<td>' + esc(p.submitted_by_name) + '</td>' +
                '<td>' + esc(p.vendor_name) +
                    (p.job_name ? '<div style="font-size:0.75rem;color:var(--text-secondary);">' +
                                  esc(p.job_name) + '</div>' : '') + '</td>' +
                '<td class="text-right">' + formatCurrency(p.total) +
                    (p.over_order
                        ? '<div style="font-size:0.72rem;color:var(--danger-color);font-weight:700;">over order</div>'
                        : '') + '</td>' +
                '<td style="max-width:280px;">' + esc(p.notes || '') + '</td>' +
                '<td class="text-right" style="white-space:nowrap;">' +
                    '<button class="btn btn-sm btn-primary" onclick="openDecision(' + p.step_id + ', \'approve\')">Approve</button> ' +
                    '<button class="btn btn-sm" onclick="openDecision(' + p.step_id + ', \'reject\')">Send back</button>' +
                '</td></tr>';
        }).join('');
        html += '</tbody></table></div>';
    }
    /* Steps further up the same chain. Showing them stops an approver
       wondering why something they know about is not in their list. */
    if (upcoming.length) {
        html += '<div style="padding:16px;border-top:1px solid var(--border-color);margin-top:8px;">' +
            '<h4 style="font-size:0.9rem;margin-bottom:8px;">Coming to you</h4>' +
            '<p style="font-size:0.82rem;color:var(--text-secondary);">' +
            upcoming.length + ' ' + (upcoming.length === 1 ? 'item is' : 'items are') +
            ' on your chain but still with someone below you.</p></div>';
    }
    return html;
}

function openDecision(stepId, action) {
    var item = _myApprovals.filter(function (p) { return p.step_id === stepId; })[0];
    _pendingDecision = { stepId: stepId, action: action };
    document.getElementById('decide-title').textContent =
        action === 'approve' ? 'Approve this cost' : 'Send this back';
    document.getElementById('decide-summary').innerHTML = item
        ? esc(item.number) + ' — ' + esc(item.vendor_name) + ' — ' +
          formatCurrency(item.total) + '<br>Raised by ' + esc(item.submitted_by_name)
        : '';
    document.getElementById('decide-note-label').textContent =
        action === 'approve' ? 'Note *' : 'What needs fixing? *';
    document.getElementById('decide-notes').value = '';
    var confirmBtn = document.getElementById('decide-confirm');
    confirmBtn.textContent = action === 'approve' ? 'Approve' : 'Send back';
    confirmBtn.className = 'btn ' + (action === 'approve' ? 'btn-primary' : 'btn-danger');
    document.getElementById('decide-modal').style.display = 'flex';
}
window.openDecision = openDecision;

function closeDecideModal() {
    var modal = document.getElementById('decide-modal');
    if (modal) modal.style.display = 'none';
    _pendingDecision = null;
}
window.closeDecideModal = closeDecideModal;

async function confirmDecision() {
    if (!_pendingDecision) return;
    var notes = document.getElementById('decide-notes').value.trim();
    if (!notes) {
        showToast('Please say why — the person who raised it will see this', 'error');
        return;
    }
    var btn = document.getElementById('decide-confirm');
    btn.disabled = true;
    try {
        var res = await fetch('/api/employee/approvals/' + _pendingDecision.stepId + '/action', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: _pendingDecision.action, notes: notes })
        });
        var data = await res.json();
        if (!res.ok) { showToast(data.detail || 'Could not record that', 'error'); return; }
        showToast(data.status === 'approved'
            ? 'Approved — it is now with finance'
            : data.status === 'pending' ? 'Approved and passed up the line' : 'Sent back',
            'success');
        closeDecideModal();
        await loadStaffApprovals();
        loadMyOverview();
    } catch (e) {
        showToast('Could not record that', 'error');
    } finally {
        btn.disabled = false;
    }
}
window.confirmDecision = confirmDecision;

/* --- Timesheet, leave, payslips, documents ----------------------------- */

async function loadMyTimesheet() {
    var body = document.getElementById('my-timesheet-body');
    if (!body) return;
    try {
        var res = await fetch('/api/employee/attendance/today');
        var rows = [];
        if (res.ok) {
            var data = await res.json();
            rows = data.recent || data.history || (data.today ? [data.today] : []);
        }
        if (!rows.length) {
            body.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:30px;color:var(--text-secondary);">No clock-ins recorded.</td></tr>';
            return;
        }
        body.innerHTML = rows.map(function (r) {
            return '<tr><td>' + esc(r.date) + '</td><td>' + esc(r.clock_in || '—') + '</td>' +
                '<td>' + esc(r.clock_out || '—') + '</td>' +
                '<td class="text-right">' + (r.total_hours || 0) + '</td>' +
                '<td>' + esc(r.location_label || r.check_type || '') + '</td>' +
                '<td>' + statusPill(r.status || 'present', r.status === 'completed' ? 'good' : 'calm') + '</td></tr>';
        }).join('');
    } catch (e) {
        body.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:30px;color:var(--text-secondary);">Could not load your timesheet.</td></tr>';
    }
}
window.loadMyTimesheet = loadMyTimesheet;

async function loadMyLeave() {
    var body = document.getElementById('my-leave-body');
    if (!body) return;
    try {
        var res = await fetch('/api/employee/leave');
        var data = res.ok ? await res.json() : { requests: [] };
        var rows = data.requests || [];
        if (!rows.length) {
            body.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:30px;color:var(--text-secondary);">No leave booked.</td></tr>';
            return;
        }
        body.innerHTML = rows.map(function (l) {
            var tone = l.status === 'approved' ? 'good' : l.status === 'rejected' ? 'bad' : 'wait';
            return '<tr><td>' + esc(l.leave_type) + '</td><td>' + esc(l.start_date) + '</td>' +
                '<td>' + esc(l.end_date) + '</td><td class="text-right">' + (l.days || 0) + '</td>' +
                '<td>' + statusPill(l.status, tone) + '</td><td>' + esc(l.reason || '') + '</td></tr>';
        }).join('');
    } catch (e) {
        body.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:30px;color:var(--text-secondary);">Could not load your leave.</td></tr>';
    }
}
window.loadMyLeave = loadMyLeave;

function showRequestLeaveModal() {
    var modal = document.getElementById('request-leave-modal');
    if (!modal) return;
    document.getElementById('request-leave-form').reset();
    var today = localDate(new Date());
    document.getElementById('leave-start').value = today;
    document.getElementById('leave-end').value = today;
    modal.style.display = 'flex';
}
window.showRequestLeaveModal = showRequestLeaveModal;

function closeRequestLeaveModal() {
    var modal = document.getElementById('request-leave-modal');
    if (modal) modal.style.display = 'none';
}
window.closeRequestLeaveModal = closeRequestLeaveModal;

async function submitLeaveRequest() {
    var payload = {
        leave_type: document.getElementById('leave-type').value,
        start_date: document.getElementById('leave-start').value,
        end_date: document.getElementById('leave-end').value,
        reason: document.getElementById('leave-reason').value.trim()
    };
    if (!payload.start_date || !payload.end_date) {
        showToast('Pick the dates you are off', 'error');
        return;
    }
    var btn = document.getElementById('leave-submit-btn');
    btn.disabled = true;
    try {
        var res = await fetch('/api/employee/leave', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        var data = await res.json();
        /* The server counts the working days and checks the balance, so its
           message is the one worth showing. */
        if (!res.ok) { showToast(data.detail || 'Could not send that', 'error'); return; }
        showToast(data.message || 'Leave requested', 'success');
        closeRequestLeaveModal();
        loadMyLeave();
    } catch (e) {
        showToast('Could not send that', 'error');
    } finally {
        btn.disabled = false;
    }
}
window.submitLeaveRequest = submitLeaveRequest;

async function loadMyPayslips() {
    var body = document.getElementById('my-payslips-body');
    if (!body) return;
    try {
        var res = await fetch('/api/employee/dashboard');
        var data = res.ok ? await res.json() : {};
        var rows = data.payslips || [];
        if (!rows.length) {
            body.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:30px;color:var(--text-secondary);">No payslips yet.</td></tr>';
            return;
        }
        body.innerHTML = rows.map(function (p) {
            return '<tr><td>' + esc(p.number) + '</td>' +
                '<td>' + esc(p.period_start) + ' → ' + esc(p.period_end) + '</td>' +
                '<td>' + esc(p.pay_date || '') + '</td>' +
                '<td class="text-right">' + formatCurrency(p.gross_pay) + '</td>' +
                '<td class="text-right">' + formatCurrency(p.net_pay) + '</td>' +
                '<td>' + statusPill(p.status || '', p.status === 'Paid' ? 'good' : 'calm') + '</td></tr>';
        }).join('');
    } catch (e) {
        body.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:30px;color:var(--text-secondary);">Could not load your payslips.</td></tr>';
    }
}
window.loadMyPayslips = loadMyPayslips;

async function loadMyDocuments() {
    var requests = document.getElementById('my-doc-requests');
    var files = document.getElementById('my-doc-files');
    try {
        var res = await fetch('/api/employee/document-requests');
        var data = res.ok ? await res.json() : { requests: [] };
        var rows = data.requests || [];
        if (requests) {
            requests.innerHTML = rows.length
                ? rows.map(function (r) {
                    var tone = r.status === 'approved' ? 'good' : r.status === 'rejected' ? 'bad'
                        : r.status === 'submitted' ? 'wait' : 'calm';
                    return '<div style="display:flex;justify-content:space-between;align-items:center;gap:12px;padding:10px 0;border-bottom:1px solid var(--border-light);">' +
                        '<div><strong>' + esc(r.name) + '</strong>' +
                        (r.due_date ? '<div style="font-size:0.78rem;color:var(--text-secondary);">Due ' + esc(r.due_date) + '</div>' : '') +
                        '</div>' + statusPill(r.status, tone) + '</div>';
                }).join('')
                : '<p style="color:var(--text-secondary);">Nothing outstanding.</p>';
        }
    } catch (e) {
        if (requests) requests.innerHTML = '<p style="color:var(--text-secondary);">Could not load requests.</p>';
    }
    try {
        var dres = await fetch('/api/employee/documents');
        var docs = dres.ok ? await dres.json() : [];
        if (files) {
            files.innerHTML = docs.length
                ? docs.map(function (d) {
                    return '<div style="padding:10px 0;border-bottom:1px solid var(--border-light);">' +
                        '<a href="/api/employee/documents/' + d.id + '/download">' + esc(d.title) + '</a>' +
                        '<span style="font-size:0.78rem;color:var(--text-secondary);margin-left:8px;">' +
                        esc(d.doc_type || '') + '</span></div>';
                }).join('')
                : '<p style="color:var(--text-secondary);">Nothing on file.</p>';
        }
    } catch (e) {
        if (files) files.innerHTML = '<p style="color:var(--text-secondary);">Could not load documents.</p>';
    }
}
window.loadMyDocuments = loadMyDocuments;

/* --- HR: the access picker on the employee form ------------------------ */

var _permissionRoles = [];

async function loadPermissionRoles(current) {
    var select = document.getElementById('emp-permission-role');
    if (!select) return;
    try {
        /* Same catalogue endpoint as the level and role pickers, so the
           vocabulary has one definition and one cached fetch. */
        var data = await loadHrLevels();
        _permissionRoles = data.permission_roles || [];
        if (!_permissionRoles.length) return;
        select.innerHTML = _permissionRoles.map(function (r) {
            return '<option value="' + esc(r.code) + '">' + esc(r.label) + '</option>';
        }).join('');
        select.value = current || 'staff';
        describeAccessChoice();
    } catch (e) { /* the default Staff option stands */ }
}
window.loadPermissionRoles = loadPermissionRoles;

/* HR is choosing what somebody can do, so the consequence of the choice is
   spelled out under the picker rather than left to the role's name. */
function describeAccessChoice() {
    var select = document.getElementById('emp-permission-role');
    var help = document.getElementById('emp-permission-help');
    if (!select || !help) return;
    var role = _permissionRoles.filter(function (r) { return r.code === select.value; })[0];
    help.textContent = role ? role.description : '';
}
window.describeAccessChoice = describeAccessChoice;

/* --- HR: organisation email addresses ---------------------------------- */

/* When the business has a domain, staff accounts are issued on it. Typing the
   name fills the address in, so HR is not hand-rolling firstname.lastname and
   getting it subtly wrong on every tenth hire. */
function prefillOrgEmail() {
    var first = document.getElementById('emp-first-name');
    var last = document.getElementById('emp-last-name');
    var email = document.getElementById('emp-email');
    if (!first || !last || !email || email.dataset.orgWired) return;
    email.dataset.orgWired = '1';

    var suggest = async function () {
        /* Never overwrite something typed by hand. */
        if (email.value && !email.dataset.suggested) return;
        if (!first.value.trim() && !last.value.trim()) return;
        try {
            var res = await fetch('/api/hr/suggest-email?first_name=' +
                encodeURIComponent(first.value.trim()) + '&last_name=' +
                encodeURIComponent(last.value.trim()));
            if (!res.ok) return;
            var data = await res.json();
            if (!data.email) return;
            email.value = data.email;
            email.dataset.suggested = '1';
        } catch (e) { /* HR can still type it */ }
    };
    first.addEventListener('blur', suggest);
    last.addEventListener('blur', suggest);
    email.addEventListener('input', function () { delete email.dataset.suggested; });
}
window.prefillOrgEmail = prefillOrgEmail;
