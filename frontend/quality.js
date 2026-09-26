/* ===========================================================================
   quality.js - checklists, cube tests and non-conformances.

   The inspection is walked on site item by item - ok, not ok, not applicable
   - and closed as passed or failed. Cube sets are logged at the pour and read
   against the grade when crushed. Anything not as specified becomes an NCR,
   filled in from what failed, and stays open until it is put right.
   =========================================================================== */

var QC = { tab: 'inspections', jobId: null, checklists: null, current: null };

async function loadQuality() {
    var sel = document.getElementById('qc-job');
    if (!sel) return;
    if (!sel.options.length) {
        await fillJobPicker('qc-job');
        if (!sel.value && sel.options.length > 1) sel.selectedIndex = 1;
    }
    QC.jobId = parseInt(sel.value) || 0;
    if (!QC.checklists) QC.checklists = (await (await fetch('/api/qc/checklists', { credentials: 'include' })).json()).checklists;
    document.querySelectorAll('#qc-tabs button').forEach(function (b) { b.classList.toggle('active', b.dataset.tab === QC.tab); });
    var q = QC.jobId ? '?job_id=' + QC.jobId : '';
    var host = document.getElementById('qc-body');
    var [ins, cubes, ncrs] = await Promise.all([
        fetch('/api/qc/inspections' + q, { credentials: 'include' }).then(function (r) { return r.json(); }),
        fetch('/api/qc/cubes' + q, { credentials: 'include' }).then(function (r) { return r.json(); }),
        fetch('/api/qc/ncrs' + q, { credentials: 'include' }).then(function (r) { return r.json(); })]);
    QC.ins = ins.inspections || []; QC.cubes = cubes.cubes || []; QC.ncrs = ncrs.ncrs || [];
    document.getElementById('qc-stats').innerHTML =
        statCard('Inspections failed', String(QC.ins.filter(function (i) { return i.result === 'FAILED'; }).length)) +
        statCard('Cubes to crush', String((cubes.summary || {}).due || 0)) +
        statCard('Below grade', String((cubes.summary || {}).below || 0)) +
        statCard('NCRs open', String((ncrs.summary || {}).open || 0) +
            ((ncrs.summary || {}).overdue ? ' <span style="font-size:0.72rem;color:var(--danger-color);">(' + ncrs.summary.overdue + ' late)</span>' : ''));
    var tone = { PASSED: 'good', FAILED: 'bad', OPEN: 'warn', CLOSED: 'good' };
    if (QC.tab === 'inspections') {
        host.innerHTML = '<div class="table-responsive"><table class="data-table"><thead><tr><th>No.</th><th>Checklist</th><th>Where</th>' +
            '<th>On</th><th>By</th><th>Result</th><th></th></tr></thead><tbody>' +
            (QC.ins.map(function (i) {
                return '<tr><td style="font-family:monospace;">' + esc(i.number) + '</td><td>' + esc(i.checklist) + '</td><td>' + esc(i.location) + '</td>' +
                    '<td>' + esc(i.inspected_on) + '</td><td>' + esc(i.inspected_by) + '</td><td>' + statusPill(i.result, tone[i.result]) +
                    (i.failed_items ? ' <span style="font-size:0.72rem;color:var(--danger-color);">' + i.failed_items + ' not ok</span>' : '') + '</td>' +
                    '<td class="text-right" style="white-space:nowrap;"><button class="btn btn-sm btn-outline" onclick="qcOpen(' + i.id + ')">Open</button> ' +
                    '<button class="btn btn-sm btn-outline" onclick="openFiles(\'inspection\',' + i.id + ',\'' + esc(i.number) + '\')">Photos</button></td></tr>';
            }).join('') || '<tr><td colspan="7" style="text-align:center;padding:24px;color:var(--text-secondary);">No inspections yet. Walk the checklist before work is covered up.</td></tr>') +
            '</tbody></table></div>';
    } else if (QC.tab === 'cubes') {
        host.innerHTML = '<div class="table-responsive"><table class="data-table"><thead><tr><th>Set</th><th>Cast</th><th>Where</th><th>Grade</th>' +
            '<th>7 days</th><th>28 days</th><th>Status</th><th></th></tr></thead><tbody>' +
            (QC.cubes.map(function (c) {
                var at = function (age) {
                    var r = c.results.filter(function (x) { return x.age_days === age; })[0];
                    if (r) return '<span style="color:' + (r.ok ? 'inherit' : 'var(--danger-color)') + ';font-weight:600;">' + r.average + '</span>' +
                        (r.spread_ok ? '' : ' <span title="A cube is more than 15% off the average" style="color:var(--warning-color);">&#9888;</span>');
                    var d = c.due.filter(function (x) { return x.age_days === age; })[0];
                    return d ? '<span style="font-size:0.76rem;color:' + (d.overdue ? 'var(--danger-color)' : 'var(--text-secondary)') + ';">due ' + esc(d.due_on) + '</span>' : '';
                };
                var st = c.status === 'below grade' ? 'bad' : c.status === 'meets grade' ? 'good' : 'calm';
                return '<tr><td style="font-family:monospace;">' + esc(c.number) + '</td><td>' + esc(c.cast_on) + '</td><td>' + esc(c.location) +
                    (c.supplier ? '<div style="font-size:0.72rem;color:var(--text-secondary);">' + esc(c.supplier) + (c.docket ? ' #' + esc(c.docket) : '') + '</div>' : '') + '</td>' +
                    '<td>' + esc(c.grade) + '</td><td>' + at(7) + '</td><td>' + at(28) + '</td><td>' + statusPill(c.status, st) + '</td>' +
                    '<td class="text-right" style="white-space:nowrap;"><button class="btn btn-sm btn-outline" onclick="qcCubeResult(' + c.id + ')">Result</button>' +
                    (c.status === 'below grade' ? ' <button class="btn btn-sm btn-outline" style="color:var(--danger-color);" onclick="qcNcrFrom(\'cube_set\',' + c.id + ')">Raise NCR</button>' : '') + '</td></tr>';
            }).join('') || '<tr><td colspan="8" style="text-align:center;padding:24px;color:var(--text-secondary);">No cube sets yet. Log each pour\'s cubes the day they are cast.</td></tr>') +
            '</tbody></table></div><p style="font-size:0.74rem;color:var(--text-secondary);margin-top:8px;">Averages in N/mm&sup2;. Seven-day results are expected near two-thirds of the grade; ' +
            'twenty-eight-day results are read against it. &#9888; marks a set with a cube more than 15% off its average (IS 516).</p>';
    } else {
        host.innerHTML = '<div class="table-responsive"><table class="data-table"><thead><tr><th>NCR</th><th>Raised</th><th>Where</th><th>What</th>' +
            '<th>Owner</th><th>By</th><th>Status</th><th></th></tr></thead><tbody>' +
            (QC.ncrs.map(function (n) {
                return '<tr><td style="font-family:monospace;">' + esc(n.number) + (n.severity === 'Major' ? '<div style="font-size:0.7rem;color:var(--danger-color);">major</div>' : '') + '</td>' +
                    '<td>' + esc(n.raised_on) + '</td><td>' + esc(n.location) + '</td><td style="max-width:320px;">' + esc(n.description.slice(0, 160)) +
                    (n.closure_note ? '<div style="font-size:0.74rem;color:var(--success-color);">Closed: ' + esc(n.closure_note) + '</div>' : '') + '</td>' +
                    '<td>' + esc(n.responsible) + '</td><td style="' + (n.overdue ? 'color:var(--danger-color);font-weight:600;' : '') + '">' + esc(n.target_date) + '</td>' +
                    '<td>' + statusPill(n.status, n.overdue ? 'bad' : tone[n.status]) + '</td><td class="text-right" style="white-space:nowrap;">' +
                    (n.status === 'OPEN' && can('site.signoff') ? '<button class="btn btn-sm btn-outline" onclick="qcNcrClose(' + n.id + ')">Close</button> ' : '') +
                    '<button class="btn btn-sm btn-outline" onclick="openFiles(\'ncr\',' + n.id + ',\'' + esc(n.number) + '\')">Photos</button></td></tr>';
            }).join('') || '<tr><td colspan="8" style="text-align:center;padding:24px;color:var(--text-secondary);">No non-conformances.</td></tr>') +
            '</tbody></table></div>';
    }
}
window.loadQuality = loadQuality;

function qcTab(t) { QC.tab = t; loadQuality(); }
window.qcTab = qcTab;

function qcNew() {
    if (!QC.jobId) { showToast('Pick the project first', 'error'); return; }
    if (QC.tab === 'cubes') return qcCubeNew();
    if (QC.tab === 'ncrs') return qcNcrNew();
    var names = Object.keys(QC.checklists);
    document.getElementById('qcnew-list').innerHTML = names.map(function (n) { return '<option>' + esc(n) + '</option>'; }).join('');
    document.getElementById('qcnew-where').value = '';
    document.getElementById('qcnew-witness').value = '';
    openModal('qcnew-modal');
}
window.qcNew = qcNew;

async function qcCreate() {
    var res = await fetch('/api/qc/inspections', { method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_id: QC.jobId, checklist: document.getElementById('qcnew-list').value,
                               location: document.getElementById('qcnew-where').value,
                               witnessed_by: document.getElementById('qcnew-witness').value }) });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not start it', 'error'); return; }
    closeModal('qcnew-modal');
    await loadQuality();
    qcOpen(out.inspection.id);
}
window.qcCreate = qcCreate;

function qcOpen(id) {
    var i = QC.ins.filter(function (x) { return x.id === id; })[0];
    if (!i) return;
    QC.current = JSON.parse(JSON.stringify(i));
    var open = i.result === 'OPEN';
    document.getElementById('qcins-title').textContent = i.number + ' — ' + i.checklist + (i.location ? ' · ' + i.location : '');
    document.getElementById('qcins-body').innerHTML = '<table class="data-table"><thead><tr><th>Check</th><th style="text-align:center;">OK</th>' +
        '<th style="text-align:center;">Not OK</th><th style="text-align:center;">N/A</th><th>Remark</th></tr></thead><tbody>' +
        QC.current.items.map(function (x, n) {
            var radio = function (v) {
                return '<td style="text-align:center;"><input type="radio" name="qci' + n + '"' + (x.result === v ? ' checked' : '') +
                    (open ? '' : ' disabled') + ' onchange="QC.current.items[' + n + '].result=\'' + v + '\'"></td>';
            };
            return '<tr><td>' + esc(x.item) + '</td>' + radio('ok') + radio('not ok') + radio('na') +
                '<td><input class="form-control" style="min-width:160px;" value="' + esc(x.remark || '') + '"' + (open ? '' : ' disabled') +
                ' oninput="QC.current.items[' + n + '].remark=this.value"></td></tr>';
        }).join('') + '</tbody></table>' +
        '<p style="font-size:0.78rem;color:var(--text-secondary);margin-top:8px;">By ' + esc(i.inspected_by) + ' on ' + esc(i.inspected_on) +
        (i.witnessed_by ? ', witnessed by ' + esc(i.witnessed_by) : '') + '.</p>';
    var b = [];
    if (open) b.push('<button class="btn btn-outline" onclick="qcSave(false)">Save</button>',
                     (can('site.signoff') ? '<button class="btn btn-primary" onclick="qcSave(true)">Close it</button>' : ''));
    if (i.result === 'FAILED') b.push('<button class="btn btn-outline" style="color:var(--danger-color);" onclick="qcNcrFrom(\'inspection\',' + i.id + ')">Raise NCR</button>');
    b.push('<button class="btn btn-outline" onclick="openFiles(\'inspection\',' + i.id + ',\'' + esc(i.number) + '\')">Photos</button>',
           '<button class="btn btn-outline" onclick="closeModal(\'qcins-modal\')">Done</button>');
    document.getElementById('qcins-actions').innerHTML = b.join(' ');
    openModal('qcins-modal');
}
window.qcOpen = qcOpen;

async function qcSave(close) {
    var i = QC.current;
    var res = await fetch('/api/qc/inspections/' + i.id, { method: 'PUT', credentials: 'include',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ job_id: i.job_id, items: i.items }) });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not save', 'error'); return; }
    if (close) {
        res = await fetch('/api/qc/inspections/' + i.id + '/close', { method: 'POST', credentials: 'include' });
        out = await res.json();
        if (!res.ok) { showToast(out.detail || 'Could not close it', 'error'); return; }
        showToast(out.inspection.number + ' ' + out.inspection.result.toLowerCase() + '.', out.inspection.result === 'PASSED' ? 'success' : 'error');
    } else showToast('Saved.', 'success');
    await loadQuality();
    qcOpen(i.id);
}
window.qcSave = qcSave;

function qcCubeNew() {
    ['qccube-where', 'qccube-supplier', 'qccube-docket', 'qccube-slump'].forEach(function (id) { document.getElementById(id).value = ''; });
    document.getElementById('qccube-grade').value = 'M25';
    document.getElementById('qccube-date').value = localDate(new Date());
    openModal('qccube-modal');
}

async function qcCubeSave() {
    var v = function (id) { return document.getElementById(id).value; };
    var res = await fetch('/api/qc/cubes', { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_id: QC.jobId, grade: v('qccube-grade'), cast_on: v('qccube-date'), location: v('qccube-where'),
                               supplier: v('qccube-supplier'), docket: v('qccube-docket'), slump_mm: parseFloat(v('qccube-slump')) || 0 }) });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not save', 'error'); return; }
    showToast(out.cube_set.number + ' logged. Its 7- and 28-day tests are now tracked.', 'success');
    closeModal('qccube-modal');
    loadQuality();
}
window.qcCubeSave = qcCubeSave;

async function qcCubeResult(id) {
    var c = QC.cubes.filter(function (x) { return x.id === id; })[0];
    var next = (c.due[0] || {}).age_days || 28;
    var age = prompt('Age at test, in days (7 or 28):', String(next));
    if (!age) return;
    var s = prompt(c.number + ' ' + c.grade + ' - crushing strengths in N/mm², one per cube:', '');
    if (!s) return;
    var res = await fetch('/api/qc/cubes/' + id + '/results', { method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ age_days: parseInt(age), strengths: s }) });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not record it', 'error'); return; }
    var r = out.cube_set.results.filter(function (x) { return x.age_days === parseInt(age); })[0];
    showToast(out.cube_set.number + ' at ' + age + ' days: ' + r.average + ' N/mm² - ' + r.verdict + '.', r.ok ? 'success' : 'error');
    loadQuality();
}
window.qcCubeResult = qcCubeResult;

async function qcNcrFrom(sourceType, id) {
    var who = prompt('Who puts it right? (the gang, the supplier...)', '') || '';
    var by = prompt('By when? (YYYY-MM-DD)', '') || '';
    var major = confirm('Is it major? OK = major, Cancel = minor');
    var res = await fetch('/api/qc/ncrs', { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source_type: sourceType, source_id: id, responsible: who, target_date: by, severity: major ? 'Major' : 'Minor' }) });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not raise it', 'error'); return; }
    showToast(out.ncr.number + ' raised.', 'success');
    closeModal('qcins-modal');
    QC.tab = 'ncrs';
    loadQuality();
}
window.qcNcrFrom = qcNcrFrom;

async function qcNcrNew() {
    var what = prompt('What is not as specified?');
    if (!what) return;
    var where = prompt('Where?', '') || '';
    var who = prompt('Who puts it right?', '') || '';
    var by = prompt('By when? (YYYY-MM-DD)', '') || '';
    var res = await fetch('/api/qc/ncrs', { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_id: QC.jobId, description: what, location: where, responsible: who, target_date: by }) });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not raise it', 'error'); return; }
    showToast(out.ncr.number + ' raised.', 'success');
    loadQuality();
}

async function qcNcrClose(id) {
    var note = prompt('What was done to put it right?');
    if (!note) return;
    var res = await fetch('/api/qc/ncrs/' + id + '/close', { method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ closure_note: note }) });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not close it', 'error'); return; }
    showToast(out.ncr.number + ' closed.', 'success');
    loadQuality();
}
window.qcNcrClose = qcNcrClose;
