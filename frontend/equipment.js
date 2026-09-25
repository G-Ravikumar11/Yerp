/* ===========================================================================
   equipment.js - the plant and machinery register.

   Where each machine is, what it did yesterday, what it burned, and whether
   it is due a service - on one screen, with the four things done to a
   machine (move it, log its day, service it, look at it) one click away.
   What it costs lands on the project it worked for, on its own.
   =========================================================================== */

var EQP = { assets: [], jobs: [], cats: [], current: null, editing: null };

var EQP_TONE = { 'Available': 'calm', 'Deployed': 'good', 'Under repair': 'bad', 'Disposed': 'calm' };

async function eqpJobs() {
    try {
        var d = await (await fetch('/api/jobs', { credentials: 'include' })).json();
        EQP.jobs = (d.jobs || d || []).filter(function (j) {
            return ['complete', 'cancelled'].indexOf(j.status) < 0; });
    } catch (e) { EQP.jobs = []; }
}

async function loadEquipment() {
    var body = document.getElementById('eqp-body');
    if (!body) return;
    var status = (document.getElementById('eqp-status') || {}).value || '';
    var d = await (await fetch('/api/assets' + (status ? '?status=' + encodeURIComponent(status) : ''),
                               { credentials: 'include' })).json();
    EQP.assets = d.assets || [];
    EQP.cats = d.categories || [];
    var s = d.summary || {};
    document.getElementById('eqp-stats').innerHTML =
        statCard('Machines', String(s.machines || 0)) +
        statCard('On sites', String(s.deployed || 0)) +
        statCard('Idle in the yard', String(s.idle_in_yard || 0)) +
        statCard('Service due', String(s.service_due || 0) +
            (s.service_soon ? ' <span style="font-size:0.7rem;color:var(--text-secondary);">+' + s.service_soon + ' soon</span>' : '')) +
        statCard('Cost to date', formatCurrency(s.cost_to_date || 0));
    body.innerHTML = EQP.assets.length ? EQP.assets.map(function (a, i) {
        var svc = a.service || {};
        var flag = svc.due ? '<div style="font-size:0.7rem;color:var(--danger-color);font-weight:600;">' +
                esc(svc.reasons.join('; ')) + '</div>'
            : svc.soon ? '<div style="font-size:0.7rem;color:var(--warning-color);">' + esc(svc.reasons.join('; ')) + '</div>'
            : '';
        var acts = a.status === 'Disposed' ? '' :
            '<button class="btn btn-sm btn-outline" onclick="eqpMove(' + i + ')">' +
                (a.current_job_id ? 'Move' : 'Deploy') + '</button> ' +
            (a.status === 'Deployed' ? '<button class="btn btn-sm btn-primary" onclick="eqpLog(' + i + ')">Log day</button> ' : '') +
            (a.status === 'Under repair'
                ? '<button class="btn btn-sm btn-primary" onclick="eqpBack(' + a.id + ')">Back at work</button> '
                : '<button class="btn btn-sm btn-outline" onclick="eqpService(' + i + ')">Service</button> ');
        return '<tr>' +
            '<td style="font-family:monospace;font-weight:600;">' + esc(a.code) + '</td>' +
            '<td><a href="#" onclick="event.preventDefault();eqpOpen(' + a.id + ')" style="font-weight:600;">' + esc(a.name) + '</a>' +
                '<div style="font-size:0.72rem;color:var(--text-secondary);">' + esc(a.category) +
                (a.reg_no ? ' &middot; ' + esc(a.reg_no) : '') + ' &middot; ' + esc(a.ownership) +
                (a.ownership === 'Hired' ? ' @ ' + formatCurrency(a.hire_rate) + '/' + esc(a.hire_basis).toLowerCase() : '') +
                '</div></td>' +
            '<td style="white-space:nowrap;">' + statusPill(a.status, EQP_TONE[a.status] || 'calm') + '</td>' +
            '<td>' + esc(a.current_job || 'Yard') + '</td>' +
            '<td class="text-right" style="white-space:nowrap;">' + (a.meter_reading || 0).toLocaleString('en-IN') + ' ' +
                esc((a.meter_unit || '').toLowerCase()) + flag + '</td>' +
            '<td class="text-right" style="white-space:nowrap;">' + formatCurrency(a.cost_to_date) + '</td>' +
            '<td class="text-right" style="white-space:nowrap;">' + acts +
                '<button class="btn btn-sm btn-outline" onclick="eqpEdit(' + i + ')">Edit</button></td></tr>';
    }).join('') : '<tr><td colspan="7" style="text-align:center;padding:26px;color:var(--text-secondary);">' +
        'No machines on the register yet. Add what the business owns, and what it hires in.</td></tr>';
    if (EQP.current) eqpOpen(EQP.current);
}
window.loadEquipment = loadEquipment;

/* --- The machine itself ---------------------------------------------------- */

function eqpEdit(i) {
    var a = (i !== undefined && EQP.assets[i]) || {};
    EQP.editing = a.id || null;
    document.getElementById('eqp-form-title').textContent = a.id ? 'Edit ' + a.code : 'Add a machine';
    var cat = document.getElementById('eqp-f-category');
    cat.innerHTML = (EQP.cats.length ? EQP.cats : ['Other']).map(function (c) {
        return '<option' + (c === (a.category || 'Earthmoving') ? ' selected' : '') + '>' + esc(c) + '</option>';
    }).join('');
    var v = { name: a.name, make: a.make, model: a.model, reg_no: a.reg_no, serial_no: a.serial_no,
              ownership: a.ownership || 'Owned', hired_from: a.hired_from, hire_rate: a.hire_rate || '',
              hire_basis: a.hire_basis || 'Day', meter_unit: a.meter_unit || 'Hours',
              meter_reading: a.meter_reading || '', service_every: a.service_every || '',
              service_every_days: a.service_every_days || '', last_service_on: a.last_service_on,
              last_service_meter: a.id ? (a.last_service_meter || 0) : '',
              purchase_date: a.purchase_date, purchase_value: a.purchase_value || '',
              insurance_until: a.insurance_until, fitness_until: a.fitness_until, notes: a.notes };
    Object.keys(v).forEach(function (k) {
        var el = document.getElementById('eqp-f-' + k);
        if (el) el.value = v[k] === undefined || v[k] === null ? '' : v[k];
    });
    document.getElementById('eqp-f-meter_reading').disabled = !!a.id;
    eqpOwnership();
    openModal('eqp-form-modal');
    document.getElementById('eqp-f-name').focus();
}
window.eqpEdit = eqpEdit;

function eqpOwnership() {
    var hired = document.getElementById('eqp-f-ownership').value === 'Hired';
    document.getElementById('eqp-hire-fields').style.display = hired ? '' : 'none';
    document.getElementById('eqp-own-fields').style.display = hired ? 'none' : '';
}
window.eqpOwnership = eqpOwnership;

async function eqpSave() {
    var val = function (k) { var e = document.getElementById('eqp-f-' + k); return e ? e.value : ''; };
    var num = function (k) { return parseFloat(val(k)) || 0; };
    var body = { name: val('name'), category: val('category'), ownership: val('ownership'),
        make: val('make'), model: val('model'), reg_no: val('reg_no'), serial_no: val('serial_no'),
        hired_from: val('hired_from'), hire_rate: num('hire_rate'), hire_basis: val('hire_basis'),
        meter_unit: val('meter_unit'), meter_reading: num('meter_reading'),
        service_every: num('service_every'), service_every_days: parseInt(val('service_every_days')) || 0,
        last_service_on: val('last_service_on'), purchase_date: val('purchase_date'),
        // Left blank on a new machine, the service count starts from today's
        // reading; given, a service already overdue shows as overdue.
        last_service_meter: val('last_service_meter') === '' ? null : num('last_service_meter'),
        purchase_value: num('purchase_value'), insurance_until: val('insurance_until'),
        fitness_until: val('fitness_until'), notes: val('notes') };
    var res = await fetch('/api/assets' + (EQP.editing ? '/' + EQP.editing : ''), {
        method: EQP.editing ? 'PUT' : 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not save it', 'error'); return; }
    closeModal('eqp-form-modal');
    showToast(out.code + ' ' + out.name + ' saved', 'success');
    loadEquipment();
}
window.eqpSave = eqpSave;

/* --- Move, log, service ------------------------------------------------------ */

async function eqpMove(i) {
    var a = EQP.assets[i];
    await eqpJobs();
    EQP.acting = a;
    document.getElementById('eqp-move-title').textContent = (a.current_job_id ? 'Move ' : 'Deploy ') + a.code + ' ' + a.name;
    document.getElementById('eqp-move-to').innerHTML =
        (a.current_job_id ? '<option value="">Back to the yard</option>' : '') +
        EQP.jobs.filter(function (j) { return j.id !== a.current_job_id; }).map(function (j) {
            return '<option value="' + j.id + '">' + esc((j.number || '') + ' — ' + j.name) + '</option>';
        }).join('');
    document.getElementById('eqp-move-date').value = localDate(new Date());
    document.getElementById('eqp-move-note').value = '';
    openModal('eqp-move-modal');
}
window.eqpMove = eqpMove;

async function eqpMoveSave() {
    var a = EQP.acting;
    var to = parseInt(document.getElementById('eqp-move-to').value) || null;
    var res = await fetch('/api/assets/' + a.id + '/move', {
        method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ to_job_id: to, moved_on: document.getElementById('eqp-move-date').value,
                               note: document.getElementById('eqp-move-note').value }) });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not move it', 'error'); return; }
    closeModal('eqp-move-modal');
    showToast(out.message, 'success');
    loadEquipment();
}
window.eqpMoveSave = eqpMoveSave;

function eqpLog(i) {
    var a = EQP.assets[i];
    EQP.acting = a;
    document.getElementById('eqp-log-title').textContent = a.code + ' ' + a.name + ' — ' + a.current_job;
    ['hours', 'idle', 'litres', 'meter', 'operator', 'work'].forEach(function (k) {
        document.getElementById('eqp-log-' + k).value = ''; });
    document.getElementById('eqp-log-date').value = localDate(new Date());
    document.getElementById('eqp-log-rate').value = localStorage.getItem('eqp-fuel-rate') || '';
    document.getElementById('eqp-log-meter').placeholder = 'now ' + (a.meter_reading || 0);
    document.getElementById('eqp-log-hint').textContent = a.ownership === 'Hired'
        ? 'Hire is charged on its terms: ' + formatCurrency(a.hire_rate) + ' per ' + (a.hire_basis || '').toLowerCase() +
          (a.hire_basis === 'Month' ? ', spread over 26 working days.' : '.')
        : 'An owned machine costs the site its diesel and its repairs.';
    openModal('eqp-log-modal');
    document.getElementById('eqp-log-hours').focus();
}
window.eqpLog = eqpLog;

async function eqpLogSave() {
    var a = EQP.acting;
    var val = function (k) { return document.getElementById('eqp-log-' + k).value; };
    var rate = parseFloat(val('rate')) || 0;
    try { if (rate) localStorage.setItem('eqp-fuel-rate', rate); } catch (e) {}
    var meter = val('meter');
    var res = await fetch('/api/assets/' + a.id + '/logs', {
        method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ log_date: val('date'), hours_worked: parseFloat(val('hours')) || 0,
            idle_hours: parseFloat(val('idle')) || 0, fuel_litres: parseFloat(val('litres')) || 0,
            fuel_rate: rate, meter_reading: meter === '' ? null : parseFloat(meter),
            operator: val('operator'), work_done: val('work') }) });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not log it', 'error'); return; }
    closeModal('eqp-log-modal');
    showToast(out.message + ' Cost ' + formatCurrency(out.cost) + '.', out.service && out.service.due ? 'warning' : 'success');
    loadEquipment();
}
window.eqpLogSave = eqpLogSave;

function eqpService(i) {
    var a = EQP.assets[i];
    EQP.acting = a;
    document.getElementById('eqp-svc-title').textContent = a.code + ' ' + a.name;
    ['desc', 'vendor', 'parts', 'labour', 'down', 'meter'].forEach(function (k) {
        document.getElementById('eqp-svc-' + k).value = ''; });
    document.getElementById('eqp-svc-kind').value = (a.service || {}).due ? 'Preventive' : 'Repair';
    document.getElementById('eqp-svc-date').value = localDate(new Date());
    document.getElementById('eqp-svc-meter').placeholder = 'now ' + (a.meter_reading || 0);
    document.getElementById('eqp-svc-off').checked = false;
    openModal('eqp-svc-modal');
}
window.eqpService = eqpService;

async function eqpServiceSave() {
    var a = EQP.acting;
    var val = function (k) { return document.getElementById('eqp-svc-' + k).value; };
    var meter = val('meter');
    var res = await fetch('/api/assets/' + a.id + '/services', {
        method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ service_on: val('date'), kind: val('kind'), description: val('desc'),
            vendor: val('vendor'), parts_cost: parseFloat(val('parts')) || 0,
            labour_cost: parseFloat(val('labour')) || 0, downtime_hours: parseFloat(val('down')) || 0,
            meter_at_service: meter === '' ? null : parseFloat(meter),
            out_of_service: document.getElementById('eqp-svc-off').checked }) });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not record it', 'error'); return; }
    closeModal('eqp-svc-modal');
    showToast(out.message, 'success');
    loadEquipment();
}
window.eqpServiceSave = eqpServiceSave;

async function eqpBack(id) {
    var res = await fetch('/api/assets/' + id + '/back-in-service', { method: 'POST', credentials: 'include' });
    var out = await res.json();
    showToast(out.message || out.detail, res.ok ? 'success' : 'error');
    loadEquipment();
}
window.eqpBack = eqpBack;

/* --- One machine's history ---------------------------------------------------- */

async function eqpOpen(id) {
    EQP.current = id;
    var host = document.getElementById('eqp-detail');
    var d = await (await fetch('/api/assets/' + id, { credentials: 'include' })).json();
    var svc = d.service || {};
    host.innerHTML = '<div class="widget" style="margin-top:18px;">' +
        '<div class="widget-header"><h3>' + esc(d.code + ' ' + d.name) + '</h3>' +
        '<button class="btn btn-sm btn-outline" onclick="EQP.current=null;document.getElementById(\'eqp-detail\').innerHTML=\'\'">Close</button></div>' +
        '<div style="padding:14px 18px;">' +
        '<div class="stats-grid">' +
        statCard('Where', esc(d.current_job || 'Yard')) +
        statCard('Utilisation', d.utilisation_percent + '%') +
        statCard('Diesel', d.litres_per_hour + ' L/h') +
        statCard('Cost to date', formatCurrency(d.cost_to_date)) + '</div>' +
        (svc.reasons && svc.reasons.length ? '<div style="margin:12px 0;padding:10px 12px;border-radius:8px;border:1px solid var(--' +
            (svc.due ? 'danger' : 'warning') + '-color);font-size:0.84rem;">' + esc(svc.reasons.join('; ')) + '</div>' : '') +
        '<h4 style="margin:16px 0 8px;font-size:0.9rem;">Daily log</h4>' +
        '<div class="table-responsive"><table class="data-table"><thead><tr><th>Date</th><th>Site</th>' +
        '<th class="text-right">Worked h</th><th class="text-right">Idle h</th><th class="text-right">Diesel L</th>' +
        '<th class="text-right">Cost ₹</th><th>Operator</th><th>Work</th></tr></thead><tbody>' +
        (d.logs.length ? d.logs.map(function (l) {
            return '<tr><td>' + esc(l.log_date) + '</td><td>' + esc(l.job) + '</td>' +
                '<td class="text-right">' + l.hours_worked + '</td><td class="text-right">' + l.idle_hours + '</td>' +
                '<td class="text-right">' + l.fuel_litres + '</td>' +
                '<td class="text-right">' + formatCurrency(l.fuel_cost + l.hire_cost) + '</td>' +
                '<td>' + esc(l.operator) + '</td><td>' + esc(l.work_done) + '</td></tr>';
        }).join('') : '<tr><td colspan="8" style="text-align:center;padding:16px;color:var(--text-secondary);">No days logged.</td></tr>') +
        '</tbody></table></div>' +
        '<h4 style="margin:16px 0 8px;font-size:0.9rem;">Services and repairs</h4>' +
        '<div class="table-responsive"><table class="data-table"><thead><tr><th>Date</th><th>Kind</th><th>What</th>' +
        '<th>By</th><th class="text-right">Meter</th><th class="text-right">Down h</th><th class="text-right">Cost ₹</th></tr></thead><tbody>' +
        (d.services.length ? d.services.map(function (s) {
            return '<tr><td>' + esc(s.service_on) + '</td><td>' + esc(s.kind) + '</td><td>' + esc(s.description) + '</td>' +
                '<td>' + esc(s.vendor) + '</td><td class="text-right">' + (s.meter_at_service || '') + '</td>' +
                '<td class="text-right">' + (s.downtime_hours || '') + '</td>' +
                '<td class="text-right">' + formatCurrency(s.total_cost) + '</td></tr>';
        }).join('') : '<tr><td colspan="7" style="text-align:center;padding:16px;color:var(--text-secondary);">No services recorded.</td></tr>') +
        '</tbody></table></div>' +
        '<h4 style="margin:16px 0 8px;font-size:0.9rem;">Movements</h4>' +
        (d.moves.length ? '<div style="font-size:0.84rem;">' + d.moves.map(function (m) {
            return '<div style="padding:3px 0;">' + esc(m.moved_on) + ' &nbsp; ' + esc(m.from) + ' &rarr; <strong>' +
                esc(m.to) + '</strong>' + (m.note ? ' <span style="color:var(--text-secondary);">' + esc(m.note) + '</span>' : '') + '</div>';
        }).join('') + '</div>' : '<p style="color:var(--text-secondary);font-size:0.84rem;">Never moved.</p>') +
        '</div></div>';
    host.scrollIntoView({ block: 'start', behavior: 'smooth' });
}
window.eqpOpen = eqpOpen;
