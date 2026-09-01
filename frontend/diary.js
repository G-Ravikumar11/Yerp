/* ===========================================================================
   diary.js - the daily site record, and the project profit it makes real.

   The diary is the document that settles a delay claim two years later, so
   nothing here rewrites a day once it has been signed off. It is also the
   only place the labour standing on site is written down, which is what
   turns a job's cost from "material" into the truth.
   =========================================================================== */

var DIARY = { list: [], summary: {}, current: null, job: null };
var TRADES = ['Mason', 'Helper', 'Carpenter', 'Bar bender', 'Fitter',
              'Electrician', 'Plumber', 'Painter', 'Operator', 'Driver',
              'Surveyor', 'Supervisor'];
var WEATHER = ['Clear', 'Cloudy', 'Rain', 'Heavy rain'];

async function loadDiary() {
    var pick = document.getElementById('diary-job');
    if (!pick) return;
    var d = await (await fetch('/api/jobs', { credentials: 'include' })).json();
    var jobs = d.jobs || d;
    pick.innerHTML = jobs.length
        ? jobs.map(function (j) {
            return '<option value="' + j.id + '">' + esc(j.number || '') + ' ' +
                esc(j.name) + '</option>';
          }).join('')
        : '<option value="">No projects yet</option>';
    if (jobs.length) { DIARY.job = jobs[0].id; refreshDiary(); }
}
window.loadDiary = loadDiary;

function diaryJobChanged() {
    var pick = document.getElementById('diary-job');
    DIARY.job = parseInt(pick.value) || null;
    refreshDiary();
}
window.diaryJobChanged = diaryJobChanged;

async function refreshDiary() {
    if (!DIARY.job) return;
    var d = await (await fetch('/api/diary?job_id=' + DIARY.job,
                               { credentials: 'include' })).json();
    DIARY.list = d.diaries || [];
    var s = d.summary || {};
    var stats = document.getElementById('diary-stats');
    if (stats) stats.innerHTML =
        statCard('Days recorded', String(s.days_recorded || 0)) +
        statCard('Mandays', String(s.mandays || 0)) +
        statCard('Labour', formatCurrency(s.labour_cost || 0)) +
        statCard('Plant', formatCurrency(s.plant_cost || 0)) +
        statCard('Rained off', String(s.days_lost_to_weather || 0));

    document.getElementById('diary-body').innerHTML = DIARY.list.length
        ? DIARY.list.map(function (r) {
            return '<tr>' +
                '<td style="font-weight:600;">' + esc(r.diary_date) +
                    (r.lost_to_weather ? '<div style="font-size:0.72rem;font-weight:400;' +
                     'color:var(--warning-color);">rained off</div>' : '') + '</td>' +
                '<td>' + esc(r.weather) +
                    (r.rain_hours ? ' · ' + r.rain_hours + 'h' : '') + '</td>' +
                '<td class="text-right" style="font-weight:600;">' + r.total_mandays + '</td>' +
                '<td class="text-right">' + formatCurrency(r.labour_cost) + '</td>' +
                '<td class="text-right">' + formatCurrency(r.plant_cost) + '</td>' +
                '<td style="max-width:260px;">' + esc((r.work_done || '').slice(0, 90)) +
                    (r.holdups ? '<div style="font-size:0.72rem;color:var(--warning-color);">' +
                     'held up: ' + esc(r.holdups.slice(0, 60)) + '</div>' : '') + '</td>' +
                '<td>' + statusPill(r.status, r.status === 'SUBMITTED' ? 'good' : 'calm') + '</td>' +
                '<td class="text-right">' +
                    '<button class="btn btn-sm btn-outline" onclick="openDiary(' + r.id +
                    ')">Open</button> <a class="btn btn-sm btn-outline" href="/api/diary/' +
                    r.id + '/export.xlsx">DPR</a></td>' +
                '</tr>';
          }).join('')
        : '<tr><td colspan="8" style="text-align:center;padding:30px;' +
          'color:var(--text-secondary);">No days recorded on this site yet.</td></tr>';

    loadLabourHistory();
}
window.refreshDiary = refreshDiary;

async function loadLabourHistory() {
    var box = document.getElementById('labour-history');
    if (!box || !DIARY.job) return;
    var h = await (await fetch('/api/diary-labour/' + DIARY.job,
                               { credentials: 'include' })).json();
    var s = h.summary || {};
    if (!(h.by_trade || []).length) { box.innerHTML = ''; return; }
    var top = Math.max.apply(null, h.by_trade.map(function (t) { return t.mandays; }));
    box.innerHTML =
        '<div class="widget"><div class="widget-header"><h3>Who has been on this site</h3></div>' +
        '<div class="widget-content" style="padding:16px 20px;">' +
        '<p style="font-size:0.85rem;color:var(--text-secondary);margin-bottom:14px;">' +
        s.mandays + ' mandays over ' + s.days_worked + ' working days · average gang ' +
        s.average_gang + ' · ' + formatCurrency(s.labour_cost) + ' in wages · ' +
        s.rain_hours + ' hours of rain</p>' +
        h.by_trade.map(function (t) {
            var pc = top ? (t.mandays / top * 100) : 0;
            return '<div style="margin-bottom:9px;">' +
                '<div style="display:flex;justify-content:space-between;font-size:0.82rem;">' +
                '<span>' + esc(t.trade) + '</span><span style="color:var(--text-secondary);">' +
                t.mandays + ' md · ' + formatCurrency(t.cost) + '</span></div>' +
                '<div style="height:7px;background:var(--border-color);border-radius:4px;' +
                'margin-top:3px;overflow:hidden;"><div style="width:' + pc + '%;height:100%;' +
                'background:var(--primary-color);"></div></div></div>';
        }).join('') + '</div></div>';
}

/* --- One day -------------------------------------------------------------- */

function labourRow(l, i) {
    l = l || {};
    return '<tr>' +
        '<td><select class="form-control input-sm" id="lab-trade-' + i + '">' +
            TRADES.map(function (t) {
                return '<option' + (t === l.trade ? ' selected' : '') + '>' + t + '</option>';
            }).join('') + '</select></td>' +
        '<td><input class="form-control input-sm" id="lab-agency-' + i +
            '" value="' + esc(l.agency || 'Own') + '" placeholder="Own or the gang"></td>' +
        '<td><input type="number" step="any" min="0" class="form-control input-sm" id="lab-head-' + i +
            '" value="' + (l.headcount || '') + '" style="text-align:right;" oninput="diaryTotals()"></td>' +
        '<td><input type="number" step="any" min="0" class="form-control input-sm" id="lab-hours-' + i +
            '" value="' + (l.hours || '') + '" style="text-align:right;" oninput="diaryTotals()"></td>' +
        '<td><input type="number" step="any" min="0" class="form-control input-sm" id="lab-rate-' + i +
            '" value="' + (l.rate || '') + '" style="text-align:right;" oninput="diaryTotals()"></td>' +
        '</tr>';
}

function plantRow(p, i) {
    p = p || {};
    return '<tr>' +
        '<td><input class="form-control input-sm" id="pl-name-' + i +
            '" value="' + esc(p.plant || '') + '" placeholder="JCB 3DX"></td>' +
        '<td><input type="number" step="any" min="0" class="form-control input-sm" id="pl-worked-' + i +
            '" value="' + (p.worked_hours || '') + '" style="text-align:right;" oninput="diaryTotals()"></td>' +
        '<td><input type="number" step="any" min="0" class="form-control input-sm" id="pl-idle-' + i +
            '" value="' + (p.idle_hours || '') + '" style="text-align:right;" oninput="diaryTotals()"></td>' +
        '<td><input type="number" step="any" min="0" class="form-control input-sm" id="pl-rate-' + i +
            '" value="' + (p.rate || '') + '" style="text-align:right;" oninput="diaryTotals()"></td>' +
        '</tr>';
}

function renderDiaryForm(d) {
    DIARY.current = d;
    var locked = d.id && d.status !== 'DRAFT';
    document.getElementById('diary-form-title').textContent =
        d.id ? ('Day of ' + d.diary_date) : 'New day';
    document.getElementById('diary-date').value = d.diary_date || new Date().toISOString().slice(0, 10);
    document.getElementById('diary-weather').innerHTML = WEATHER.map(function (w) {
        return '<option' + (w === d.weather ? ' selected' : '') + '>' + w + '</option>';
    }).join('');
    document.getElementById('diary-rain').value = d.rain_hours || '';
    document.getElementById('diary-hours').value = d.working_hours || 8;
    document.getElementById('diary-work').value = d.work_done || '';
    document.getElementById('diary-holdups').value = d.holdups || '';
    document.getElementById('diary-instructions').value = d.instructions || '';
    document.getElementById('diary-visitors').value = d.visitors || '';
    document.getElementById('diary-safety').value = d.safety_note || '';

    // Always one blank row past the end, so adding a trade is typing rather
    // than hunting for a button.
    var lab = (d.labour || []).concat([{}, {}]);
    var pl = (d.plant || []).concat([{}]);
    document.getElementById('diary-labour-rows').innerHTML =
        lab.map(labourRow).join('');
    document.getElementById('diary-plant-rows').innerHTML =
        pl.map(plantRow).join('');
    DIARY.labRows = lab.length;
    DIARY.plRows = pl.length;

    document.getElementById('diary-form').style.display = 'flex';
    document.querySelectorAll('#diary-form input, #diary-form select, #diary-form textarea')
        .forEach(function (el) { el.disabled = locked; });
    document.getElementById('diary-save').style.display = locked ? 'none' : '';
    document.getElementById('diary-submit').style.display = locked ? 'none' : '';
    document.getElementById('diary-locked').textContent = locked
        ? 'Signed off on ' + (d.submitted_at || '') + ' — a diary that can be rewritten afterwards is worth nothing in a claim.'
        : '';
    diaryTotals();
}

function newDiary() {
    if (!DIARY.job) { showToast('Choose a site first', 'error'); return; }
    renderDiaryForm({ weather: 'Clear', working_hours: 8, labour: [], plant: [] });
}
window.newDiary = newDiary;

async function openDiary(id) {
    var d = await (await fetch('/api/diary/' + id, { credentials: 'include' })).json();
    renderDiaryForm(d);
}
window.openDiary = openDiary;

function closeDiaryForm() {
    document.getElementById('diary-form').style.display = 'none';
}
window.closeDiaryForm = closeDiaryForm;

function collectDiary() {
    var day = parseFloat(document.getElementById('diary-hours').value) || 8;
    var labour = [], plant = [];
    for (var i = 0; i < DIARY.labRows; i++) {
        var heads = parseFloat((document.getElementById('lab-head-' + i) || {}).value) || 0;
        if (!heads) continue;
        labour.push({
            trade: document.getElementById('lab-trade-' + i).value,
            agency: document.getElementById('lab-agency-' + i).value || 'Own',
            headcount: heads,
            hours: parseFloat(document.getElementById('lab-hours-' + i).value) || day,
            rate: parseFloat(document.getElementById('lab-rate-' + i).value) || 0,
        });
    }
    for (var j = 0; j < DIARY.plRows; j++) {
        var name = (document.getElementById('pl-name-' + j) || {}).value || '';
        if (!name.trim()) continue;
        plant.push({
            plant: name,
            worked_hours: parseFloat(document.getElementById('pl-worked-' + j).value) || 0,
            idle_hours: parseFloat(document.getElementById('pl-idle-' + j).value) || 0,
            rate: parseFloat(document.getElementById('pl-rate-' + j).value) || 0,
        });
    }
    return {
        job_id: DIARY.job,
        diary_date: document.getElementById('diary-date').value,
        weather: document.getElementById('diary-weather').value,
        rain_hours: parseFloat(document.getElementById('diary-rain').value) || 0,
        working_hours: day,
        work_done: document.getElementById('diary-work').value,
        holdups: document.getElementById('diary-holdups').value,
        instructions: document.getElementById('diary-instructions').value,
        visitors: document.getElementById('diary-visitors').value,
        safety_note: document.getElementById('diary-safety').value,
        labour: labour, plant: plant,
    };
}

function diaryTotals() {
    var body = collectDiary(), day = body.working_hours || 8;
    var md = 0, lc = 0, pc = 0;
    body.labour.forEach(function (l) {
        var share = (l.hours || day) / day;
        md += l.headcount * share;
        lc += l.headcount * share * l.rate;
    });
    body.plant.forEach(function (p) { pc += (p.worked_hours + p.idle_hours) * p.rate; });
    var el = document.getElementById('diary-totals');
    if (el) el.innerHTML = '<strong>' + Math.round(md * 100) / 100 + '</strong> mandays · ' +
        'labour <strong>' + formatCurrency(lc) + '</strong> · plant <strong>' +
        formatCurrency(pc) + '</strong> · the day cost <strong>' +
        formatCurrency(lc + pc) + '</strong>';
}
window.diaryTotals = diaryTotals;

async function saveDiary(andSubmit) {
    var body = collectDiary();
    var editing = DIARY.current && DIARY.current.id;
    var res = await fetch('/api/diary' + (editing ? '/' + DIARY.current.id : ''), {
        method: editing ? 'PUT' : 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not save the day', 'error'); return; }
    var id = out.diary.id;
    if (andSubmit) {
        var sub = await fetch('/api/diary/' + id + '/submit',
                              { method: 'POST', credentials: 'include' });
        var s = await sub.json();
        if (!sub.ok) {
            showToast(s.detail || 'Could not sign it off', 'error');
            DIARY.current = out.diary;
            return;
        }
        showToast(s.message, 'success');
    } else {
        showToast(out.message || 'Saved.', 'success');
    }
    closeDiaryForm();
    refreshDiary();
}
window.saveDiary = saveDiary;

/* --- Project profit ------------------------------------------------------- */

async function loadPortfolio() {
    var body = document.getElementById('pnl-body');
    if (!body) return;
    var d = await (await fetch('/api/jobs-pnl', { credentials: 'include' })).json();
    var s = d.summary || {};
    var stats = document.getElementById('pnl-stats');
    if (stats) stats.innerHTML =
        statCard('Projects', String(s.projects || 0)) +
        statCard('Order book', formatCurrency(s.order_value || 0)) +
        statCard('Revenue', formatCurrency(s.revenue || 0)) +
        statCard('Cost incurred', formatCurrency(s.incurred || 0)) +
        statCard('Margin', formatCurrency(s.margin || 0)) +
        statCard('Owed to us', formatCurrency(s.owed_to_us || 0));

    body.innerHTML = (d.projects || []).length ? d.projects.map(function (p) {
        return '<tr>' +
            '<td style="font-weight:600;">' + esc(p.number || '') + ' ' + esc(p.name) +
                '<div style="font-size:0.75rem;font-weight:400;color:var(--text-secondary);">' +
                esc(p.customer_name || '') + '</div></td>' +
            '<td class="text-right">' + formatCurrency(p.order_value) + '</td>' +
            '<td class="text-right">' + formatCurrency(p.revenue) + '</td>' +
            '<td class="text-right">' + formatCurrency(p.incurred) +
                (p.committed ? '<div style="font-size:0.72rem;color:var(--text-secondary);">+' +
                 formatCurrency(p.committed) + ' committed</div>' : '') + '</td>' +
            '<td class="text-right" style="font-weight:700;color:' +
                (p.losing ? 'var(--danger-color)' : 'var(--success-color)') + ';">' +
                formatCurrency(p.margin) +
                '<div style="font-size:0.72rem;font-weight:400;">' + p.margin_percent + '%</div></td>' +
            '<td class="text-right">' + p.mandays + '</td>' +
            '<td>' + (p.losing ? statusPill('losing money', 'bad')
                     : p.over_budget ? statusPill('over budget', 'wait')
                                     : statusPill(p.status || 'live', 'good')) + '</td>' +
            '<td class="text-right"><a class="btn btn-sm btn-outline" href="/api/jobs/' +
                p.job_id + '/pnl.xlsx">Excel</a></td>' +
            '</tr>';
    }).join('') : '<tr><td colspan="8" style="text-align:center;padding:30px;' +
        'color:var(--text-secondary);">No projects yet.</td></tr>';
}
window.loadPortfolio = loadPortfolio;
