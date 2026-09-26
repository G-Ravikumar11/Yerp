/* ===========================================================================
   sw.js - the app on a phone with no signal.

   Pages, scripts and styles come from the network when there is one and from
   the last copy when there is not, so the app still opens on a site where the
   phone shows one bar. Of the API, only what the diary needs to be written
   is kept - who is signed in, the projects, the days already written - and
   only ever as a fallback to the live answer. Everything else is left to the
   network. Signing out wipes what was kept.
   =========================================================================== */

var SHELL = 'yerp-shell-v1';
var API = 'yerp-api';
var API_KEPT = [/^\/api\/client\/me$/, /^\/api\/employee\/auth\/me$/, /^\/api\/jobs$/,
                /^\/api\/employee\/jobs$/, /^\/api\/diary$/, /^\/api\/diary\/\d+$/,
                /^\/api\/diary-labour\/\d+$/];

self.addEventListener('install', function (e) {
    e.waitUntil(caches.open(SHELL).then(function (c) {
        return c.addAll(['/app.html', '/styles.css', '/manifest.webmanifest', '/icons/icon-192.png']);
    }).catch(function () {}));
    self.skipWaiting();
});

self.addEventListener('activate', function (e) {
    e.waitUntil(caches.keys().then(function (keys) {
        return Promise.all(keys.filter(function (k) { return k !== SHELL && k !== API; })
                               .map(function (k) { return caches.delete(k); }));
    }).then(function () { return self.clients.claim(); }));
});

function keep(cacheName, req, res) {
    if (res && res.ok && res.type === 'basic') {
        var copy = res.clone();
        caches.open(cacheName).then(function (c) { c.put(req, copy); });
    }
    return res;
}

self.addEventListener('fetch', function (e) {
    var req = e.request;
    if (req.method !== 'GET') return;
    var url = new URL(req.url);
    if (url.origin !== self.location.origin) return;

    if (url.pathname.indexOf('/api/') === 0) {
        if (!API_KEPT.some(function (r) { return r.test(url.pathname); })) return;
        e.respondWith(fetch(req).then(function (res) { return keep(API, req, res); }).catch(function () {
            return caches.match(req).then(function (hit) {
                return hit || new Response(JSON.stringify({ detail: 'Offline' }),
                    { status: 503, headers: { 'Content-Type': 'application/json' } });
            });
        }));
        return;
    }

    if (req.mode === 'navigate' || /\.(js|css|png|svg|webmanifest|html)$/.test(url.pathname)) {
        e.respondWith(fetch(req).then(function (res) { return keep(SHELL, req, res); }).catch(function () {
            return caches.match(req).then(function (hit) {
                if (hit) return hit;
                return caches.match(req, { ignoreSearch: true }).then(function (loose) {
                    if (loose) return loose;
                    if (req.mode === 'navigate') return caches.match('/app.html');
                    return new Response('', { status: 504 });
                });
            });
        }));
    }
});

self.addEventListener('message', function (e) {
    if (e.data === 'forget') caches.delete(API);
});
