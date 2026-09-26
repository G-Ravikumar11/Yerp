/* ===========================================================================
   safety.js - incidents, toolbox talks and permits to work.
   =========================================================================== */

var SAFE = { tab: 'incidents', jobId: 0, data: null };

async function loadSafety() {
    var sel = document.getElementById('sf-job');
    if (!sel) return;
    if (!sel.options.length) {
        await fillJobPicker('sf-job');
        if (!sel.value && sel.options.length > 1) sel.selectedIndex = 1;
    }
    SAFE.jobId = parseInt(sel.value) || 0;
    var d = SAFE.data = await (await fetch('/api/safety' + (SAFE.jobId ? '?job_id=' + SAFE.jobId : ''), { credentials: 'include' })).json();
    var s = d.summary || {};
    document.getElementById('sf-stats').innerHTML =
        statCard('Days without a lost-time injury', s.days_without_lti === null ? 'none yet' : String(s.days_without_lti)) +
        statCard('Incidents this month', String(s.incidents_this_month || 0)) +
        statCard('Near misses reported', String(s.near_misses || 0)) +
        statCard('Toolbox talks this week', String(s.talks_this_week || 0)) +
        statCard('Permits live', String(s.active_permits || 0) +
            (s.expired_open ? ' <span style="font-size:0.72rem;color:var(--danger-color);">(' + s.expired_open + ' run out)</span>' : ''));
    document.querySelectorAll('#sf-tabs button').forEach(function (b) { b.classList.toggle('active', b.dataset.tab === SAFE.tab); });
    var host = document.getElementById('sf-body');
    if (SAFE.tab === 'incidents') {
        host.innerHTML = '<div class="table-responsive"><table class="data-table"><thead><tr><th>No.</th><th>When</th><th>Kind</th><th>What happened</th>' +
            '<th>Hurt</th><th>Status</th><th></th></tr></thead><tbody>' +
            (d.incidents.map(function (i) {
                return '<tr><td style="font-family:monospace;white-space:nowrap;">' + esc(i.number) + '</td><td>' + esc(i.happened_on) + ' ' + esc(i.happened_at) + '</td>' +
                    '<td style="' + (i.serious ? 'color:var(--danger-color);font-weight:600;' : '') + '">' + esc(i.kind) + '</td>' +
                    '<td style="max-width:320px;">' + esc(i.description.slice(0, 150)) + (i.location ? '<div style="font-size:0.72rem;color:var(--text-secondary);">' + esc(i.location) + '</div>' : '') +
                    (i.root_cause ? '<div style="font-size:0.72rem;color:var(--success-color);">Cause: ' + esc(i.root_cause) + ' &middot; Fix: ' + esc(i.corrective_action) + '</div>' : '') + '</td>' +
                    '<td>' + esc(i.injured_name) + (i.injury ? '<div style="font-size:0.72rem;">' + esc(i.injury) + (i.lost_days ? ', ' + i.lost_days + ' days lost' : '') + '</div>' : '') + '</td>' +
                    '<td style="white-space:nowrap;">' + statusPill(i.status, i.status === 'OPEN' ? (i.serious ? 'bad' : 'wait') : 'good') + '</td>' +
                    '<td class="text-right" style="white-space:nowrap;">' + (i.status === 'OPEN' ? '<button class="btn btn-sm btn-outline" onclick="sfClose(' + i.id + ')">Close</button> ' : '') +
                    '<button class="btn btn-sm btn-outline" onclick="openFiles(\'incident\',' + i.id + ',\'' + esc(i.number) + '\')">Photos</button></td></tr>';
            }).join('') || '<tr><td colspan="7" style="text-align:center;padding:24px;color:var(--text-secondary);">Nothing reported. A near miss written down is the cheapest lesson there is.</td></tr>') +
            '</tbody></table></div>';
    } else if (SAFE.tab === 'talks') {
        host.innerHTML = '<div class="table-responsive"><table class="data-table"><thead><tr><th>On</th><th>Topic</th><th>By</th><th>Attended</th></tr></thead><tbody>' +
            (d.talks.map(function (t) {
                return '<tr><td>' + esc(t.held_on) + '</td><td>' + esc(t.topic) + (t.notes ? '<div style="font-size:0.72rem;color:var(--text-secondary);">' + esc(t.notes) + '</div>' : '') + '</td>' +
                    '<td>' + esc(t.conducted_by) + '</td><td>' + t.attendees + (t.attendee_names ? '<div style="font-size:0.72rem;color:var(--text-secondary);">' + esc(t.attendee_names) + '</div>' : '') + '</td></tr>';
            }).join('') || '<tr><td colspan="4" style="text-align:center;padding:24px;color:var(--text-secondary);">No talks recorded.</td></tr>') +
            '</tbody></table></div>';
    } else {
        host.innerHTML = '<div class="table-responsive"><table class="data-table"><thead><tr><th>Permit</th><th>Kind</th><th>Where</th><th>Runs</th>' +
            '<th>Worker</th><th>Status</th><th></th></tr></thead><tbody>' +
            (d.permits.map(function (p) {
                var tone = p.expired ? 'bad' : p.status === 'ACTIVE' ? 'good' : 'calm';
                return '<tr><td style="font-family:monospace;white-space:nowrap;">' + esc(p.number) + '</td><td>' + esc(p.kind) + '</td><td>' + esc(p.location) + '</td>' +
                    '<td>' + esc(p.valid_from.slice(5)) + ' &rarr; ' + esc(p.valid_to.slice(5)) + '</td><td>' + esc(p.receiver) + '</td>' +
                    '<td style="white-space:nowrap;">' + statusPill(p.expired ? 'RUN OUT' : p.status, tone) + '</td><td class="text-right">' +
                    (p.status === 'ACTIVE' ? '<button class="btn btn-sm btn-outline" onclick="sfPermitClose(' + p.id + ')">Close</button>' : '') + '</td></tr>';
            }).join('') || '<tr><td colspan="7" style="text-align:center;padding:24px;color:var(--text-secondary);">No permits issued.</td></tr>') +
            '</tbody></table></div>';
    }
}
window.loadSafety = loadSafety;

function sfTab(t) { SAFE.tab = t; loadSafety(); }
window.sfTab = sfTab;

function sfNew() {
    if (!SAFE.jobId) { showToast('Pick the project first', 'error'); return; }
    if (SAFE.tab === 'talks') return sfTalk();
    if (SAFE.tab === 'permits') return sfPermit();
    document.getElementById('sfi-kind').innerHTML = SAFE.data.kinds.map(function (k) { return '<option>' + esc(k) + '</option>'; }).join('');
    ['sfi-where', 'sfi-what', 'sfi-who', 'sfi-injury', 'sfi-treat', 'sfi-lost', 'sfi-action', 'sfi-time'].forEach(function (id) { document.getElementById(id).value = ''; });
    document.getElementById('sfi-date').value = localDate(new Date());
    openModal('sfi-modal');
}
window.sfNew = sfNew;

async function sfReport() {
    var v = function (id) { return document.getElementById(id).value; };
    var res = await fetch('/api/safety/incidents', { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_id: SAFE.jobId, kind: v('sfi-kind'), happened_on: v('sfi-date'), happened_at: v('sfi-time'),
                               location: v('sfi-where'), description: v('sfi-what'), injured_name: v('sfi-who'), injury: v('sfi-injury'),
                               treatment: v('sfi-treat'), lost_days: parseFloat(v('sfi-lost')) || 0, immediate_action: v('sfi-action') }) });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not report it', 'error'); return; }
    showToast(out.incident.number + ' reported.', 'success');
    closeModal('sfi-modal');
    loadSafety();
}
window.sfReport = sfReport;

async function sfClose(id) {
    var cause = prompt('Why did it happen? (the root cause)');
    if (!cause) return;
    var fix = prompt('What stops it happening again?');
    if (!fix) return;
    var res = await fetch('/api/safety/incidents/' + id + '/close', { method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ root_cause: cause, corrective_action: fix }) });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not close it', 'error'); return; }
    showToast(out.incident.number + ' closed.', 'success');
    loadSafety();
}
window.sfClose = sfClose;

async function sfTalk() {
    var topic = prompt('Toolbox talk - the topic:');
    if (!topic) return;
    var names = prompt('Who stood through it? (names, separated by commas - or just the number)', '') || '';
    var n = /^\s*\d+\s*$/.test(names) ? parseInt(names) : 0;
    var res = await fetch('/api/safety/talks', { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_id: SAFE.jobId, topic: topic, attendees: n, attendee_names: n ? '' : names }) });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not record it', 'error'); return; }
    showToast('Talk recorded.', 'success');
    loadSafety();
}

function sfPermit() {
    var kinds = Object.keys(SAFE.data.permit_kinds);
    document.getElementById('sfp-kind').innerHTML = kinds.map(function (k) { return '<option>' + esc(k) + '</option>'; }).join('');
    ['sfp-where', 'sfp-what', 'sfp-who'].forEach(function (id) { document.getElementById(id).value = ''; });
    var now = new Date(), end = new Date(now.getTime() + 8 * 3600 * 1000);
    var dt = function (d) { return localDate(d) + 'T' + String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0'); };
    document.getElementById('sfp-from').value = dt(now);
    document.getElementById('sfp-to').value = dt(end);
    sfPermitKind();
    openModal('sfp-modal');
}

function sfPermitKind() {
    var k = document.getElementById('sfp-kind').value;
    document.getElementById('sfp-checks').innerHTML = (SAFE.data.permit_kinds[k] || []).map(function (item, n) {
        return '<label style="display:flex;gap:8px;align-items:center;font-size:0.86rem;margin:4px 0;"><input type="checkbox" data-item="' + esc(item) + '"> ' + esc(item) + '</label>';
    }).join('');
}
window.sfPermitKind = sfPermitKind;

async function sfPermitIssue() {
    var v = function (id) { return document.getElementById(id).value; };
    var pre = [];
    document.querySelectorAll('#sfp-checks input').forEach(function (c) { pre.push({ item: c.dataset.item, done: c.checked }); });
    var res = await fetch('/api/safety/permits', { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_id: SAFE.jobId, kind: v('sfp-kind'), location: v('sfp-where'), description: v('sfp-what'),
                               receiver: v('sfp-who'), valid_from: v('sfp-from'), valid_to: v('sfp-to'), precautions: pre }) });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Not issued', 'error'); return; }
    showToast(out.permit.number + ' issued, until ' + out.permit.valid_to + '.', 'success');
    closeModal('sfp-modal');
    loadSafety();
}
window.sfPermitIssue = sfPermitIssue;

async function sfPermitClose(id) {
    var note = prompt('Closing the permit - is the area safe and the work stopped? (a note)', 'Work complete, area cleared');
    if (note === null) return;
    var res = await fetch('/api/safety/permits/' + id + '/close', { method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ note: note }) });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not close it', 'error'); return; }
    showToast(out.permit.number + ' closed.', 'success');
    loadSafety();
}
window.sfPermitClose = sfPermitClose;
