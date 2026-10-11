/* The previous app's offline worker. Nothing uses it any more: it removes itself and what it kept,
   so a phone that installed it does not go on serving old pages. The new app has its own worker under /next/. */
self.addEventListener('install', function () { self.skipWaiting(); });
self.addEventListener('activate', function (e) {
    e.waitUntil(caches.keys().then(function (keys) {
        return Promise.all(keys.filter(function (k) { return k.indexOf('yerp-') === 0; }).map(function (k) { return caches.delete(k); }));
    }).then(function () { return self.registration.unregister(); }));
});
