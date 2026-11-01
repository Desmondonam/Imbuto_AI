// Pages work offline after one visit. Queued photos live in the page's IndexedDB (photo.js).
var CACHE = 'imbuto-v1', SHELL = ['/', '/offline', '/prices', '/ask', '/photo', '/static/photo.js'];
self.addEventListener('install', function (e) {
  e.waitUntil(caches.open(CACHE).then(function (c) { return c.addAll(SHELL); }).then(function () { return self.skipWaiting(); }));
});
self.addEventListener('activate', function (e) {
  e.waitUntil(caches.keys().then(function (keys) {
    return Promise.all(keys.filter(function (k) { return k !== CACHE; }).map(function (k) { return caches.delete(k); }));
  }).then(function () { return self.clients.claim(); }));
});
self.addEventListener('fetch', function (e) {
  if (e.request.method !== 'GET') return;
  e.respondWith(fetch(e.request).then(function (r) {
    var u = new URL(e.request.url);
    if (r.ok && u.origin === location.origin && u.pathname !== '/ops') {
      var copy = r.clone(); caches.open(CACHE).then(function (c) { c.put(e.request, copy); });
    }
    return r;
  }).catch(function () {
    return caches.match(e.request).then(function (m) { return m || caches.match('/offline'); });
  }));
});
