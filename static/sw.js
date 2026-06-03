const CACHE = 'cpnb-v3';
const PRECACHE = ['/', '/manifest.json'];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(c => c.addAll(PRECACHE))
  );
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', e => {
  const url = e.request.url;

  // API, fotos y HTML principal: siempre red (nunca cache)
  if (url.includes('/api/') || url.endsWith('/') || url.includes('index.html')) {
    e.respondWith(fetch(e.request));
    return;
  }

  // Recursos estáticos (css, js, iconos): cache primero
  e.respondWith(
    caches.match(e.request).then(cached => cached || fetch(e.request))
  );
});
