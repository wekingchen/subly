const CACHE_PREFIX = 'subly-static-'
const CACHE_NAME = `${CACHE_PREFIX}v3`
const PRECACHE = [
  '/offline.html',
  '/offline.css',
  '/pwa-192.png',
  '/pwa-512.png',
  '/pwa-512-maskable.png'
]
const CACHED_BRAND_ASSETS = new Set(PRECACHE.slice(1))

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE))
  )
  self.skipWaiting()
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(
      keys
        .filter((key) => key.startsWith(CACHE_PREFIX) && key !== CACHE_NAME)
        .map((key) => caches.delete(key))
    ))
  )
  self.clients.claim()
})

self.addEventListener('fetch', (event) => {
  const request = event.request
  const url = new URL(request.url)
  if (
    request.method === 'GET'
    && url.origin === self.location.origin
    && CACHED_BRAND_ASSETS.has(url.pathname)
  ) {
    event.respondWith(
      caches.match(request).then((cached) => cached || fetch(request))
    )
    return
  }

  if (
    request.mode !== 'navigate'
    || url.origin !== self.location.origin
    || url.pathname.startsWith('/api/')
  ) {
    return
  }

  event.respondWith(
    fetch(request, { cache: 'no-store' })
      .catch(() => caches.match('/offline.html'))
  )
})
