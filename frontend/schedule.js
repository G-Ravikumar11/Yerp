/* ===========================================================================
   schedule.js - the programme, as bars against today.

   Each activity a bar across its planned dates, filled as far as it is done,
   with its forecast finish drawn past it when it is slipping - and the
   S-curve of planned against actual underneath. Activities tied to a work
   order line fill themselves from the measurement book.
   =========================================================================== */

var SCH = { job: null, data: null, jobs: [], editing: null };

async function loadSchedule() {
    var pick = document.getElementById('sch-job');
    if (!pick) return;
    if (!SCH.jobs.length) {
        var d = await (await fetch('/api/jobs', { credentials: 'include' })).json();
        SCH.jobs = (d.jobs || d || []);
        pick.innerHTML = SCH.jobs.map(function (j) {
            return '<option value="' + j.id + '">' + esc((j.number || '') + ' — ' + j.name) + '</option>'; }).join('');
        var ov = await (await fetch('/api/schedule-overview', { credentials: 'include' })).json();
        if ((ov.projects || []).length) pick.value = ov.projects[0].job_id;
    }
    SCH.job = parseInt(pick.value) || null;
    if (!SCH.job) {
        document.getElementById('sch-body').innerHTML = '<p style="padding:24px;color:var(--text-secondary);">No projects yet.</p>';
        return;
    }
    SCH.data = await (await fetch('/api/jobs/' + SCH.job + '/schedule', { credentials: 'include' })).json();
    drawSchedule();
}
window.loadSchedule = loadSchedule;

function drawSchedule() {
    var d = SCH.data, s = d.summary;
    var v = s.variance;
    document.getElementById('sch-stats').innerHTML =
        statCard('Planned by today', s.planned_percent + '%') +
        statCard('Done', s.actual_percent + '%') +
        statCard('Ahead / behind', '<span style="color:var(--' + (v < -5 ? 'danger' : v < 0 ? 'warning' : 'success') + '-color);">' +
            (v > 0 ? '+' : '') + v + ' pts</span>') +
        statCard('Late activities', String(s.late) + (s.behind ? ' <span style="font-size:0.7rem;color:var(--text-secondary);">+' + s.behind + ' behind</span>' : '')) +
        statCard('Finishes', (s.forecast_finish || '—') + (s.slip_days > 0 ? ' <span style="font-size:0.7rem;color:var(--danger-color);">' +
            s.slip_days + ' days late</span>' : ''));
    var acts = d.activities;
    if (!acts.length) {
        document.getElementById('sch-body').innerHTML = '<div class="widget"><div style="padding:24px;color:var(--text-secondary);">' +
            'No programme yet. Add activities, or draw one from a work order: each line becomes an activity whose progress comes from the measurement book.</div></div>';
        return;
    }
    var dates = [];
    acts.forEach(function (a) { dates.push(a.planned_start, a.planned_finish, a.forecast_finish); });
    dates = dates.filter(Boolean).sort();
    var t0 = new Date(dates[0]), t1 = new Date(dates[dates.length - 1]);
    var today = new Date(localDate(new Date()));
    if (today > t1) t1 = today;
    var span = Math.max(1, (t1 - t0) / 86400000 + 1);
    var pos = function (iso) { return ((new Date(iso) - t0) / 86400000) / span * 100; };
    var todayAt = pos(localDate(new Date()));
    var tone = { done: 'var(--success-color)', late: 'var(--danger-color)', behind: 'var(--warning-color)',
                 'on track': 'var(--primary-color)', 'not started': '#94a3b8' };
    var rows = acts.map(function (a) {
        var left = pos(a.planned_start), width = Math.max(0.8, pos(a.planned_finish) - left + 100 / span);
        var slip = a.forecast_finish && a.forecast_finish > a.planned_finish
            ? '<div title="Forecast finish ' + esc(a.forecast_finish) + '" style="position:absolute;top:9px;height:6px;left:' +
              (left + width) + '%;width:' + Math.max(0.5, pos(a.forecast_finish) - left - width + 100 / span) +
              '%;background:repeating-linear-gradient(90deg,var(--danger-color) 0 4px,transparent 4px 7px);opacity:.8;"></div>' : '';
        return '<tr>' +
            '<td style="white-space:nowrap;font-family:monospace;font-size:0.76rem;">' + esc(a.code) + '</td>' +
            '<td style="min-width:200px;"><a href="#" onclick="event.preventDefault();schEdit(' + a.id + ')" style="font-weight:600;">' + esc(a.name) + '</a>' +
                '<div style="font-size:0.7rem;color:var(--text-secondary);">' + esc(a.planned_start) + ' → ' + esc(a.planned_finish) +
                (a.depends_on ? ' · after ' + esc(a.depends_on) : '') + ' · ' + esc(a.progress_from) + '</div></td>' +
            '<td class="text-right" style="white-space:nowrap;">' + a.actual_percent + '%<div style="font-size:0.68rem;color:var(--text-secondary);">plan ' + a.planned_percent + '%</div></td>' +
            '<td style="min-width:360px;position:relative;padding:0 6px;">' +
                '<div style="position:relative;height:24px;">' +
                '<div style="position:absolute;top:0;bottom:0;left:' + todayAt + '%;width:1px;background:var(--danger-color);opacity:.5;"></div>' +
                '<div style="position:absolute;top:5px;height:14px;left:' + left + '%;width:' + width + '%;background:var(--border-color);border-radius:4px;overflow:hidden;">' +
                    '<div style="height:100%;width:' + Math.min(100, a.actual_percent) + '%;background:' + (tone[a.state] || 'var(--primary-color)') + ';"></div></div>' +
                slip + '</div></td>' +
            '<td style="white-space:nowrap;font-size:0.76rem;color:' + (tone[a.state] || '') + ';">' + esc(a.state) +
                (a.slip_days > 0 ? '<div style="font-size:0.68rem;">+' + a.slip_days + ' days</div>' : '') + '</td>' +
            '<td class="text-right">' + (a.work_order_line_id ? '' :
                '<button class="btn btn-sm btn-outline" onclick="schProgress(' + a.id + ')">Progress</button>') + '</td></tr>';
    }).join('');
    document.getElementById('sch-body').innerHTML =
        '<div class="widget"><div class="table-responsive"><table class="data-table">' +
        '<thead><tr><th>Code</th><th>Activity</th><th class="text-right">Done</th>' +
        '<th>' + esc(dates[0]) + ' <span style="float:right;">' + esc(localDate(t1)) + '</span></th><th>State</th><th></th></tr></thead>' +
        '<tbody>' + rows + '</tbody></table></div></div>' +
        schCurve(d.curve);
}

function schCurve(curve) {
    if (!curve || curve.length < 2) return '';
    var W = 760, H = 180, pad = 28;
    var x = function (i) { return pad + i * (W - pad * 2) / (curve.length - 1); };
    var y = function (p) { return H - pad - p * (H - pad * 2) / 100; };
    var line = function (key) {
        return curve.map(function (c, i) { return c[key] === null || c[key] === undefined ? null : [x(i), y(c[key])]; })
            .filter(Boolean).map(function (p, i) { return (i ? 'L' : 'M') + p[0].toFixed(1) + ',' + p[1].toFixed(1); }).join(' ');
    };
    return '<div class="widget" style="margin-top:14px;"><div class="widget-header"><h3>Planned against actual</h3>' +
        '<span style="font-size:0.76rem;color:var(--text-secondary);"><span style="color:#94a3b8;">&#9644;</span> planned &nbsp; ' +
        '<span style="color:var(--primary-color);">&#9644;</span> actual</span></div>' +
        '<div style="padding:8px 16px;overflow-x:auto;"><svg viewBox="0 0 ' + W + ' ' + H + '" style="width:100%;min-width:480px;height:auto;">' +
        [0, 25, 50, 75, 100].map(function (p) {
            return '<line x1="' + pad + '" x2="' + (W - pad) + '" y1="' + y(p) + '" y2="' + y(p) + '" stroke="currentColor" stroke-opacity=".08"/>' +
                '<text x="2" y="' + (y(p) + 3) + '" font-size="9" fill="currentColor" fill-opacity=".5">' + p + '%</text>';
        }).join('') +
        '<path d="' + line('planned') + '" fill="none" stroke="#94a3b8" stroke-width="2" stroke-dasharray="5 3"/>' +
        '<path d="' + line('actual') + '" fill="none" stroke="var(--primary-color)" stroke-width="2.5"/>' +
        '<text x="' + pad + '" y="' + (H - 6) + '" font-size="9" fill="currentColor" fill-opacity=".5">' + esc(curve[0].week) + '</text>' +
        '<text x="' + (W - pad) + '" y="' + (H - 6) + '" font-size="9" text-anchor="end" fill="currentColor" fill-opacity=".5">' + esc(curve[curve.length - 1].week) + '</text>' +
        '</svg></div></div>';
}

/* --- Editing ------------------------------------------------------------------- */

async function schEdit(id) {
    var a = id ? SCH.data.activities.filter(function (x) { return x.id === id; })[0] : {};
    SCH.editing = a.id || null;
    document.getElementById('sch-form-title').textContent = a.id ? 'Edit ' + (a.code || a.name) : 'New activity';
    document.getElementById('sch-f-name').value = a.name || '';
    document.getElementById('sch-f-code').value = a.code || '';
    document.getElementById('sch-f-start').value = a.planned_start || localDate(new Date());
    document.getElementById('sch-f-finish').value = a.planned_finish || '';
    document.getElementById('sch-f-weight').value = a.weight || '';
    document.getElementById('sch-f-milestone').checked = !!a.is_milestone;
    document.getElementById('sch-f-after').innerHTML = '<option value="">Nothing - it can start on its date</option>' +
        SCH.data.activities.filter(function (x) { return x.id !== a.id; }).map(function (x) {
            return '<option value="' + x.id + '"' + (x.id === a.depends_on_id ? ' selected' : '') + '>' + esc(x.code + ' ' + x.name) + '</option>';
        }).join('');
    var lines = '<option value="">Reported by hand</option>';
    try {
        var w = await (await fetch('/api/erp/work-orders', { credentials: 'include' })).json();
        var mine = (w.work_orders || []).filter(function (x) { return x.job_id === SCH.job && x.status !== 'Draft'; });
        for (var i = 0; i < mine.length; i++) {
            var full = await (await fetch('/api/erp/work-orders/' + mine[i].id, { credentials: 'include' })).json();
            (full.lines || []).forEach(function (l) {
                lines += '<option value="' + l.id + '"' + (l.id === a.work_order_line_id ? ' selected' : '') + '>' +
                    esc(mine[i].number + ' · ' + (l.fg_code || '') + ' ' + (l.description || l.item_name || '').split('\n')[0]) + '</option>';
            });
        }
    } catch (e) {}
    document.getElementById('sch-f-line').innerHTML = lines;
    document.getElementById('sch-delete').style.display = a.id ? '' : 'none';
    openModal('sch-form-modal');
    document.getElementById('sch-f-name').focus();
}
window.schEdit = schEdit;

async function schSave() {
    var val = function (k) { return document.getElementById('sch-f-' + k).value; };
    var body = { name: val('name'), code: val('code'), planned_start: val('start'), planned_finish: val('finish'),
                 weight: parseFloat(val('weight')) || 0, depends_on_id: parseInt(val('after')) || null,
                 work_order_line_id: parseInt(val('line')) || null,
                 is_milestone: document.getElementById('sch-f-milestone').checked };
    var res = await fetch(SCH.editing ? '/api/schedule/activities/' + SCH.editing : '/api/jobs/' + SCH.job + '/schedule/activities', {
        method: SCH.editing ? 'PUT' : 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not save it', 'error'); return; }
    closeModal('sch-form-modal');
    SCH.data = out.schedule;
    drawSchedule();
}
window.schSave = schSave;

async function schDelete() {
    if (!SCH.editing || !confirm('Remove this activity? Anything that followed it will follow what it followed.')) return;
    var res = await fetch('/api/schedule/activities/' + SCH.editing, { method: 'DELETE', credentials: 'include' });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not remove it', 'error'); return; }
    closeModal('sch-form-modal');
    SCH.data = out.schedule;
    drawSchedule();
}
window.schDelete = schDelete;

async function schProgress(id) {
    var a = SCH.data.activities.filter(function (x) { return x.id === id; })[0];
    var pct = prompt((a.code + ' ' + a.name) + '\nHow far along is it, in per cent? (now ' + a.actual_percent + '%)');
    if (pct === null || pct === '') return;
    var res = await fetch('/api/schedule/activities/' + id + '/progress', {
        method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ percent: parseFloat(pct) }) });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not record it', 'error'); return; }
    SCH.data = out.schedule;
    drawSchedule();
}
window.schProgress = schProgress;

async function schFromWo() {
    var w = await (await fetch('/api/erp/work-orders', { credentials: 'include' })).json();
    var mine = (w.work_orders || []).filter(function (x) { return x.job_id === SCH.job && x.status !== 'Draft'; });
    if (!mine.length) { showToast('This project has no placed work order to draw from', 'error'); return; }
    var pick = mine.length === 1 ? mine[0] : mine.filter(function (x) {
        return x.number === prompt('Which work order? ' + mine.map(function (m) { return m.number; }).join(', '), mine[0].number); })[0];
    if (!pick) return;
    var start = prompt('The work starts on (YYYY-MM-DD)', localDate(new Date()));
    if (!start) return;
    var end = new Date(start); end.setDate(end.getDate() + 90);
    var finish = prompt('And finishes by (YYYY-MM-DD)', localDate(end));
    if (!finish) return;
    var res = await fetch('/api/jobs/' + SCH.job + '/schedule/from-work-order/' + pick.id, {
        method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ start: start, finish: finish }) });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not draw it', 'error'); return; }
    showToast(out.message, 'success');
    SCH.data = out.schedule;
    drawSchedule();
}
window.schFromWo = schFromWo;
