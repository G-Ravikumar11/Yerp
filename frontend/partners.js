/* ===========================================================================
   partners.js - who at which gang or supplier can sign in to the partner
   portal, from Settings.
   =========================================================================== */

var PARTNERS = { data: null };

async function loadPortalAccess() {
    var host = document.getElementById('portal-access');
    if (!host) return;
    var d = PARTNERS.data = await (await fetch('/api/portal-access', { credentials: 'include' })).json();
    var link = location.origin + '/portal.html';
    host.innerHTML =
        '<p style="font-size:0.84rem;color:var(--text-secondary);margin:0 0 12px;">Gangs and suppliers sign in at ' +
        '<a href="' + link + '" target="_blank" rel="noopener">' + esc(link) + '</a> to see their orders, bills, payments and ' +
        'statement. Suppliers can send their invoices in; they arrive in Supplier Bills as drafts.</p>' +
        '<div class="form-row" style="align-items:end;">' +
            '<div class="form-group"><label>Who</label><select id="pa-type" class="form-control" onchange="portalParties()">' +
                '<option value="contractor">Subcontractor</option><option value="supplier">Supplier</option></select></div>' +
            '<div class="form-group" style="flex:2;"><label>Which</label><select id="pa-party" class="form-control" onchange="portalPartyPicked()"></select></div>' +
        '</div><div class="form-row" style="align-items:end;">' +
            '<div class="form-group"><label>Their name</label><input id="pa-name" class="form-control"></div>' +
            '<div class="form-group" style="flex:2;"><label>Their email (they sign in with it)</label><input id="pa-email" type="email" class="form-control"></div>' +
            '<div class="form-group" style="flex:0 0 auto;"><button class="btn btn-primary" onclick="portalInvite()">Invite</button></div>' +
        '</div><div id="pa-link"></div>' +
        (d.users.length ? '<div class="table-responsive" style="margin-top:12px;"><table class="data-table"><thead><tr><th>Who</th><th>Of</th>' +
            '<th>Last signed in</th><th></th></tr></thead><tbody>' + d.users.map(function (u) {
                var st = !u.is_active ? statusPill('off', 'calm') : u.has_password ? statusPill('active', 'good')
                    : u.invite_open ? statusPill('invited', 'wait') : statusPill('link ran out', 'bad');
                return '<tr><td>' + esc(u.name || u.email) + '<div style="font-size:0.74rem;color:var(--text-secondary);">' + esc(u.email) + '</div></td>' +
                    '<td>' + esc(u.party) + '<div style="font-size:0.74rem;color:var(--text-secondary);">' +
                        (u.party_type === 'contractor' ? 'subcontractor' : 'supplier') + '</div></td>' +
                    '<td style="white-space:nowrap;">' + esc(u.last_login ? u.last_login.slice(0, 16) : '—') + ' ' + st + '</td>' +
                    '<td class="text-right" style="white-space:nowrap;">' +
                        (u.is_active ? '<button class="btn btn-sm btn-outline" onclick="portalReinvite(' + u.id + ')">New link</button> ' +
                            '<button class="btn btn-sm btn-outline" onclick="portalSwitch(' + u.id + ',\'disable\')">Turn off</button>'
                        : '<button class="btn btn-sm btn-outline" onclick="portalSwitch(' + u.id + ',\'enable\')">Turn on</button>') + '</td></tr>';
            }).join('') + '</tbody></table></div>' : '');
    portalParties();
}
window.loadPortalAccess = loadPortalAccess;

function portalParties() {
    var type = document.getElementById('pa-type').value;
    var list = type === 'contractor' ? PARTNERS.data.contractors : PARTNERS.data.suppliers;
    document.getElementById('pa-party').innerHTML = list.length
        ? list.map(function (p) { return '<option value="' + p.id + '">' + esc(p.name) + '</option>'; }).join('')
        : '<option value="">None on the list yet</option>';
    portalPartyPicked();
}
window.portalParties = portalParties;

function portalPartyPicked() {
    var type = document.getElementById('pa-type').value;
    var id = parseInt(document.getElementById('pa-party').value) || 0;
    var list = type === 'contractor' ? PARTNERS.data.contractors : PARTNERS.data.suppliers;
    var p = list.find(function (x) { return x.id === id; });
    document.getElementById('pa-name').value = p ? p.contact : '';
    document.getElementById('pa-email').value = p ? p.email : '';
}
window.portalPartyPicked = portalPartyPicked;

function portalShowLink(out) {
    var text = 'Your partner portal login: ' + out.invite_url;
    document.getElementById('pa-link').innerHTML =
        '<div style="margin-top:10px;padding:10px 12px;border:1px solid var(--border-color);border-radius:8px;font-size:0.84rem;">' +
        (out.emailed ? 'Sent by email. ' : 'Mail is not connected, so send them this link yourself. ') +
        'It works once, for seven days:<div style="display:flex;gap:6px;margin-top:6px;">' +
        '<input class="form-control" readonly value="' + esc(out.invite_url) + '" onclick="this.select()">' +
        '<button class="btn btn-sm btn-outline" onclick="navigator.clipboard.writeText(\'' + esc(out.invite_url) + '\');showToast(\'Copied\',\'success\')">Copy</button>' +
        '<a class="btn btn-sm btn-outline" target="_blank" rel="noopener" href="https://wa.me/?text=' + encodeURIComponent(text) + '">WhatsApp</a></div></div>';
}

async function portalInvite() {
    var res = await fetch('/api/portal-access', { method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ party_type: document.getElementById('pa-type').value,
                               party_id: parseInt(document.getElementById('pa-party').value) || 0,
                               name: document.getElementById('pa-name').value,
                               email: document.getElementById('pa-email').value }) });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Not invited', 'error'); return; }
    showToast(out.message, 'success');
    await loadPortalAccess();
    portalShowLink(out);
}
window.portalInvite = portalInvite;

async function portalReinvite(id) {
    var res = await fetch('/api/portal-access/' + id + '/reinvite', { method: 'POST', credentials: 'include' });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Not done', 'error'); return; }
    await loadPortalAccess();
    portalShowLink(out);
}
window.portalReinvite = portalReinvite;

async function portalSwitch(id, action) {
    var res = await fetch('/api/portal-access/' + id + '/' + action, { method: 'POST', credentials: 'include' });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Not done', 'error'); return; }
    showToast(out.message, 'success');
    loadPortalAccess();
}
window.portalSwitch = portalSwitch;
