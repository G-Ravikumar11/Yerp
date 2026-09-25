/* ===========================================================================
   leads.js - the tender pipeline and the EMD register.

   A board of the tenders in play by stage, the bid dates coming up, and the
   earnest money still with clients. One click prices a tender - it becomes an
   estimate - and the estimate's win or loss comes back here on its own.
   =========================================================================== */

var LEADS = { rows: [], meta: {}, editing: null, current: null, tab: 'board' };
var LEAD_STAGES = [['NEW', 'New'], ['QUALIFIED', 'Qualified'], ['ESTIMATING', 'Estimating'], ['SUBMITTED', 'Bid in']];

async function loadLeads() {
    var host = document.getElementById('leads-body');
    if (!host) return;
    var d = await (await fetch('/api/leads', { credentials: 'include' })).json();
    LEADS.rows = d.leads || [];
    LEADS.meta = d;
    var s = d.summary || {};
    document.getElementById('leads-stats').innerHTML =
        statCard('Live tenders', String(s.live || 0)) +
        statCard('Pipeline value', formatCurrency(s.pipeline_value || 0)) +
        statCard('Bids due this week', String(s.due_this_week || 0)) +
        statCard('Hit rate', (s.hit_rate || 0) + '%') +
        statCard('EMD with clients', formatCurrency(s.emd_out || 0) +
            (s.emd_out_count ? ' <span style="font-size:0.7rem;color:var(--text-secondary);">(' + s.emd_out_count + ')</span>' : ''));
    document.querySelectorAll('#leads-tabs button').forEach(function (b) {
        b.classList.toggle('active', b.dataset.tab === LEADS.tab); });
    if (LEADS.tab === 'emd') return leadsEmd(host);
    if (LEADS.tab === 'closed') return leadsClosed(host);
    host.innerHTML = '<div style="display:grid;grid-template-columns:repeat(4,minmax(220px,1fr));gap:12px;overflow-x:auto;">' +
        LEAD_STAGES.map(function (st) {
            var here = LEADS.rows.filter(function (l) { return l.status === st[0]; });
            return '<div style="background:var(--bg-hover,rgba(0,0,0,0.03));border-radius:10px;padding:10px;min-height:120px;">' +
                '<div style="font-weight:700;font-size:0.82rem;margin-bottom:8px;display:flex;justify-content:space-between;">' +
                esc(st[1]) + '<span style="color:var(--text-secondary);font-weight:400;">' + here.length + ' &middot; ' +
                formatCurrency(here.reduce(function (t, l) { return t + (l.estimated_value || 0); }, 0)) + '</span></div>' +
                here.map(leadCard).join('') + '</div>';
        }).join('') + '</div>';
    if (LEADS.current) openLead(LEADS.current);
}
window.loadLeads = loadLeads;

function leadCard(l) {
    var d = l.days_to_bid;
    var due = d === null || d === undefined ? '' :
        d < 0 ? '<span style="color:var(--danger-color);font-weight:600;">bid date passed</span>' :
        d <= 3 ? '<span style="color:var(--danger-color);font-weight:600;">bid in ' + d + ' day' + (d === 1 ? '' : 's') + '</span>' :
        d <= 7 ? '<span style="color:var(--warning-color);">bid in ' + d + ' days</span>' : 'bid ' + esc(l.bid_due_on);
    return '<div onclick="openLead(' + l.id + ')" style="cursor:pointer;background:var(--card-bg,#fff);border:1px solid var(--border-color);' +
        'border-radius:8px;padding:9px 10px;margin-bottom:8px;">' +
        '<div style="font-size:0.7rem;color:var(--text-secondary);font-family:monospace;">' + esc(l.number) + '</div>' +
        '<div style="font-weight:600;font-size:0.84rem;line-height:1.3;">' + esc(l.title) + '</div>' +
        '<div style="font-size:0.74rem;color:var(--text-secondary);">' + esc(l.customer_name || '') + '</div>' +
        '<div style="display:flex;justify-content:space-between;font-size:0.74rem;margin-top:5px;">' +
        '<span>' + formatCurrency(l.estimated_value) + '</span><span>' + due + '</span></div>' +
        (l.emd_outstanding ? '<div style="font-size:0.7rem;color:var(--text-secondary);margin-top:3px;">EMD ' +
            formatCurrency(l.emd_amount) + ' out</div>' : '') + '</div>';
}

function leadsClosed(host) {
    var done = LEADS.rows.filter(function (l) { return ['WON', 'LOST', 'DROPPED'].indexOf(l.status) >= 0; });
    var tone = { WON: 'good', LOST: 'bad', DROPPED: 'calm' };
    host.innerHTML = '<div class="widget"><div class="table-responsive"><table class="data-table">' +
        '<thead><tr><th>No.</th><th>Tender</th><th>Client</th><th class="text-right">Our price ₹</th>' +
        '<th>Outcome</th><th>Why / who won</th><th class="text-right">Their price ₹</th></tr></thead><tbody>' +
        (done.length ? done.map(function (l) {
            return '<tr style="cursor:pointer;" onclick="openLead(' + l.id + ')"><td style="font-family:monospace;">' + esc(l.number) + '</td>' +
                '<td>' + esc(l.title) + '</td><td>' + esc(l.customer_name) + '</td>' +
                '<td class="text-right">' + formatCurrency(l.our_price || l.estimated_value) + '</td>' +
                '<td>' + statusPill(l.status, tone[l.status]) + '</td>' +
                '<td>' + esc(l.lost_reason || '') + (l.winning_bidder ? ' &mdash; ' + esc(l.winning_bidder) : '') + '</td>' +
                '<td class="text-right">' + (l.winning_price ? formatCurrency(l.winning_price) : '') + '</td></tr>';
        }).join('') : '<tr><td colspan="7" style="text-align:center;padding:22px;color:var(--text-secondary);">Nothing decided yet.</td></tr>') +
        '</tbody></table></div></div>';
}

async function leadsEmd(host) {
    var d = await (await fetch('/api/leads-emd', { credentials: 'include' })).json();
    host.innerHTML = '<div class="stats-grid">' +
        statCard('EMD with clients', formatCurrency(d.summary.out)) +
        statCard('On tenders already decided', formatCurrency(d.summary.on_decided_tenders)) +
        statCard('Deposits out', String(d.summary.count)) + '</div>' +
        '<div class="widget" style="margin-top:14px;"><div class="table-responsive"><table class="data-table">' +
        '<thead><tr><th>Tender</th><th>Client</th><th>Mode / ref.</th><th>Paid on</th><th class="text-right">Days held</th>' +
        '<th class="text-right">Amount ₹</th><th>Tender is</th><th></th></tr></thead><tbody>' +
        (d.emds.length ? d.emds.map(function (l) {
            var chase = ['WON', 'LOST', 'DROPPED'].indexOf(l.status) >= 0;
            return '<tr><td><span style="font-family:monospace;">' + esc(l.number) + '</span> ' + esc(l.title) + '</td>' +
                '<td>' + esc(l.customer_name) + '</td><td>' + esc(l.emd_mode) + ' ' + esc(l.emd_reference) + '</td>' +
                '<td style="white-space:nowrap;">' + esc(l.emd_paid_on) + '</td>' +
                '<td class="text-right" style="' + (chase ? 'color:var(--danger-color);font-weight:700;' : '') + '">' + (l.days_held || 0) + '</td>' +
                '<td class="text-right" style="font-weight:600;white-space:nowrap;">' + formatCurrency(l.emd_amount) + '</td>' +
                '<td>' + esc(l.status.toLowerCase()) + (chase ? ' <span style="font-size:0.7rem;color:var(--danger-color);">chase it</span>' : '') + '</td>' +
                '<td class="text-right"><button class="btn btn-sm btn-outline" onclick="leadEmdBack(' + l.id + ')">Came back</button></td></tr>';
        }).join('') : '<tr><td colspan="8" style="text-align:center;padding:22px;color:var(--text-secondary);">No earnest money out.</td></tr>') +
        '</tbody></table></div></div>';
}

function leadsTab(t) { LEADS.tab = t; loadLeads(); }
window.leadsTab = leadsTab;

async function leadEmdBack(id) {
    var res = await fetch('/api/leads/' + id + '/emd-returned', {
        method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: '{}' });
    var out = await res.json();
    showToast(out.message || out.detail, res.ok ? 'success' : 'error');
    loadLeads();
}
window.leadEmdBack = leadEmdBack;

/* --- One tender ----------------------------------------------------------------- */

async function openLead(id) {
    LEADS.current = id;
    var l = await (await fetch('/api/leads/' + id, { credentials: 'include' })).json();
    var open = ['NEW', 'QUALIFIED', 'ESTIMATING', 'SUBMITTED'].indexOf(l.status) >= 0;
    var move = open && !l.estimate_id ? LEAD_STAGES.filter(function (s) { return s[0] !== l.status && s[0] !== 'ESTIMATING' && s[0] !== 'SUBMITTED'; })
        .map(function (s) { return '<button class="btn btn-sm btn-outline" onclick="leadMove(' + l.id + ',\'' + s[0] + '\')">' + s[1] + '</button>'; }).join(' ') : '';
    document.getElementById('lead-detail').innerHTML = '<div class="widget" style="margin-top:18px;">' +
        '<div class="widget-header"><h3>' + esc(l.number + ' ' + l.title) + '</h3>' +
        '<div style="display:flex;gap:6px;flex-wrap:wrap;">' + move +
        (open && !l.estimate_id ? ' <button class="btn btn-sm btn-primary" onclick="leadEstimate(' + l.id + ')">Price it</button>' : '') +
        (l.estimate_id ? ' <button class="btn btn-sm btn-outline" onclick="showView(\'estimates-view\')">Estimate ' + esc(l.estimate_number) + '</button>' : '') +
        (open ? ' <button class="btn btn-sm btn-outline" onclick="leadLose(' + l.id + ')">Lost</button>' +
                ' <button class="btn btn-sm btn-outline" onclick="leadDrop(' + l.id + ')">Drop</button>' : '') +
        ' <button class="btn btn-sm btn-outline" onclick="leadEdit(' + l.id + ')">Edit</button>' +
        ' <button class="btn btn-sm btn-outline" onclick="LEADS.current=null;document.getElementById(\'lead-detail\').innerHTML=\'\'">Close</button></div></div>' +
        '<div style="padding:14px 18px;display:grid;grid-template-columns:1fr 1fr;gap:18px;">' +
        '<div style="font-size:0.84rem;line-height:1.7;">' +
            '<div><strong>Client:</strong> ' + esc(l.customer_name || '—') + (l.contact_person ? ' &middot; ' + esc(l.contact_person) : '') +
                (l.phone ? ' &middot; ' + esc(l.phone) : '') + '</div>' +
            '<div><strong>Where:</strong> ' + esc(l.location || '—') + ' &middot; <strong>Source:</strong> ' + esc(l.source || '—') + '</div>' +
            '<div><strong>Reference:</strong> ' + esc(l.tender_reference || '—') + '</div>' +
            '<div><strong>Value:</strong> ' + formatCurrency(l.estimated_value) + (l.our_price ? ' &middot; <strong>our price</strong> ' + formatCurrency(l.our_price) : '') + '</div>' +
            '<div><strong>Site visit:</strong> ' + esc(l.site_visit_on || '—') + ' &middot; <strong>pre-bid:</strong> ' + esc(l.prebid_on || '—') +
                ' &middot; <strong>bid due:</strong> ' + esc(l.bid_due_on || '—') + '</div>' +
            '<div><strong>EMD:</strong> ' + (l.emd_amount ? formatCurrency(l.emd_amount) + ' ' + esc(l.emd_mode) + ' ' + esc(l.emd_reference) +
                (l.emd_returned_on ? ' &mdash; back ' + esc(l.emd_returned_on) : l.emd_paid_on ? ' &mdash; paid ' + esc(l.emd_paid_on) : '') : '—') + '</div>' +
            (l.lost_reason ? '<div><strong>Lost:</strong> ' + esc(l.lost_reason) + (l.winning_bidder ? ' &mdash; ' + esc(l.winning_bidder) +
                (l.winning_price ? ' at ' + formatCurrency(l.winning_price) : '') : '') + '</div>' : '') +
        '</div><div>' +
        '<div style="display:flex;gap:6px;margin-bottom:8px;">' +
        '<select id="lead-act-kind" class="form-control" style="width:auto;"><option>Call</option><option>Visit</option><option>Meeting</option><option>Email</option><option>Note</option></select>' +
        '<input id="lead-act-note" class="form-control" placeholder="What happened"></div>' +
        '<div style="display:flex;gap:6px;margin-bottom:10px;">' +
        '<input id="lead-act-next" class="form-control" placeholder="Next step"><input type="date" id="lead-act-on" class="form-control" style="width:auto;">' +
        '<button class="btn btn-sm btn-primary" onclick="leadNote(' + l.id + ')">Add</button></div>' +
        '<div style="max-height:220px;overflow-y:auto;font-size:0.8rem;">' + (l.activities || []).map(function (a) {
            return '<div style="padding:6px 0;border-top:1px solid var(--border-color);"><strong>' + esc(a.kind) + '</strong> ' +
                '<span style="color:var(--text-secondary);">' + esc((a.at || '').slice(0, 16)) + ' ' + esc(a.by) + '</span><div>' + esc(a.note) + '</div>' +
                (a.next_action ? '<div style="color:var(--primary-color);">Next: ' + esc(a.next_action) + (a.next_on ? ' by ' + esc(a.next_on) : '') + '</div>' : '') + '</div>';
        }).join('') + '</div></div></div></div>';
    document.getElementById('lead-detail').scrollIntoView({ block: 'start', behavior: 'smooth' });
}
window.openLead = openLead;

async function leadPost(url, body) {
    var res = await fetch(url, { method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });
    var out = await res.json();
    showToast(out.message || out.detail, res.ok ? 'success' : 'error');
    if (res.ok) loadLeads();
    return res.ok ? out : null;
}

function leadMove(id, to) { leadPost('/api/leads/' + id + '/status', { status: to }); }
window.leadMove = leadMove;

async function leadEstimate(id) {
    var out = await leadPost('/api/leads/' + id + '/estimate');
    if (out && confirm(out.message + '\n\nOpen the estimate now?')) showView('estimates-view');
}
window.leadEstimate = leadEstimate;

function leadLose(id) {
    var why = prompt('Why was it lost? (price, eligibility, time...)');
    if (why === null || !why.trim()) return;
    var who = prompt('Who won it? (leave blank if not known)') || '';
    var at = parseFloat(prompt('At what price? (blank if not known)') || '') || 0;
    leadPost('/api/leads/' + id + '/status', { status: 'LOST', lost_reason: why, winning_bidder: who, winning_price: at });
}
window.leadLose = leadLose;

function leadDrop(id) {
    var why = prompt('Why is it being dropped?');
    if (why === null || !why.trim()) return;
    leadPost('/api/leads/' + id + '/status', { status: 'DROPPED', note: why });
}
window.leadDrop = leadDrop;

function leadNote(id) {
    var note = document.getElementById('lead-act-note').value;
    if (!note.trim()) { showToast('What happened?', 'error'); return; }
    leadPost('/api/leads/' + id + '/activities', { kind: document.getElementById('lead-act-kind').value, note: note,
        next_action: document.getElementById('lead-act-next').value, next_on: document.getElementById('lead-act-on').value });
}
window.leadNote = leadNote;

function leadEdit(id) {
    var l = id ? LEADS.rows.filter(function (x) { return x.id === id; })[0] || {} : {};
    LEADS.editing = l.id || null;
    document.getElementById('lead-form-title').textContent = l.id ? 'Edit ' + l.number : 'New tender';
    if (typeof fillCustomerNames === 'function') fillCustomerNames();
    var src = document.getElementById('lead-f-source');
    src.innerHTML = (LEADS.meta.sources || []).map(function (s) {
        return '<option' + (s === l.source ? ' selected' : '') + '>' + esc(s) + '</option>'; }).join('');
    var modes = document.getElementById('lead-f-emd_mode');
    modes.innerHTML = '<option value=""></option>' + (LEADS.meta.emd_modes || []).map(function (s) {
        return '<option' + (s === l.emd_mode ? ' selected' : '') + '>' + esc(s) + '</option>'; }).join('');
    ['title', 'customer_name', 'contact_person', 'phone', 'email', 'location', 'tender_reference', 'estimated_value',
     'site_visit_on', 'prebid_on', 'bid_due_on', 'emd_amount', 'emd_reference', 'emd_paid_on', 'notes'].forEach(function (k) {
        document.getElementById('lead-f-' + k).value = l[k] === undefined || l[k] === null || l[k] === 0 ? '' : l[k];
    });
    openModal('lead-form-modal');
    document.getElementById('lead-f-title').focus();
}
window.leadEdit = leadEdit;

async function leadSave() {
    var val = function (k) { return document.getElementById('lead-f-' + k).value; };
    var body = {};
    ['title', 'customer_name', 'contact_person', 'phone', 'email', 'location', 'source', 'tender_reference',
     'site_visit_on', 'prebid_on', 'bid_due_on', 'emd_mode', 'emd_reference', 'emd_paid_on', 'notes'].forEach(function (k) { body[k] = val(k); });
    body.estimated_value = parseFloat(val('estimated_value')) || 0;
    body.emd_amount = parseFloat(val('emd_amount')) || 0;
    var res = await fetch('/api/leads' + (LEADS.editing ? '/' + LEADS.editing : ''), {
        method: LEADS.editing ? 'PUT' : 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not save it', 'error'); return; }
    closeModal('lead-form-modal');
    showToast((out.message || 'Saved'), 'success');
    LEADS.current = out.lead.id;
    loadLeads();
}
window.leadSave = leadSave;
