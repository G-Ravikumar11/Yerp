/* ===========================================================================
   files.js - site photos and the drawings register.

   openFiles() is the one window for the photos and papers kept against any
   record - a diary day, a measurement, a variation, the project itself. On a
   phone the button opens the camera. Photos are made smaller before they go
   up, so a day's pictures cost a few hundred kilobytes, not forty megabytes.

   The Drawings & Photos screen is the project's register: every sheet, every
   revision kept, the one to build to marked, and the project's photographs.
   =========================================================================== */

var FILES = { type: null, id: null, title: '', jobId: null, tab: 'drawings', drawings: [],
              filter: { kind: '', q: '', from: '', to: '', by: '', source: '' },
              regFilter: { q: '', discipline: '', status: '' } };

/* A photo shrunk to at most `max` pixels on its long side, as JPEG. */
function shrinkImage(file, max, quality) {
    return new Promise(function (resolve) {
        if (!/^image\/(jpeg|png|webp)$/.test(file.type)) { resolve(null); return; }
        var img = new Image();
        img.onload = function () {
            var scale = Math.min(1, max / Math.max(img.width, img.height));
            var c = document.createElement('canvas');
            c.width = Math.round(img.width * scale);
            c.height = Math.round(img.height * scale);
            c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
            c.toBlob(function (b) { URL.revokeObjectURL(img.src); resolve(b); }, 'image/jpeg', quality);
        };
        img.onerror = function () { resolve(null); };
        img.src = URL.createObjectURL(file);
    });
}

async function uploadFiles(fileList, attachedType, attachedId, extra) {
    var done = 0, failed = [];
    for (var i = 0; i < fileList.length; i++) {
        var f = fileList[i];
        var fd = new FormData();
        // A photographed drawing keeps enough pixels to read its dimensions;
        // a site photo does not need them. The server makes both smaller again.
        var drawing = (extra || {}).kind === 'drawing';
        var big = await shrinkImage(f, drawing ? 2400 : 1600, drawing ? 0.85 : 0.8);
        if (big && big.size >= f.size && /^image\/jpeg$/.test(f.type)) big = null;   // already smaller as it was
        if (big) {
            fd.append('file', big, f.name.replace(/\.[^.]+$/, '') + '.jpg');
            var small = await shrinkImage(f, 320, 0.6);
            if (small) fd.append('thumb', small, 'thumb.jpg');
        } else {
            fd.append('file', f, f.name);
        }
        fd.append('attached_type', attachedType);
        fd.append('attached_id', attachedId);
        Object.keys(extra || {}).forEach(function (k) { fd.append(k, extra[k]); });
        var res = await fetch('/api/files', { method: 'POST', credentials: 'include', body: fd });
        if (res.ok) done++;
        else {
            var out = await res.json().catch(function () { return {}; });
            failed.push(f.name + ': ' + (out.detail || 'not saved'));
        }
    }
    if (failed.length) showToast(failed.join(' · '), 'error');
    else if (done) showToast(done + ' file' + (done === 1 ? '' : 's') + ' added.', 'success');
    return done;
}

function fileSize(n) {
    if (!n) return '';
    return n >= 1048576 ? (Math.round(n / 104857.6) / 10) + ' MB' : Math.max(1, Math.round(n / 1024)) + ' KB';
}
window.fileSize = fileSize;

var KIND_WORD = { drawing: 'Drawing', photo: 'Photo', document: 'Document' };

function fileTile(f, canDelete) {
    var inner = f.is_image
        ? '<img src="' + f.thumb_url + '" alt="" loading="lazy" style="width:100%;height:120px;object-fit:cover;border-radius:6px;display:block;">'
        : '<div style="height:120px;display:flex;align-items:center;justify-content:center;border-radius:6px;' +
          'background:var(--bg-hover,rgba(0,0,0,0.04));font-weight:700;color:var(--text-secondary);">' +
          esc((f.name.split('.').pop() || 'file').toUpperCase()) + '</div>';
    return '<div style="border:1px solid var(--border-color);border-radius:8px;padding:6px;">' +
        '<a href="' + f.url + '" target="_blank" rel="noopener">' + inner + '</a>' +
        '<div style="font-size:0.74rem;margin-top:4px;line-height:1.3;">' +
            '<span style="font-size:0.64rem;font-weight:700;padding:0 5px;border-radius:4px;margin-right:4px;' +
            'background:' + (f.kind === 'drawing' ? '#dbeafe;color:#1d4ed8' : f.kind === 'photo' ? '#dcfce7;color:#15803d' : '#f1f5f9;color:#475569') + ';">' +
            esc(KIND_WORD[f.kind] || f.kind) + '</span>' + esc(f.caption || f.name) + '</div>' +
        '<div style="font-size:0.66rem;color:var(--text-secondary);">' + fileSize(f.size) +
            (f.original_size > f.size * 1.2 ? ' (was ' + fileSize(f.original_size) + ')' : '') +
            (f.shared ? ' · same file kept elsewhere, stored once' : '') + '</div>' +
        '<div style="font-size:0.68rem;color:var(--text-secondary);">' + esc(f.taken_on || '') +
        (f.of ? ' &middot; ' + esc(f.of) : '') + (f.uploaded_by_name ? ' &middot; ' + esc(f.uploaded_by_name) : '') + '</div>' +
        (canDelete ? '<button class="btn btn-sm btn-outline" style="margin-top:4px;font-size:0.7rem;padding:1px 6px;" ' +
            'onclick="removeFile(' + f.id + ')">Remove</button>' : '') + '</div>';
}

async function openFiles(attachedType, attachedId, title) {
    FILES.type = attachedType; FILES.id = attachedId; FILES.title = title || '';
    FILES.filter = { kind: '', q: '', from: '', to: '', by: '', source: '' };
    var isOrder = attachedType === 'subcontract_order' || attachedType === 'work_order';
    document.getElementById('files-title').textContent = (isOrder ? 'Drawings & photos — ' : 'Photos & files — ') + (title || '');
    // A work order's files are mostly its drawings; everywhere else, photos.
    var kindSel = document.getElementById('files-kind');
    if (kindSel) kindSel.value = isOrder ? 'drawing' : '';
    await refreshFilesModal();
    openModal('files-modal');
}
window.openFiles = openFiles;

/* The filter row: type, words, dates, who added it. Shared by the files
   window and the project's photos. */
function fileFilterBar(prefix, f, summary, onchange, extra) {
    var s = summary || {};
    var chip = function (k, label, n) {
        return '<button class="tab' + ((f.kind || '') === k ? ' active' : '') + '" style="padding:6px 12px;" ' +
            'onclick="' + onchange + '(\'kind\',\'' + k + '\')">' + esc(label) +
            (n !== undefined ? ' <span style="font-size:0.72rem;opacity:0.75;">' + n + '</span>' : '') + '</button>';
    };
    return '<div style="display:flex;gap:4px;flex-wrap:wrap;">' +
        chip('', 'All') + chip('drawing', 'Drawings', f.kind ? undefined : s.drawings) +
        chip('photo', 'Photos', f.kind ? undefined : s.photos) + chip('document', 'Documents', f.kind ? undefined : s.documents) +
        '</div>' +
        '<input class="form-control" style="flex:1;min-width:150px;" placeholder="Search name or caption" value="' + esc(f.q) + '" ' +
            'oninput="' + onchange + '(\'q\',this.value,true)">' +
        '<input type="date" class="form-control" style="width:auto;" title="Taken from" value="' + esc(f.from) + '" onchange="' + onchange + '(\'from\',this.value)">' +
        '<input type="date" class="form-control" style="width:auto;" title="Taken to" value="' + esc(f.to) + '" onchange="' + onchange + '(\'to\',this.value)">' +
        '<select class="form-control" style="width:auto;" onchange="' + onchange + '(\'by\',this.value)"><option value="">Anyone</option>' +
            (s.uploaders || []).map(function (u) { return '<option' + (u === f.by ? ' selected' : '') + '>' + esc(u) + '</option>'; }).join('') +
            (f.by && (s.uploaders || []).indexOf(f.by) < 0 ? '<option selected>' + esc(f.by) + '</option>' : '') + '</select>' +
        (extra || '') +
        ((f.kind || f.q || f.from || f.to || f.by || f.source)
            ? '<button class="btn btn-sm btn-outline" onclick="' + onchange + '(\'clear\')">Clear</button>' : '');
}

function fileQuery(f) {
    return (f.kind ? '&kind=' + encodeURIComponent(f.kind) : '') + (f.q ? '&q=' + encodeURIComponent(f.q) : '') +
        (f.from ? '&date_from=' + f.from : '') + (f.to ? '&date_to=' + f.to : '') +
        (f.by ? '&by=' + encodeURIComponent(f.by) : '');
}

function storageLine(s) {
    if (!s || !s.count) return '';
    return s.count + ' file' + (s.count === 1 ? '' : 's') + ' · ' + fileSize(s.stored_bytes) + ' stored' +
        (s.saved_bytes > 1024 ? ' · ' + fileSize(s.saved_bytes) + ' saved by making them smaller and keeping each once' : '');
}

var fileFilterTimer = null;
function filesFilter(key, value, typing) {
    if (key === 'clear') FILES.filter = { kind: '', q: '', from: '', to: '', by: '', source: '' };
    else FILES.filter[key] = value;
    clearTimeout(fileFilterTimer);
    fileFilterTimer = setTimeout(function () { refreshFilesModal(typing); }, typing ? 300 : 0);
}
window.filesFilter = filesFilter;

async function refreshFilesModal(keepFocus) {
    var d = await (await fetch('/api/files?attached_type=' + FILES.type + '&attached_id=' + FILES.id + fileQuery(FILES.filter),
                               { credentials: 'include' })).json();
    var list = d.files || [];
    // The counts on the chips are of everything here, not of what is filtered.
    if (!FILES.filter.kind && !FILES.filter.q && !FILES.filter.from && !FILES.filter.to && !FILES.filter.by) FILES.allSummary = d.summary;
    if (!keepFocus) document.getElementById('files-filters').innerHTML = fileFilterBar('files', FILES.filter, FILES.allSummary || d.summary, 'filesFilter');
    document.getElementById('files-summary').textContent = storageLine(d.summary);
    var filtered = FILES.filter.kind || FILES.filter.q || FILES.filter.from || FILES.filter.to || FILES.filter.by;
    document.getElementById('files-grid').innerHTML = list.length
        ? list.map(function (f) { return fileTile(f, !d.locked); }).join('')
        : '<p style="color:var(--text-secondary);grid-column:1/-1;">' + (filtered ? 'Nothing matches the filters.'
            : 'Nothing kept against this yet. On a phone, "Take a photo" opens the camera.') + '</p>';
}

async function filesPicked(input) {
    if (!input.files.length) return;
    var caption = document.getElementById('files-caption').value.trim();
    var kind = (document.getElementById('files-kind') || {}).value || '';
    var extra = {};
    if (caption) extra.caption = caption;
    if (kind) extra.kind = kind;
    await uploadFiles(input.files, FILES.type, FILES.id, extra);
    input.value = '';
    document.getElementById('files-caption').value = '';
    await refreshFilesModal();
    if (FILES.tab === 'photos' && currentView === 'drawings-view') loadDrawings();
}
window.filesPicked = filesPicked;

async function removeFile(id) {
    if (!confirm('Remove this file?')) return;
    var res = await fetch('/api/files/' + id, { method: 'DELETE', credentials: 'include' });
    var out = await res.json().catch(function () { return {}; });
    if (!res.ok) { showToast(out.detail || 'Could not remove it', 'error'); return; }
    if (document.getElementById('files-modal').style.display === 'flex') refreshFilesModal();
    if (currentView === 'drawings-view') loadDrawings();
}
window.removeFile = removeFile;

/* --- The Drawings & Photos screen ------------------------------------------ */

async function loadDrawings() {
    var sel = document.getElementById('drw-job');
    if (!sel) return;
    if (!sel.options.length) {
        await fillJobPicker('drw-job');
        if (sel.options.length && !sel.value) sel.selectedIndex = sel.options[0].value ? 0 : Math.min(1, sel.options.length - 1);
    }
    var jobId = parseInt(sel.value);
    if (FILES.jobId !== jobId) FILES.jobSummary = null;
    FILES.jobId = jobId;
    var host = document.getElementById('drw-body');
    if (!jobId) { host.innerHTML = '<p style="color:var(--text-secondary);">Pick a project.</p>'; return; }
    document.querySelectorAll('#drw-tabs button').forEach(function (b) {
        b.classList.toggle('active', b.dataset.tab === FILES.tab); });
    if (FILES.tab === 'photos') {
        var f = FILES.filter;
        var url = '/api/jobs/' + jobId + '/photos?kind=' + encodeURIComponent(f.kind || 'photo,drawing,document') +
            fileQuery(Object.assign({}, f, { kind: '' })) + (f.source ? '&source=' + encodeURIComponent(f.source) : '');
        var p = await (await fetch(url, { credentials: 'include' })).json();
        var sm = p.summary || {};
        if (!f.kind && !f.q && !f.from && !f.to && !f.by && !f.source) FILES.jobSummary = sm;
        var all = FILES.jobSummary || sm;
        document.getElementById('drw-stats').innerHTML =
            statCard('Drawings', String(all.drawings || 0)) + statCard('Photos', String(all.photos || 0)) +
            statCard('Documents', String(all.documents || 0)) + statCard('Storage used', fileSize(all.stored_bytes) || '0 KB');
        var sources = [['', 'Kept against: anything'], ['subcontract_order,work_order', 'Work orders'], ['diary', 'Site diary'],
                       ['measurement', 'Measurements'], ['variation', 'Variations'], ['job', 'The project'],
                       ['inspection,ncr', 'Quality'], ['incident', 'Safety']];
        var sourceSel = '<select class="form-control" style="width:auto;" onchange="projectFilesFilter(\'source\',this.value)">' +
            sources.map(function (o) { return '<option value="' + o[0] + '"' + (o[0] === (f.source || '') ? ' selected' : '') + '>' + esc(o[1]) + '</option>'; }).join('') +
            '</select>';
        if (!FILES.typing) {
            host.innerHTML = '<div style="margin-bottom:10px;display:flex;gap:8px;flex-wrap:wrap;">' +
                '<label class="btn btn-primary" style="cursor:pointer;margin:0;">+ Photos of the site' +
                '<input type="file" accept="image/*" capture="environment" multiple style="display:none;" onchange="projectPhotos(this)"></label>' +
                '<label class="btn btn-outline" style="cursor:pointer;margin:0;">+ Drawings for the project' +
                '<input type="file" accept=".pdf,.dwg,.dxf,image/*" multiple style="display:none;" onchange="projectPhotos(this,\'drawing\')"></label></div>' +
                '<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:8px;">' +
                fileFilterBar('proj', f, all, 'projectFilesFilter', sourceSel) + '</div>' +
                '<p id="proj-files-summary" style="font-size:0.78rem;color:var(--text-secondary);margin:0 0 10px;"></p>' +
                '<div id="proj-files-grid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;"></div>';
        }
        FILES.typing = false;
        document.getElementById('proj-files-summary').textContent = storageLine(sm);
        var filtered = f.kind || f.q || f.from || f.to || f.by || f.source;
        document.getElementById('proj-files-grid').innerHTML =
            (p.photos || []).map(function (x) { return fileTile(x, x.attached_type === 'job'); }).join('') ||
            '<p style="color:var(--text-secondary);">' + (filtered ? 'Nothing matches the filters.'
                : 'Nothing on this project yet. Photos and drawings added to work orders, diary days, measurements and variations appear here too.') + '</p>';
        return;
    }
    var d = await (await fetch('/api/jobs/' + jobId + '/drawings', { credentials: 'include' })).json();
    FILES.drawings = d.drawings || [];
    FILES.meta = d;
    var s = d.summary || {};
    document.getElementById('drw-stats').innerHTML =
        statCard('Drawings', String(s.drawings || 0)) +
        statCard('Good for construction', String(s.gfc || 0)) +
        statCard('Awaiting approval', String(s.awaiting || 0));
    var rf = FILES.regFilter;
    var shown = FILES.drawings.filter(function (w) {
        var words = (rf.q || '').toLowerCase();
        return (!words || ((w.number || '') + ' ' + (w.title || '')).toLowerCase().indexOf(words) >= 0) &&
            (!rf.discipline || w.discipline === rf.discipline) &&
            (!rf.status || (rf.status === 'none' ? !w.current_revision : w.status === rf.status));
    });
    var opts = function (list, cur, blank) {
        return '<option value="">' + esc(blank) + '</option>' + list.map(function (x) {
            var v = Array.isArray(x) ? x[0] : x, l = Array.isArray(x) ? x[1] : x;
            return '<option value="' + esc(v) + '"' + (v === cur ? ' selected' : '') + '>' + esc(l) + '</option>';
        }).join('');
    };
    var bar = '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px;align-items:center;">' +
        '<input class="form-control" id="drw-q" style="flex:1;min-width:180px;max-width:320px;" placeholder="Search number or title" value="' +
            esc(rf.q) + '" oninput="drawingFilter(\'q\',this.value)">' +
        '<select class="form-control" style="width:auto;" onchange="drawingFilter(\'discipline\',this.value)">' +
            opts((d.disciplines || []), rf.discipline, 'Every discipline') + '</select>' +
        '<select class="form-control" style="width:auto;" onchange="drawingFilter(\'status\',this.value)">' +
            opts((d.statuses || []).concat([['none', 'No sheet yet']]), rf.status, 'Every status') + '</select>' +
        '<span style="font-size:0.8rem;color:var(--text-secondary);">' + shown.length + ' of ' + FILES.drawings.length + '</span></div>';
    host.innerHTML = bar + '<div class="table-responsive"><table class="data-table"><thead><tr><th>Number</th><th>Title</th>' +
        '<th>Discipline</th><th>Revision</th><th>Status</th><th>Received</th><th></th></tr></thead><tbody>' +
        (shown.map(function (w) {
            var tone = w.status === 'Good for construction' ? 'good' : w.status === 'For approval' ? 'warn' : 'calm';
            return '<tr><td style="font-family:monospace;font-weight:600;">' + esc(w.number) + '</td><td>' + esc(w.title) + '</td>' +
                '<td>' + esc(w.discipline) + '</td><td style="font-family:monospace;">' + esc(w.current_revision || '—') +
                (w.revisions > 1 ? ' <span style="font-size:0.7rem;color:var(--text-secondary);">(' + w.revisions + ')</span>' : '') + '</td>' +
                '<td>' + (w.current_revision ? statusPill(w.status, tone) : '<span style="color:var(--text-secondary);">no sheet yet</span>') + '</td>' +
                '<td>' + esc(w.received_on || '') + '</td><td class="text-right" style="white-space:nowrap;">' +
                (w.current_file_id ? '<a class="btn btn-sm btn-outline" target="_blank" href="/api/files/' + w.current_file_id + '">Open</a> ' : '') +
                '<button class="btn btn-sm btn-outline" onclick="drawingRevision(' + w.id + ')">New revision</button> ' +
                '<button class="btn btn-sm btn-outline" onclick="drawingHistory(' + w.id + ')">History</button></td></tr>';
        }).join('') || '<tr><td colspan="7" style="text-align:center;padding:24px;color:var(--text-secondary);">' +
            (FILES.drawings.length ? 'No drawing matches the filters.'
                : 'No drawings on the register. Add each sheet by its number, then its revisions as they arrive.') + '</td></tr>') +
        '</tbody></table></div>';
    if (FILES.regTyping) {
        var q = document.getElementById('drw-q');
        if (q) { q.focus(); q.setSelectionRange(q.value.length, q.value.length); }
        FILES.regTyping = false;
    }
}
window.loadDrawings = loadDrawings;

var drawingFilterTimer = null;
function drawingFilter(key, value) {
    FILES.regFilter[key] = value;
    FILES.regTyping = key === 'q';
    clearTimeout(drawingFilterTimer);
    drawingFilterTimer = setTimeout(loadDrawings, key === 'q' ? 250 : 0);
}
window.drawingFilter = drawingFilter;

var projFilterTimer = null;
function projectFilesFilter(key, value, typing) {
    if (key === 'clear') FILES.filter = { kind: '', q: '', from: '', to: '', by: '', source: '' };
    else FILES.filter[key] = value;
    FILES.typing = !!typing;
    clearTimeout(projFilterTimer);
    projFilterTimer = setTimeout(loadDrawings, typing ? 300 : 0);
}
window.projectFilesFilter = projectFilesFilter;

function drawingsTab(t) {
    FILES.tab = t;
    FILES.filter = { kind: '', q: '', from: '', to: '', by: '', source: '' };
    FILES.jobSummary = null;
    loadDrawings();
}
window.drawingsTab = drawingsTab;

async function projectPhotos(input, kind) {
    if (!input.files.length || !FILES.jobId) return;
    await uploadFiles(input.files, 'job', FILES.jobId, kind ? { kind: kind } : {});
    input.value = '';
    loadDrawings();
}
window.projectPhotos = projectPhotos;

async function drawingAdd() {
    if (!FILES.jobId) { showToast('Pick the project first', 'error'); return; }
    var number = prompt('Drawing number, as printed on the sheet (e.g. STR-101):');
    if (!number) return;
    var title = prompt('What it shows (e.g. Raft reinforcement):') || '';
    var disc = prompt('Discipline - ' + ((FILES.meta || {}).disciplines || []).join(', '), 'Structural') || 'Structural';
    var res = await fetch('/api/jobs/' + FILES.jobId + '/drawings', {
        method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ number: number, title: title, discipline: disc }) });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not add it', 'error'); return; }
    showToast(out.drawing.number + ' added. Now add its first revision.', 'success');
    await loadDrawings();
    drawingRevision(out.drawing.id);
}
window.drawingAdd = drawingAdd;

function drawingRevision(id) {
    var w = FILES.drawings.filter(function (x) { return x.id === id; })[0] || {};
    FILES.revFor = id;
    document.getElementById('drwrev-title').textContent = 'New revision — ' + (w.number || '');
    document.getElementById('drwrev-rev').value = '';
    document.getElementById('drwrev-from').value = '';
    document.getElementById('drwrev-remarks').value = '';
    document.getElementById('drwrev-date').value = localDate(new Date());
    document.getElementById('drwrev-file').value = '';
    document.getElementById('drwrev-status').innerHTML = ((FILES.meta || {}).statuses || [])
        .filter(function (s) { return s !== 'Superseded'; })
        .map(function (s) { return '<option>' + esc(s) + '</option>'; }).join('');
    openModal('drwrev-modal');
}
window.drawingRevision = drawingRevision;

async function drawingRevisionSave() {
    var file = document.getElementById('drwrev-file').files[0];
    var rev = document.getElementById('drwrev-rev').value.trim();
    if (!file || !rev) { showToast('The sheet and its revision are both needed', 'error'); return; }
    var fd = new FormData();
    fd.append('file', file, file.name);
    fd.append('revision', rev);
    fd.append('status', document.getElementById('drwrev-status').value);
    fd.append('received_on', document.getElementById('drwrev-date').value);
    fd.append('received_from', document.getElementById('drwrev-from').value);
    fd.append('remarks', document.getElementById('drwrev-remarks').value);
    var res = await fetch('/api/drawings/' + FILES.revFor + '/revisions', { method: 'POST', credentials: 'include', body: fd });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not add it', 'error'); return; }
    showToast(out.message, 'success');
    closeModal('drwrev-modal');
    loadDrawings();
}
window.drawingRevisionSave = drawingRevisionSave;

async function drawingHistory(id) {
    var d = (await (await fetch('/api/drawings/' + id, { credentials: 'include' })).json()).drawing;
    document.getElementById('drwhist-title').textContent = d.number + ' — ' + (d.title || '');
    document.getElementById('drwhist-body').innerHTML = '<table class="data-table"><thead><tr><th>Rev</th><th>Status</th>' +
        '<th>Received</th><th>From</th><th>Remarks</th><th></th></tr></thead><tbody>' +
        d.history.map(function (h) {
            return '<tr' + (h.current ? ' style="font-weight:600;"' : ' style="color:var(--text-secondary);"') + '>' +
                '<td style="font-family:monospace;">' + esc(h.revision) + '</td><td>' + esc(h.status) + '</td>' +
                '<td>' + esc(h.received_on) + '</td><td>' + esc(h.received_from) + '</td><td>' + esc(h.remarks) + '</td>' +
                '<td>' + (h.file_id ? '<a class="btn btn-sm btn-outline" target="_blank" href="/api/files/' + h.file_id + '">Open</a>' : '') + '</td></tr>';
        }).join('') + '</tbody></table>' +
        (d.current_revision ? '<div style="margin-top:12px;display:flex;gap:8px;flex-wrap:wrap;">' +
            ['For approval', 'Approved', 'Good for construction'].map(function (s) {
                return '<button class="btn btn-sm btn-outline" onclick="drawingStatus(' + d.id + ',\'' + s + '\')">Mark ' + s.toLowerCase() + '</button>';
            }).join('') + '</div>' : '');
    openModal('drwhist-modal');
}
window.drawingHistory = drawingHistory;

async function drawingStatus(id, status) {
    var res = await fetch('/api/drawings/' + id + '/status', {
        method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: status }) });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not change it', 'error'); return; }
    showToast(out.drawing.number + ': ' + status.toLowerCase() + '.', 'success');
    closeModal('drwhist-modal');
    loadDrawings();
}
window.drawingStatus = drawingStatus;
