/* Approvals: one inbox for everything waiting on a signature.

   Work orders to gangs, RA bills and subcontractor bills to certify,
   variations, purchase orders and bills on the reporting line, and leave -
   each used to wait in its own screen, and a person who could decide one had
   to know where to look. The server reads all of them for whoever is signed
   in; this draws the list and sends each decision back through that
   document's own rules. */

var APPROVALS = { tab: 'inbox', items: [], owner: false, pick: null, decision: '' };

function apEmpty(text) {
    return '<p style="text-align:center;color:var(--text-secondary);padding:40px;">' + esc(text) + '</p>';
}

function apSetBadge(n) {
    var badge = document.getElementById('nav-approvals-count');
    if (badge) { badge.textContent = n; badge.hidden = !n; }
    var tab = document.getElementById('pending-approval-count');
    if (tab) { tab.textContent = n; tab.style.display = n ? 'inline-block' : 'none'; }
}

async function refreshApprovalBadge() {
    try {
        var res = await fetch('/api/approvals/inbox', { credentials: 'include' });
        if (!res.ok) return;
        var data = await res.json();
        APPROVALS.mine = data.mine || 0;
        apSetBadge(APPROVALS.mine);
        return data;
    } catch (e) { /* the badge is a courtesy */ }
}
window.refreshApprovalBadge = refreshApprovalBadge;

function apTabs(tab) {
    document.querySelectorAll('#approvals-tabs .tab').forEach(function (t) {
        t.classList.toggle('active', t.dataset.tab === tab);
    });
}

async function loadApprovalsInbox(tab) {
    APPROVALS.tab = tab || APPROVALS.tab || 'inbox';
    apTabs(APPROVALS.tab);
    var box = document.getElementById('approvals-content');
    if (!box) return;
    box.innerHTML = apEmpty('Loading...');
    try {
        if (APPROVALS.tab === 'sent') {
            var sent = await (await fetch('/api/approvals/sent', { credentials: 'include' })).json();
            box.innerHTML = apSentTable(sent.items || []);
            return;
        }
        var res = await fetch('/api/approvals/inbox', { credentials: 'include' });
        var data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Could not load');
        APPROVALS.items = data.items || [];
        APPROVALS.owner = !!data.owner;
        APPROVALS.mine = data.mine || 0;
        apSetBadge(APPROVALS.mine);
        box.innerHTML = apInbox(APPROVALS.items);
    } catch (e) {
        box.innerHTML = '<p style="text-align:center;color:var(--danger-color);padding:40px;">Could not load approvals: ' + esc(e.message) + '</p>';
    }
}
window.loadApprovalsInbox = loadApprovalsInbox;

function apPill(text, colour) {
    return '<span style="display:inline-block;padding:2px 8px;border-radius:6px;font-size:0.72rem;font-weight:700;' +
        'background:' + colour + '1f;color:' + colour + ';white-space:nowrap;">' + esc(text) + '</span>';
}

var AP_COLOURS = {
    subcontract_order: '#7c3aed', ra_bill: '#0891b2', sub_bill: '#d97706', variation: '#db2777',
    step: '#2563eb', leave: '#059669'
};

function apWhen(v) {
    if (!v) return '';
    var d = String(v).slice(0, 10).split('-');
    return d.length === 3 ? d[2] + '/' + d[1] + '/' + d[0] : v;
}

function apRow(i) {
    var colour = AP_COLOURS[i.kind] || '#475569';
    var number = i.pdf
        ? '<a href="' + esc(i.pdf) + '" target="_blank" rel="noopener" title="Open the document">' + esc(i.number) + '</a>'
        : esc(i.number);
    var who = [i.party, i.project].filter(Boolean).map(esc).join('<br><span style="color:var(--text-secondary);font-size:0.78rem;">') +
        ([i.party, i.project].filter(Boolean).length > 1 ? '</span>' : '');
    var raised = i.raised_by ? esc(i.raised_by) + (i.since ? '<div style="font-size:0.75rem;color:var(--text-secondary);">' + apWhen(i.since) + '</div>' : '')
                             : (i.since ? apWhen(i.since) : '');
    var what = (i.what ? '<div style="font-size:0.8rem;color:var(--text-secondary);max-width:320px;">' + esc(i.what) + '</div>' : '') +
        (i.warnings || []).map(function (w) {
            return '<div style="font-size:0.75rem;color:var(--danger-color);font-weight:700;">' + esc(w) + '</div>';
        }).join('') +
        (!i.mine && i.waiting_on ? '<div style="font-size:0.75rem;color:var(--text-secondary);">With ' + esc(i.waiting_on) + '</div>' : '');
    return '<tr>' +
        '<td>' + apPill(i.kind_label, colour) + '<div style="font-weight:700;margin-top:4px;font-family:monospace;">' + number + '</div></td>' +
        '<td>' + (who || '-') + what + '</td>' +
        '<td class="text-right" style="white-space:nowrap;">' + (i.amount ? formatCurrency(i.amount) : '') + '</td>' +
        '<td>' + raised + '</td>' +
        '<td class="text-right" style="white-space:nowrap;">' +
            '<button class="btn btn-sm btn-outline" onclick="apOpen(\'' + i.key + '\')">Open</button> ' +
            '<button class="btn btn-sm btn-primary" onclick="apDecide(\'' + i.key + '\',\'approve\')">' + esc(i.approve_label) + '</button> ' +
            '<button class="btn btn-sm btn-outline" onclick="apDecide(\'' + i.key + '\',\'reject\')">' + esc(i.reject_label) + '</button>' +
        '</td></tr>';
}

function apTable(items) {
    return '<div class="table-responsive"><table class="data-table"><thead><tr>' +
        '<th>Document</th><th>For</th><th class="text-right">Amount</th><th>Raised by</th><th></th>' +
        '</tr></thead><tbody>' + items.map(apRow).join('') + '</tbody></table></div>';
}

function apInbox(items) {
    var mine = items.filter(function (i) { return i.mine; });
    var others = items.filter(function (i) { return !i.mine; });
    if (!items.length) return apEmpty('Nothing is waiting on you.');
    var html = '';
    html += '<h3 style="font-size:0.95rem;margin:4px 0 10px;">Waiting on you <span style="color:var(--text-secondary);font-weight:400;">(' + mine.length + ')</span></h3>';
    html += mine.length ? apTable(mine) : apEmpty('Nothing is waiting on you.');
    if (others.length) {
        /* The owner sees everything in flight. Stepping in is allowed - it
           is their business - but it is shown apart so it is a choice. */
        html += '<h3 style="font-size:0.95rem;margin:24px 0 6px;">With your team <span style="color:var(--text-secondary);font-weight:400;">(' + others.length + ')</span></h3>' +
            '<p style="font-size:0.8rem;color:var(--text-secondary);margin-bottom:10px;">Waiting on somebody else. You can decide them yourself if they are stuck.</p>' +
            apTable(others);
    }
    return html;
}

function apSentTable(rows) {
    if (!rows.length) return apEmpty(APPROVALS.owner ? 'Nothing has been sent for approval yet.' : 'You have not sent anything for approval yet.');
    var colours = { pending: '#d97706', approved: '#16a34a', rejected: '#dc2626' };
    var words = { pending: 'Waiting', approved: 'Approved', rejected: 'Sent back' };
    return '<div class="table-responsive"><table class="data-table"><thead><tr>' +
        '<th>Document</th><th>For</th><th class="text-right">Amount</th><th>Status</th><th>Where it is</th>' +
        '</tr></thead><tbody>' + rows.map(function (r) {
            var where = r.status === 'pending' ? (r.waiting_on ? 'With ' + esc(r.waiting_on) : 'Waiting')
                : r.status === 'rejected' ? esc(r.reason || 'Sent back') : '';
            return '<tr><td>' + apPill(r.kind_label, '#475569') +
                '<div style="font-weight:700;margin-top:4px;font-family:monospace;">' + esc(r.number) + '</div></td>' +
                '<td>' + esc(r.party || '-') + (APPROVALS.owner && r.raised_by ? '<div style="font-size:0.75rem;color:var(--text-secondary);">Raised by ' + esc(r.raised_by) + '</div>' : '') + '</td>' +
                '<td class="text-right" style="white-space:nowrap;">' + (r.amount ? formatCurrency(r.amount) : '') + '</td>' +
                '<td>' + apPill(words[r.status] || r.status, colours[r.status] || '#475569') + '</td>' +
                '<td style="max-width:320px;font-size:0.85rem;">' + where + '</td></tr>';
        }).join('') + '</tbody></table></div>';
}

function apFind(key) {
    return APPROVALS.items.filter(function (i) { return i.key === key; })[0];
}

function apOpen(key) {
    var i = apFind(key);
    if (!i) return;
    if (i.kind === 'ra_bill' && typeof openDocument === 'function') return openDocument('ra-bill', i.id);
    if (i.kind === 'sub_bill' && typeof openDocument === 'function') return openDocument('sub-bill', i.id);
    if (i.kind === 'step' && i.doc_type === 'purchase_order' && typeof openDocument === 'function') return openDocument('po', i.doc_id);
    if (i.kind === 'subcontract_order' && typeof openSubcontract === 'function') {
        showView('subcontracts-view');
        return openSubcontract(i.id);
    }
    if (i.view) showView(i.view);
}
window.apOpen = apOpen;

function apDecide(key, decision) {
    var i = apFind(key);
    if (!i) return;
    APPROVALS.pick = i;
    APPROVALS.decision = decision;
    var approve = decision === 'approve';
    var needsNote = !approve || i.note_to_approve || i.overrun;
    document.getElementById('decide-title').textContent =
        (approve ? i.approve_label : i.reject_label) + ' ' + i.kind_label.toLowerCase() + ' ' + i.number;
    document.getElementById('decide-summary').innerHTML =
        [i.party, i.project].filter(Boolean).map(esc).join(' - ') +
        (i.amount ? ' - ' + formatCurrency(i.amount) : '') +
        (i.raised_by ? '<br>Raised by ' + esc(i.raised_by) : '') +
        (approve && i.overrun ? '<div style="margin-top:8px;color:var(--danger-color);font-weight:600;">' +
            esc((i.warnings || []).join(' ')) + ' Approving commits it anyway - say why.</div>' : '');
    document.getElementById('decide-note-label').textContent =
        approve ? (needsNote ? 'Note *' : 'Note (optional)') : 'What needs putting right? *';
    document.getElementById('decide-notes').value = '';
    var btn = document.getElementById('decide-confirm');
    btn.textContent = approve ? i.approve_label : i.reject_label;
    btn.className = 'btn ' + (approve ? 'btn-primary' : 'btn-danger');
    btn.setAttribute('onclick', 'apConfirm()');
    document.getElementById('decide-modal').style.display = 'flex';
}
window.apDecide = apDecide;

async function apConfirm() {
    var i = APPROVALS.pick;
    if (!i) return;
    var approve = APPROVALS.decision === 'approve';
    var note = document.getElementById('decide-notes').value.trim();
    if (!note && (!approve || i.note_to_approve || i.overrun)) {
        showToast(approve ? 'Add a note - the person who raised it will see it'
                          : 'Say what needs putting right, so it can be fixed', 'error');
        return;
    }
    var btn = document.getElementById('decide-confirm');
    btn.disabled = true;
    try {
        var res = await fetch('/api/approvals/decide', {
            method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ kind: i.kind, id: i.id, decision: APPROVALS.decision, note: note,
                                   override: !!(approve && i.overrun) })
        });
        var data = await res.json();
        if (!res.ok) { showToast(data.detail || 'Could not record that', 'error'); return; }
        showToast(data.message || (approve ? 'Done' : 'Sent back'), 'success');
        document.getElementById('decide-modal').style.display = 'none';
        APPROVALS.pick = null;
        loadApprovalsInbox('inbox');
    } catch (e) {
        showToast('Could not record that', 'error');
    } finally {
        btn.disabled = false;
    }
}
window.apConfirm = apConfirm;

/* The count on the menu, for the owner and for staff alike: once the page
   has worked out who is signed in, and every couple of minutes after. */
setTimeout(refreshApprovalBadge, 1500);
setInterval(refreshApprovalBadge, 120000);
