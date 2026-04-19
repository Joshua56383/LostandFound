const CACHE_NAME = 'recovery-hub-v1';
const ASSETS = [
    '/',
    '/static/css/main.css',
    '/static/manifest.json',
    'https://unpkg.com/lucide@latest',
    'https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js',
    'https://cdn.tailwindcss.com'
];

self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(CACHE_NAME).then(cache => {
            return cache.addAll(ASSETS);
        })
    );
});

self.addEventListener('fetch', event => {
    // Basic network-first policy for dynamic site
    event.respondWith(
        fetch(event.request).catch(() => {
            return caches.match(event.request);
        })
    );
});

// Implementation of push event handler
self.addEventListener('push', event => {
    const data = event.data ? event.data.json() : { title: 'New Update', body: 'Check your Recovery Hub alerts.' };
    
    event.waitUntil(
        self.registration.showNotification(data.title, {
            body: data.body,
            icon: 'https://img.icons8.com/isometric/192/package.png',
            badge: 'https://img.icons8.com/isometric/192/package.png',
            data: { url: data.url || '/' }
        })
    );
});

self.addEventListener('notificationclick', event => {
    event.notification.close();
    event.waitUntil(
        clients.openWindow(event.notification.data.url)
    );
});
