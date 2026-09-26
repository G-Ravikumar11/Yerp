/* ===========================================================================
   chat.js - project threads: the office and the site in one conversation,
   photos beside the words, @names that ring the bell.
   =========================================================================== */

var CHAT = { jobId: 0, threadId: 0, lastId: 0, people: [], me: '', timer: null, files: [] };

async function loadChat() {
    var sel = document.getElementById('chat-job');
    if (!sel) return;
    if (!sel.options.length) {
        await fillJobPicker('chat-job');
        sel.options[0].textContent = 'Every project';
        var p = await (await fetch('/api/chat/people', { credentials: 'include' })).json();
        CHAT.people = p.people || []; CHAT.me = p.me;
    }
    CHAT.jobId = parseInt(sel.value) || 0;
    await chatThreads();
    if (CHAT.threadId) chatOpen(CHAT.threadId, true);
    chatPoll();
}
window.loadChat = loadChat;

function chatVisible() {
    var v = document.getElementById('chat-view');
    return v && v.style.display !== 'none';
}

function chatPoll() {
    if (CHAT.timer) clearInterval(CHAT.timer);
    CHAT.timer = setInterval(async function () {
        if (!chatVisible() || document.hidden) return;
        await chatThreads();
        if (CHAT.threadId) chatMore();
    }, 8000);
}

function chatWhen(at) {
    if (!at) return '';
    var today = localDate(new Date());
    return at.slice(0, 10) === today ? at.slice(11, 16) : at.slice(8, 10) + '/' + at.slice(5, 7) + ' ' + at.slice(11, 16);
}

async function chatThreads() {
    var q = CHAT.jobId ? '?job_id=' + CHAT.jobId : '';
    var d = await (await fetch('/api/chat/threads' + q, { credentials: 'include' })).json();
    chatBadge(d.unread);
    var host = document.getElementById('chat-list');
    host.innerHTML = (d.threads || []).length ? d.threads.map(function (t) {
        return '<div class="chat-thread' + (t.id === CHAT.threadId ? ' active' : '') + (t.closed ? ' closed' : '') +
            '" onclick="chatOpen(' + t.id + ')">' +
            '<div style="display:flex;justify-content:space-between;gap:8px;">' +
                '<div style="font-weight:600;font-size:0.88rem;">' + esc(t.title) + '</div>' +
                (t.unread ? '<span class="chat-unread">' + t.unread + '</span>' : '<span style="font-size:0.7rem;color:var(--text-secondary);white-space:nowrap;">' + chatWhen(t.last_message_at) + '</span>') +
            '</div>' +
            (CHAT.jobId ? '' : '<div style="font-size:0.72rem;color:var(--primary-color);">' + esc(t.project) + '</div>') +
            (t.last ? '<div style="font-size:0.78rem;color:var(--text-secondary);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">' +
                esc(t.last.author_name) + ': ' + esc(t.last.body) + '</div>' : '') +
            (t.closed ? '<div style="font-size:0.7rem;color:var(--text-secondary);">closed</div>' : '') + '</div>';
    }).join('') : '<div style="padding:24px;text-align:center;color:var(--text-secondary);font-size:0.86rem;">' +
        'No threads yet. Start one for anything the site and the office need to agree on.</div>';
}

function chatBadge(n) {
    var nav = document.getElementById('nav-chat');
    if (!nav) return;
    var b = nav.querySelector('.chat-unread');
    if (!n) { if (b) b.remove(); return; }
    if (!b) { b = document.createElement('span'); b.className = 'chat-unread'; b.style.marginLeft = '6px'; nav.appendChild(b); }
    b.textContent = n > 99 ? '99+' : String(n);
}

function chatMessageHtml(m) {
    var files = (m.files || []).map(function (f) {
        return f.is_image
            ? '<a href="' + f.url + '" target="_blank" rel="noopener"><img src="' + f.thumb_url + '" alt="' + esc(f.name) +
              '" style="max-width:220px;max-height:220px;border-radius:8px;display:block;margin-top:4px;" onerror="this.src=\'' + f.url + '\'"></a>'
            : '<a href="' + f.url + '" target="_blank" rel="noopener" style="display:block;margin-top:4px;font-size:0.8rem;">📎 ' + esc(f.name) + '</a>';
    }).join('');
    var body = m.deleted ? '<em style="color:var(--text-secondary);">message removed</em>'
        : esc(m.body).replace(/@([A-Za-z][\w.]*(?: [A-Z][\w.]*)?)/g, '<strong>@$1</strong>').replace(/\n/g, '<br>');
    return '<div class="chat-msg' + (m.mine ? ' mine' : '') + '" data-id="' + m.id + '">' +
        (m.mine ? '' : '<div class="chat-author">' + esc(m.author_name) + '</div>') +
        '<div class="chat-bubble">' + body + files + '</div>' +
        '<div class="chat-time">' + chatWhen(m.created_at) +
            (m.mine && !m.deleted ? ' · <a href="#" onclick="event.preventDefault();chatRemove(' + m.id + ')">remove</a>' : '') + '</div></div>';
}

async function chatOpen(id, keep) {
    CHAT.threadId = id;
    var d = await (await fetch('/api/chat/threads/' + id, { credentials: 'include' })).json();
    if (!d.thread) return;
    var t = d.thread;
    document.getElementById('chat-pane').classList.add('open');
    document.getElementById('chat-head').innerHTML =
        '<button class="btn btn-sm btn-outline chat-back" onclick="chatBack()">&larr;</button>' +
        '<div style="flex:1;min-width:0;"><div style="font-weight:700;">' + esc(t.title) + '</div>' +
        '<div style="font-size:0.74rem;color:var(--text-secondary);">' + esc(t.project) + ' · started by ' + esc(t.started_by_name) + '</div></div>' +
        '<button class="btn btn-sm btn-outline" onclick="chatClose(' + t.id + ',' + (t.closed ? 'false' : 'true') + ')">' + (t.closed ? 'Reopen' : 'Close') + '</button>';
    var box = document.getElementById('chat-messages');
    box.innerHTML = d.messages.map(chatMessageHtml).join('') ||
        '<div style="padding:30px;text-align:center;color:var(--text-secondary);">Nothing said yet.</div>';
    CHAT.lastId = d.messages.length ? d.messages[d.messages.length - 1].id : 0;
    box.scrollTop = box.scrollHeight;
    document.getElementById('chat-compose').style.display = t.closed ? 'none' : '';
    document.getElementById('chat-closed').style.display = t.closed ? '' : 'none';
    if (!keep) document.getElementById('chat-text').focus();
    chatThreads();
}
window.chatOpen = chatOpen;

async function chatMore() {
    var d = await (await fetch('/api/chat/threads/' + CHAT.threadId + '?after=' + CHAT.lastId, { credentials: 'include' })).json();
    if (!d.messages || !d.messages.length) return;
    var box = document.getElementById('chat-messages');
    var atEnd = box.scrollHeight - box.scrollTop - box.clientHeight < 60;
    if (!CHAT.lastId) box.innerHTML = '';
    d.messages.forEach(function (m) { box.insertAdjacentHTML('beforeend', chatMessageHtml(m)); });
    CHAT.lastId = d.messages[d.messages.length - 1].id;
    if (atEnd) box.scrollTop = box.scrollHeight;
}

function chatBack() {
    document.getElementById('chat-pane').classList.remove('open');
    CHAT.threadId = 0;
    chatThreads();
}
window.chatBack = chatBack;

async function chatSend() {
    var text = document.getElementById('chat-text');
    var body = text.value.trim();
    if (!body && !CHAT.files.length) return;
    var res = await fetch('/api/chat/threads/' + CHAT.threadId + '/messages', { method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ body: body, file_ids: CHAT.files.map(function (f) { return f.id; }) }) });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Not sent', 'error'); return; }
    text.value = '';
    CHAT.files = []; chatAttached();
    await chatMore();
    chatThreads();
}
window.chatSend = chatSend;

function chatKey(e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); chatSend(); return; }
}
window.chatKey = chatKey;

/* @names: typing "@ra" offers the people whose names start that way. */
function chatSuggest() {
    var ta = document.getElementById('chat-text'), box = document.getElementById('chat-suggest');
    var upto = ta.value.slice(0, ta.selectionStart);
    var m = upto.match(/@([\w ]{0,20})$/);
    if (!m) { box.style.display = 'none'; return; }
    var q = m[1].toLowerCase();
    var hits = CHAT.people.filter(function (p) { return p.key !== CHAT.me && p.name.toLowerCase().indexOf(q) === 0; }).slice(0, 6);
    if (!hits.length) { box.style.display = 'none'; return; }
    box.innerHTML = hits.map(function (p) {
        return '<div class="chat-person" onmousedown="event.preventDefault();chatPick(\'' + esc(p.name).replace(/'/g, '\\\'') + '\')">' +
            esc(p.name) + ' <span style="color:var(--text-secondary);font-size:0.72rem;">' + esc(p.role) + '</span></div>';
    }).join('');
    box.style.display = '';
}
window.chatSuggest = chatSuggest;

function chatPick(name) {
    var ta = document.getElementById('chat-text');
    var upto = ta.value.slice(0, ta.selectionStart), rest = ta.value.slice(ta.selectionStart);
    upto = upto.replace(/@([\w ]{0,20})$/, '@' + name + ' ');
    ta.value = upto + rest;
    ta.selectionStart = ta.selectionEnd = upto.length;
    document.getElementById('chat-suggest').style.display = 'none';
    ta.focus();
}
window.chatPick = chatPick;

async function chatAttach(input) {
    var list = Array.prototype.slice.call(input.files || []);
    input.value = '';
    for (var i = 0; i < list.length; i++) {
        var f = list[i], fd = new FormData();
        var big = typeof shrinkImage === 'function' ? await shrinkImage(f, 1600, 0.82) : null;
        if (big) {
            fd.append('file', big, f.name.replace(/\.[^.]+$/, '') + '.jpg');
            var small = await shrinkImage(f, 360, 0.7);
            if (small) fd.append('thumb', small, 'thumb.jpg');
        } else {
            fd.append('file', f, f.name);
        }
        var res = await fetch('/api/chat/threads/' + CHAT.threadId + '/files', { method: 'POST', credentials: 'include', body: fd });
        var out = await res.json();
        if (!res.ok) { showToast(out.detail || 'Not attached', 'error'); continue; }
        CHAT.files.push(out.file);
    }
    chatAttached();
}
window.chatAttach = chatAttach;

function chatAttached() {
    document.getElementById('chat-attached').innerHTML = CHAT.files.map(function (f, i) {
        return '<span class="chat-chip">' + esc(f.name) + ' <a href="#" onclick="event.preventDefault();CHAT.files.splice(' + i + ',1);chatAttached()">&times;</a></span>';
    }).join('');
}
window.chatAttached = chatAttached;

async function chatRemove(id) {
    if (!confirm('Take this message back?')) return;
    var res = await fetch('/api/chat/messages/' + id, { method: 'DELETE', credentials: 'include' });
    if (!res.ok) { showToast('Not removed', 'error'); return; }
    chatOpen(CHAT.threadId, true);
}
window.chatRemove = chatRemove;

async function chatClose(id, close) {
    var res = await fetch('/api/chat/threads/' + id + '/' + (close ? 'close' : 'reopen'), { method: 'POST', credentials: 'include' });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Not done', 'error'); return; }
    showToast(out.message, 'success');
    chatOpen(id, true);
}
window.chatClose = chatClose;

function chatNew() {
    var sel = document.getElementById('chatnew-job');
    sel.innerHTML = document.getElementById('chat-job').innerHTML;
    sel.options[0].textContent = 'Pick the project';
    sel.value = CHAT.jobId ? String(CHAT.jobId) : '';
    document.getElementById('chatnew-title').value = '';
    document.getElementById('chatnew-body').value = '';
    openModal('chatnew-modal');
}
window.chatNew = chatNew;

async function chatStart() {
    var jobId = parseInt(document.getElementById('chatnew-job').value) || 0;
    if (!jobId) { showToast('Which project is it about?', 'error'); return; }
    var res = await fetch('/api/chat/threads', { method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_id: jobId, title: document.getElementById('chatnew-title').value,
                               body: document.getElementById('chatnew-body').value }) });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Not started', 'error'); return; }
    closeModal('chatnew-modal');
    await chatThreads();
    chatOpen(out.thread.id);
}
window.chatStart = chatStart;

// The menu's unread count, kept fresh while the app is open.
setInterval(function () {
    if (!document.getElementById('nav-chat') || document.hidden) return;
    fetch('/api/chat/unread', { credentials: 'include' }).then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) { if (d) chatBadge(d.unread); }).catch(function () {});
}, 60000);
