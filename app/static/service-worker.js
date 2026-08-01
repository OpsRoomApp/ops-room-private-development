// OPS ROOM 0.25.51: no application-shell caching for the local EFB console.
// Previous builds registered an offline shell with stale JS/CSS versions, which
// could mix old frontend code with a newer backend and break modules until a
// hard refresh. This worker clears old caches and then stays transparent.
self.addEventListener('install', event => {
  self.skipWaiting();
});
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.map(key => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});
self.addEventListener('fetch', event => {
  event.respondWith(fetch(event.request));
});
