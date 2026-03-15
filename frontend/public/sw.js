// Service Worker for Gilbert's Yoga Helper
// Provides offline caching for pages and API data

const CACHE_VERSION = 'v3';
const CACHE_NAME = `yoga-helper-${CACHE_VERSION}`;

// Pages to pre-cache on install
const PRECACHE_URLS = [
  '/',
  '/admin/search-terms',
  '/admin/exclude-terms',
  '/admin/sources',
  '/admin/crawl',
  '/static/favicon.svg',
  '/static/icons/icon-192.svg',
  '/static/icons/icon-512.svg'
];

// External CDN resources to cache
const CDN_URLS = [
  'https://cdn.tailwindcss.com',
  'https://cdnjs.cloudflare.com/ajax/libs/flowbite/2.2.1/flowbite.min.css',
  'https://cdnjs.cloudflare.com/ajax/libs/flowbite/2.2.1/flowbite.min.js',
  'https://unpkg.com/htmx.org@1.9.10'
];

// Install event - pre-cache essential pages and CDN resources
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(async (cache) => {
      console.log('[SW] Pre-caching pages');
      // Cache local pages
      await cache.addAll(PRECACHE_URLS);
      // Cache CDN resources (with no-cors for cross-origin)
      console.log('[SW] Pre-caching CDN resources');
      for (const url of CDN_URLS) {
        try {
          const response = await fetch(url, { mode: 'cors' });
          if (response.ok) {
            await cache.put(url, response);
          }
        } catch (e) {
          console.log('[SW] Failed to cache CDN:', url);
        }
      }
    })
  );
  // Activate immediately
  self.skipWaiting();
});

// Activate event - clean up old caches
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames
          .filter((name) => name.startsWith('yoga-helper-') && name !== CACHE_NAME)
          .map((name) => {
            console.log('[SW] Deleting old cache:', name);
            return caches.delete(name);
          })
      );
    })
  );
  // Take control of all pages immediately
  self.clients.claim();
});

// Check if URL is a CDN resource
function isCdnUrl(url) {
  return CDN_URLS.some(cdn => url.startsWith(cdn.split('?')[0]));
}

// Fetch event - serve from cache, update in background (stale-while-revalidate)
self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // Skip non-GET requests
  if (request.method !== 'GET') {
    return;
  }

  // Handle CDN resources
  if (isCdnUrl(request.url)) {
    event.respondWith(
      caches.open(CACHE_NAME).then((cache) => {
        return cache.match(request).then((cachedResponse) => {
          if (cachedResponse) {
            return cachedResponse;
          }
          return fetch(request).then((response) => {
            if (response.ok) {
              cache.put(request, response.clone());
            }
            return response;
          });
        });
      })
    );
    return;
  }

  // Only handle same-origin requests for non-CDN
  if (url.origin !== location.origin) {
    return;
  }

  // Skip HTMX polling requests (they need fresh data when online)
  if (url.pathname === '/admin/crawl/status' && url.search.includes('polling')) {
    return;
  }

  // For HTML pages and API requests: stale-while-revalidate
  event.respondWith(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.match(request).then((cachedResponse) => {
        // Start network fetch in background
        const fetchPromise = fetch(request)
          .then((networkResponse) => {
            // Only cache successful responses
            if (networkResponse.ok) {
              cache.put(request, networkResponse.clone());
            }
            return networkResponse;
          })
          .catch((error) => {
            console.log('[SW] Network failed, serving cached:', request.url);
            // Network failed, return cached or error
            if (cachedResponse) {
              return cachedResponse;
            }
            throw error;
          });

        // Return cached response immediately if available, otherwise wait for network
        return cachedResponse || fetchPromise;
      });
    })
  );
});

// Handle messages from the page
self.addEventListener('message', (event) => {
  if (event.data === 'skipWaiting') {
    self.skipWaiting();
  }
});
