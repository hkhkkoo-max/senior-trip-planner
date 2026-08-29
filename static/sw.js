const CACHE_NAME = 'senior-trip-v8';
const PRECACHE_ASSETS = [
  '/',
  '/static/css/style.css',
  '/static/js/app.js',
  '/static/manifest.json',
  '/static/icons/app-icon-192.png',
  '/static/icons/app-icon-512.png',
  '/static/images/travel_hero.png'
];

// 서비스 워커 설치 이벤트 (기본 정적 파일 프리캐싱)
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      console.log('[Service Worker] Pre-caching offline assets');
      return Promise.all(
        PRECACHE_ASSETS.map((url) => 
          cache.add(url).catch((err) => console.warn('[Service Worker] Skip caching:', url, err))
        )
      );
    }).then(() => self.skipWaiting())
  );
});

// 서비스 워커 활성화 이벤트 (구버전 캐시 정리)
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames.map((cache) => {
          if (cache !== CACHE_NAME) {
            console.log('[Service Worker] Clearing old cache:', cache);
            return caches.delete(cache);
          }
        })
      );
    }).then(() => self.clients.claim())
  );
});

// 네트워크 요청 가로채기 (Fetch 이벤트)
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // 1. API 호출 및 동적 데이터 요청은 항상 최신 네트워크 직접 통신 (캐싱 제외)
  if (url.pathname.startsWith('/api/') || event.request.method !== 'GET') {
    return;
  }

  // 2. 정적 자원 및 페이지: Network First, Fallback to Cache
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        // 유효한 응답인 경우 캐시 업데이트
        if (response && response.status === 200 && response.type === 'basic') {
          const responseToCache = response.clone();
          caches.open(CACHE_NAME).then((cache) => {
            cache.put(event.request, responseToCache);
          });
        }
        return response;
      })
      .catch(async () => {
        // 오프라인 상태일 때 캐시된 응답 반환
        const cachedResponse = await caches.match(event.request);
        if (cachedResponse) {
          return cachedResponse;
        }
        // HTML 페이지 요청인데 캐시가 없는 경우 루트 페이지 반환
        if (event.request.headers.get('accept')?.includes('text/html')) {
          return caches.match('/');
        }
      })
  );
});
