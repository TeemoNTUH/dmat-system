// Service Worker:離線資產快取(架構書 Q2)。
// 影像離線佇列由 capture.js 之 IndexedDB 實作;此處負責頁面殼與靜態資產快取,
// 首次使用須於連上區網時開啟過系統完成快取(裝置整備 SOP)。
const CACHE = 'dmat-static-v1';
const ASSETS = [
    '/lib/bootstrap/dist/css/bootstrap.min.css',
    '/lib/bootstrap/dist/js/bootstrap.bundle.min.js',
    '/lib/jquery/dist/jquery.min.js',
    '/lib/signalr/signalr.min.js',
    '/css/site.css',
    '/js/capture.js',
    '/js/dashboard.js',
];

self.addEventListener('install', (e) => {
    e.waitUntil(caches.open(CACHE).then(c => c.addAll(ASSETS)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
    e.waitUntil(
        caches.keys().then(keys =>
            Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
        ).then(() => self.clients.claim())
    );
});

// 靜態資產:快取優先;頁面與 API:網路優先(資料真實來源是資料庫)
self.addEventListener('fetch', (e) => {
    const url = new URL(e.request.url);
    if (e.request.method !== 'GET') return;
    if (ASSETS.some(a => url.pathname === a)) {
        e.respondWith(caches.match(e.request).then(hit => hit || fetch(e.request)));
    }
});
