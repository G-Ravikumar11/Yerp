/* ===========================================================================
   files.js - site photos and the drawings register.

   openFiles() is the one window for the photos and papers kept against any
   record - a diary day, a measurement, a variation, the project itself. On a
   phone the button opens the camera. Photos are made smaller before they go
   up, so a day's pictures cost a few hundred kilobytes, not forty megabytes.

   The Drawings & Photos screen is the project's register: every sheet, every
   revision kept, the one to build to marked, and the project's photographs.
   =========================================================================== */

var FILES = { type: null, id: null, title: '', jobId: null, tab: 'drawings', drawings: [] };

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
        var big = await shrinkImage(f, 1600, 0.82);
        if (big) {
            fd.append('file', big, f.name.replace(/\.[^.]+$/, '') + '.jpg');
            var small = await shrinkImage(f, 360, 0.7);
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

function fileTile(f, canDelete) {
    var inner = f.is_image
        ? '<img src="' + f.thumb_url + '" alt="" loading="lazy" style="width:100%;height:120px;object-fit:cover;border-radius:6px;display:block;">'
        : '<div style="height:120px;display:flex;align-items:center;justify-content:center;border-radius:6px;' +
          'background:var(--bg-hover,rgba(0,0,0,0.04));font-weight:700;color:var(--text-secondary);">' +
          esc((f.name.split('.').pop() || 'file').toUpperCase()) + '</div>';
    return '<div style="border:1px solid var(--border-color);border-radius:8px;padding:6px;">' +
        '<a href="' + f.url + '" target="_blank" rel="noopener">' + inner + '</a>' +
        '<div style="font-size:0.74rem;margin-top:4px;line-height:1.3;">' + esc(f.caption || f.name) + '</div>' +
        '<div style="font-size:0.68rem;color:var(--text-secondary);">' + esc(f.taken_on || '') +
        (f.of ? ' &middot; ' + esc(f.of) : '') + (f.uploaded_by_name ? ' &middot; ' + esc(f.uploaded_by_name) : '') + '</div>' +
        (canDelete ? '<button class="btn btn-sm btn-outline" style="margin-top:4px;font-size:0.7rem;padding:1px 6px;" ' +
            'onclick="removeFile(' + f.id + ')">Remove</button>' : '') + '</div>';
}

async function openFiles(attachedType, attachedId, title) {
    FILES.type = attachedType; FILES.id = attachedId; FILES.title = title || '';
    document.getElementById('files-title').textContent = 'Photos & files — ' + (title || '');
    await refreshFilesModal();
    openModal('files-modal');
}
window.openFiles = openFiles;

async function refreshFilesModal() {
    var d = await (await fetch('/api/files?attached_type=' + FILES.type + '&attached_id=' + FILES.id,
                               { credentials: 'include' })).json();
    var list = d.files || [];
    document.getElementById('files-grid').innerHTML = list.length
        ? list.map(function (f) { return fileTile(f, !d.locked); }).join('')
        : '<p style="color:var(--text-secondary);grid-column:1/-1;">Nothing kept against this yet. On a phone, "Add photos" opens the camera.</p>';
}

async function filesPicked(input) {
    if (!input.files.length) return;
    var caption = document.getElementById('files-caption').value.trim();
    await uploadFiles(input.files, FILES.type, FILES.id, caption ? { caption: caption } : {});
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
    FILES.jobId = jobId;
    var host = document.getElementById('drw-body');
    if (!jobId) { host.innerHTML = '<p style="color:var(--text-secondary);">Pick a project.</p>'; return; }
    document.querySelectorAll('#drw-tabs button').forEach(function (b) {
        b.classList.toggle('active', b.dataset.tab === FILES.tab); });
    if (FILES.tab === 'photos') {
        var p = await (await fetch('/api/jobs/' + jobId + '/photos', { credentials: 'include' })).json();
        document.getElementById('drw-stats').innerHTML = statCard('Photos', String((p.photos || []).length));
        host.innerHTML = '<div style="margin-bottom:10px;"><label class="btn btn-primary" style="cursor:pointer;">+ Photos of the site' +
            '<input type="file" accept="image/*" capture="environment" multiple style="display:none;" ' +
            'onchange="projectPhotos(this)"></label></div>' +
            '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;">' +
            ((p.photos || []).map(function (f) { return fileTile(f, f.attached_type === 'job'); }).join('') ||
             '<p style="color:var(--text-secondary);">No photographs on this project yet. Photos added to diary days, measurements and variations appear here too.</p>') +
            '</div>';
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
    host.innerHTML = '<div class="table-responsive"><table class="data-table"><thead><tr><th>Number</th><th>Title</th>' +
        '<th>Discipline</th><th>Revision</th><th>Status</th><th>Received</th><th></th></tr></thead><tbody>' +
        (FILES.drawings.map(function (w) {
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
            'No drawings on the register. Add each sheet by its number, then its revisions as they arrive.</td></tr>') +
        '</tbody></table></div>';
}
window.loadDrawings = loadDrawings;

function drawingsTab(t) { FILES.tab = t; loadDrawings(); }
window.drawingsTab = drawingsTab;

async function projectPhotos(input) {
    if (!input.files.length || !FILES.jobId) return;
    await uploadFiles(input.files, 'job', FILES.jobId, {});
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
