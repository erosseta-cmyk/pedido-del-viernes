// Necesario para que versiones antiguas de Chrome permitan instalar la app.
// No guarda nada en caché: siempre se piden los precios actualizados.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', e => e.respondWith(fetch(e.request)));
