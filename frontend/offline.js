/* ===========================================================================
   offline.js - the app on a phone: installed like an app, a camera button,
   and a site diary that can be written with no signal.

   A day written offline goes into an outbox on the phone, photos and all,
   and is sent by itself the moment there is signal again. Anything the
   server then refuses (a day already written by somebody else, say) stays
   in the outbox with the reason, to be put right rather than lost.
   =========================================================================== */

var OFFLINE = { prompt: null, db: null };

if ('serviceWorker' in navigator) {
    window.addEventListener('load', function () {
        navigator.serviceWorker.register('/sw.js').catch(function (e) { console.warn('No offline copy:', e); });
    });
}

/* --- Installing it -------------------------------------------------------- */

window.addEventListener('beforeinstallprompt', function (e) {
    e.preventDefault();
    OFFLINE.prompt = e;
    document.querySelectorAll('.install-app').forEach(function (b) { b.style.display = ''; });
});
window.addEventListener('appinstalled', function () {
    OFFLINE.prompt = null;
    document.querySelectorAll('.install-app').forEach(function (b) { b.style.display = 'none'; });
    if (typeof showToast === 'function') showToast('Installed. It opens from the home screen now.', 'success');
});

async function installApp() {
    if (!OFFLINE.prompt) {
        showToast(/iphone|ipad/i.test(navigator.userAgent)
            ? 'On an iPhone: tap Share, then "Add to Home Screen".'
            : 'Open the browser menu and choose "Install app" or "Add to Home screen".', 'info');
        return;
    }
    OFFLINE.prompt.prompt();
    await OFFLINE.prompt.userChoice;
    OFFLINE.prompt = null;
}
window.installApp = installApp;

function isInstalled() {
    return window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;
}
window.isInstalled = isInstalled;

/* Signing out leaves nothing behind on a shared phone. */
function forgetOfflineCopy() {
    try {
        if (navigator.serviceWorker && navigator.serviceWorker.controller) navigator.serviceWorker.controller.postMessage('forget');
        if (window.caches) caches.delete('yerp-api');
    } catch (e) {}
}
window.forgetOfflineCopy = forgetOfflineCopy;

/* --- Signal ------------------------------------------------------------------ */

function paintOnline() {
    var bar = document.getElementById('offline-bar');
    if (bar) bar.style.display = navigator.onLine ? 'none' : '';
}
window.addEventListener('online', function () { paintOnline(); outboxFlush(); });
window.addEventListener('offline', paintOnline);
document.addEventListener('DOMContentLoaded', function () {
    paintOnline();
    setTimeout(outboxFlush, 4000);
    // Opened from a home-screen shortcut: /app.html#diary-view
    setTimeout(function () {
        var v = (location.hash || '').slice(1);
        if (v && /-view$/.test(v) && document.getElementById(v) && typeof showView === 'function') showView(v);
    }, 1200);
});

/* --- The outbox -------------------------------------------------------------- */

function outboxDb() {
    if (OFFLINE.db) return Promise.resolve(OFFLINE.db);
    return new Promise(function (resolve, reject) {
        var req = indexedDB.open('yerp', 1);
        req.onupgradeneeded = function () { req.result.createObjectStore('outbox', { keyPath: 'id', autoIncrement: true }); };
        req.onsuccess = function () { OFFLINE.db = req.result; resolve(OFFLINE.db); };
        req.onerror = function () { reject(req.error); };
    });
}

function outboxTx(mode, fn) {
    return outboxDb().then(function (db) {
        return new Promise(function (resolve, reject) {
            var tx = db.transaction('outbox', mode), store = tx.objectStore('outbox'), out;
            var r = fn(store);
            if (r) r.onsuccess = function () { out = r.result; };
            tx.oncomplete = function () { resolve(out); };
            tx.onerror = function () { reject(tx.error); };
        });
    });
}

function outboxAll() { return outboxTx('readonly', function (s) { return s.getAll(); }).then(function (r) { return r || []; }); }
function outboxAdd(item) { return outboxTx('readwrite', function (s) { return s.add(item); }); }
function outboxPut(item) { return outboxTx('readwrite', function (s) { return s.put(item); }); }
function outboxDelete(id) { return outboxTx('readwrite', function (s) { return s.delete(id); }); }
window.outboxAll = outboxAll;

async function outboxKeepDiary(url, method, body, submit, photos, label) {
    await outboxAdd({ kind: 'diary', url: url, method: method, body: body, submit: !!submit,
                      photos: photos || [], label: label || '', kept_at: new Date().toISOString(), error: '' });
    paintOutbox();
}
window.outboxKeepDiary = outboxKeepDiary;

var FLUSHING = false;
async function outboxFlush() {
    if (FLUSHING || !navigator.onLine || !window.indexedDB) return;
    FLUSHING = true;
    var sent = 0;
    try {
        var items = await outboxAll();
        for (var i = 0; i < items.length; i++) {
            var it = items[i];
            if (it.error) continue;              // waiting for a person to look at it
            var res;
            try {
                res = await fetch(it.url, { method: it.method, credentials: 'include',
                    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(it.body) });
            } catch (e) { break; }               // the signal went again
            if (res.status === 401) break;       // signed out; keep it for later
            var out = {};
            try { out = await res.json(); } catch (e) {}
            if (!res.ok) { it.error = out.detail || ('Refused (' + res.status + ')'); await outboxPut(it); continue; }
            var id = out.diary && out.diary.id;
            if (id && it.photos && it.photos.length && typeof uploadFiles === 'function') {
                try { await uploadFiles(it.photos, 'diary', id); } catch (e) {}
            }
            if (id && it.submit) {
                try { await fetch('/api/diary/' + id + '/submit', { method: 'POST', credentials: 'include' }); } catch (e) {}
            }
            await outboxDelete(it.id);
            sent++;
        }
    } finally {
        FLUSHING = false;
    }
    if (sent) {
        if (typeof showToast === 'function') showToast(sent + ' diary day' + (sent === 1 ? '' : 's') + ' written offline sent.', 'success');
        if (typeof refreshDiary === 'function' && document.getElementById('diary-view') &&
            document.getElementById('diary-view').style.display !== 'none') refreshDiary();
    }
    paintOutbox();
}
window.outboxFlush = outboxFlush;

async function paintOutbox() {
    var host = document.getElementById('diary-outbox');
    if (!host || !window.indexedDB) return;
    var items = [];
    try { items = await outboxAll(); } catch (e) { return; }
    if (!items.length) { host.innerHTML = ''; host.style.display = 'none'; return; }
    host.style.display = '';
    var waiting = items.filter(function (i) { return !i.error; }).length;
    host.innerHTML = '<div style="display:flex;justify-content:space-between;gap:10px;align-items:center;flex-wrap:wrap;">' +
        '<div><strong>' + items.length + ' day' + (items.length === 1 ? '' : 's') + ' kept on this phone</strong>' +
        '<div style="font-size:0.78rem;color:var(--text-secondary);">' + (waiting ? 'They go up by themselves when there is signal.' : 'The server turned these down - see why below.') + '</div></div>' +
        (waiting ? '<button class="btn btn-sm btn-outline" onclick="outboxFlush()">Send now</button>' : '') + '</div>' +
        items.map(function (i) {
            return '<div style="margin-top:8px;font-size:0.82rem;display:flex;justify-content:space-between;gap:8px;">' +
                '<span>' + esc(i.label || i.body.diary_date) + (i.photos && i.photos.length ? ' · ' + i.photos.length + ' photo' + (i.photos.length === 1 ? '' : 's') : '') +
                (i.submit ? ' · to be signed off' : '') +
                (i.error ? '<br><span style="color:var(--danger-color);">' + esc(i.error) + '</span>' : '') + '</span>' +
                (i.error ? '<span style="white-space:nowrap;"><button class="btn btn-sm btn-outline" onclick="outboxRetry(' + i.id + ')">Try again</button> ' +
                    '<button class="btn btn-sm btn-outline" onclick="outboxDiscard(' + i.id + ')">Discard</button></span>' : '') + '</div>';
        }).join('');
}
window.paintOutbox = paintOutbox;

async function outboxRetry(id) {
    var items = await outboxAll();
    var it = items.find(function (x) { return x.id === id; });
    if (!it) return;
    it.error = '';
    await outboxPut(it);
    outboxFlush();
}
window.outboxRetry = outboxRetry;

async function outboxDiscard(id) {
    if (!confirm('Throw this day away? It was never sent.')) return;
    await outboxDelete(id);
    paintOutbox();
}
window.outboxDiscard = outboxDiscard;
