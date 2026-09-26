/* ===========================================================================
   alerts.js - the bell, and where alerts are sent.

   The bell shows what has happened that somebody should know about - a bill
   waiting on a signature, money in, a gang to pay - and takes you to it. The
   Alerts section of Settings says who gets which by email or WhatsApp.
   =========================================================================== */

var ALERTS = { list: [], open: false, timer: null, settings: null };

async function refreshAlerts() {
    var badge = document.getElementById('alerts-badge');
    if (!badge) return;
    try {
        var res = await fetch('/api/alerts?limit=20', { credentials: 'include' });
        if (!res.ok) return;
        var d = await res.json();
        ALERTS.list = d.alerts || [];
        badge.textContent = d.unread > 99 ? '99+' : String(d.unread || '');
        badge.style.display = d.unread ? 'inline-block' : 'none';
        document.getElementById('alerts-bell').style.display = 'inline-flex';
        if (ALERTS.open) renderAlerts();
    } catch (e) { /* offline or signed out; try again next time */ }
}
window.refreshAlerts = refreshAlerts;

function startAlerts() {
    refreshAlerts();
    if (ALERTS.timer) return;
    // Once a minute while the tab is being looked at - not a request a second.
    ALERTS.timer = setInterval(function () { if (!document.hidden) refreshAlerts(); }, 60000);
}
window.startAlerts = startAlerts;

var ALERT_TONE = { money: 'var(--success-color)', action: 'var(--warning-color)', wrong: 'var(--danger-color)',
                   info: 'var(--text-secondary)' };

function renderAlerts() {
    var panel = document.getElementById('alerts-panel');
    panel.innerHTML = '<div style="display:flex;justify-content:space-between;align-items:center;padding:10px 14px;' +
        'border-bottom:1px solid var(--border-color);"><strong>Alerts</strong>' +
        '<button class="btn btn-sm btn-outline" onclick="alertsReadAll()">Mark all read</button></div>' +
        '<div style="max-height:420px;overflow-y:auto;">' +
        (ALERTS.list.map(function (a) {
            return '<div onclick="alertOpen(' + a.id + ')" style="cursor:pointer;padding:10px 14px;border-bottom:1px solid var(--border-color);' +
                (a.read ? 'opacity:.62;' : 'background:var(--primary-soft,rgba(99,102,241,.06));') + '">' +
                '<div style="display:flex;gap:8px;align-items:flex-start;">' +
                '<span style="width:8px;height:8px;border-radius:50%;margin-top:6px;flex-shrink:0;background:' +
                (ALERT_TONE[a.severity] || ALERT_TONE.info) + ';"></span><div style="min-width:0;">' +
                '<div style="font-weight:600;font-size:0.84rem;">' + esc(a.title) + '</div>' +
                (a.body ? '<div style="font-size:0.76rem;color:var(--text-secondary);white-space:pre-line;">' + esc(a.body.slice(0, 240)) + '</div>' : '') +
                '<div style="font-size:0.68rem;color:var(--text-secondary);margin-top:2px;">' + esc(a.created_at) +
                (a.sent_to ? ' &middot; sent to ' + esc(a.sent_to) : '') + '</div></div></div></div>';
        }).join('') || '<p style="padding:18px;color:var(--text-secondary);">Nothing yet. Bills waiting on a signature, money in and out, and the morning list appear here.</p>') +
        '</div>';
}

function toggleAlerts(ev) {
    if (ev) ev.stopPropagation();
    ALERTS.open = !ALERTS.open;
    var panel = document.getElementById('alerts-panel');
    panel.style.display = ALERTS.open ? 'block' : 'none';
    if (ALERTS.open) { renderAlerts(); refreshAlerts(); }
}
window.toggleAlerts = toggleAlerts;

document.addEventListener('click', function (e) {
    if (!ALERTS.open) return;
    var wrap = document.getElementById('alerts-wrap');
    if (wrap && !wrap.contains(e.target)) { ALERTS.open = false; document.getElementById('alerts-panel').style.display = 'none'; }
});

async function alertOpen(id) {
    var a = ALERTS.list.filter(function (x) { return x.id === id; })[0];
    await fetch('/api/alerts/read', { method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ids: [id] }) });
    ALERTS.open = false;
    document.getElementById('alerts-panel').style.display = 'none';
    if (a && a.view && typeof showView === 'function') showView(a.view);
    refreshAlerts();
}
window.alertOpen = alertOpen;

async function alertsReadAll() {
    await fetch('/api/alerts/read', { method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ all: true }) });
    refreshAlerts();
}
window.alertsReadAll = alertsReadAll;

/* --- Settings: who gets what ------------------------------------------------ */

async function loadAlertSettings() {
    var host = document.getElementById('alert-settings');
    if (!host) return;
    var res = await fetch('/api/alerts/settings', { credentials: 'include' });
    if (!res.ok) { host.innerHTML = ''; return; }
    var s = ALERTS.settings = await res.json();
    var row = function (k) {
        var on = s.channels[k] || [];
        var box = function (ch) {
            return '<input type="checkbox" data-kind="' + k + '" data-ch="' + ch + '"' + (on.indexOf(ch) >= 0 ? ' checked' : '') + '>';
        };
        return '<tr><td>' + esc(s.kinds[k]) + '</td><td style="text-align:center;">' + box('email') +
            '</td><td style="text-align:center;">' + box('whatsapp') + '</td></tr>';
    };
    host.innerHTML =
        '<div class="form-row">' +
        '<div class="form-group"><label>Email to</label><input id="al-emails" class="form-control" value="' + esc(s.emails.join(', ')) +
            '" placeholder="owner@..., accounts@..."><p style="font-size:0.72rem;color:var(--text-secondary);margin:3px 0 0;">' +
            (s.email_ready ? 'Sent from the Gmail connected above.' : 'Connect Gmail above for these to be sent.') + '</p></div>' +
        '<div class="form-group"><label>WhatsApp to</label><input id="al-wa" class="form-control" value="' + esc(s.whatsapp.join(', ')) +
            '" placeholder="98480 12345, ..."><p style="font-size:0.72rem;color:var(--text-secondary);margin:3px 0 0;">' +
            (s.whatsapp_ready ? 'Sent through your WhatsApp Business number.' : 'Needs a WhatsApp Business number - below.') + '</p></div>' +
        '</div>' +
        '<table class="data-table" style="margin:6px 0 12px;"><thead><tr><th>When</th><th style="text-align:center;">Email</th>' +
        '<th style="text-align:center;">WhatsApp</th></tr></thead><tbody>' + Object.keys(s.kinds).map(row).join('') + '</tbody></table>' +
        '<details style="margin-bottom:12px;"><summary style="cursor:pointer;font-size:0.84rem;">WhatsApp Business number</summary>' +
        '<p style="font-size:0.76rem;color:var(--text-secondary);">From Meta Business &rarr; WhatsApp &rarr; API setup: the phone number ID and a permanent access token.</p>' +
        '<div class="form-row"><div class="form-group"><label>Phone number ID</label><input id="al-waid" class="form-control" value="' + esc(s.wa_phone_id) + '"></div>' +
        '<div class="form-group"><label>Access token</label><input id="al-watok" type="password" class="form-control" placeholder="' +
            (s.wa_token_set ? 'saved - type to replace' : '') + '"></div></div></details>' +
        '<div style="display:flex;gap:8px;"><button class="btn btn-primary" onclick="saveAlertSettings()">Save</button>' +
        '<button class="btn btn-outline" onclick="testAlert()">Send a test</button></div>';
}
window.loadAlertSettings = loadAlertSettings;

async function saveAlertSettings() {
    var split = function (id) { return document.getElementById(id).value.split(/[,;]+/).map(function (x) { return x.trim(); }).filter(Boolean); };
    var channels = {};
    document.querySelectorAll('#alert-settings input[type=checkbox]').forEach(function (b) {
        channels[b.dataset.kind] = channels[b.dataset.kind] || [];
        if (b.checked) channels[b.dataset.kind].push(b.dataset.ch);
    });
    var body = { emails: split('al-emails'), whatsapp: split('al-wa'), channels: channels,
                 wa_phone_id: document.getElementById('al-waid').value.trim() };
    var tok = document.getElementById('al-watok').value.trim();
    if (tok) body.wa_token = tok;
    var res = await fetch('/api/alerts/settings', { method: 'PUT', credentials: 'include',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not save', 'error'); return; }
    showToast('Alert settings saved.', 'success');
    loadAlertSettings();
}
window.saveAlertSettings = saveAlertSettings;

async function testAlert() {
    var out = await (await fetch('/api/alerts/test', { method: 'POST', credentials: 'include' })).json();
    showToast(out.message || 'Sent.', 'success');
    refreshAlerts();
}
window.testAlert = testAlert;
