/* Kaza service worker — makes the app installable and offline-capable.
 *
 * Strategy:
 *   - API and auth requests (/api/, /healthz) are NEVER cached — always network.
 *   - Navigations (the app shell) are network-first, falling back to the cached
 *     page when offline, so an online user always gets the latest build.
 *   - Static same-origin assets (icons, manifest, logo) use stale-while-
 *     revalidate: instant from cache, refreshed in the background.
 *   - Cross-origin requests (Google Fonts) are left to the browser.
 * Bump CACHE to invalidate old caches on the next visit.
 */
const CACHE = "kaza-v1";
const SHELL = [
  "/",
  "/manifest.webmanifest",
  "/logo.svg",
  "/icon-192.png",
  "/icon-512.png",
  "/apple-touch-icon.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      .then((cache) => cache.addAll(SHELL))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return; // never touch writes
  const url = new URL(req.url);
  if (url.origin !== location.origin) return; // fonts etc. — let the browser handle
  if (url.pathname.startsWith("/api/") || url.pathname === "/healthz") return; // never cache data/auth

  // App shell: network-first so updates land immediately; cache is the offline net.
  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE).then((cache) => cache.put("/", copy));
          return res;
        })
        .catch(() => caches.match("/"))
    );
    return;
  }

  // Static assets: stale-while-revalidate.
  event.respondWith(
    caches.match(req).then((cached) => {
      const fromNetwork = fetch(req)
        .then((res) => {
          if (res.ok) {
            const copy = res.clone();
            caches.open(CACHE).then((cache) => cache.put(req, copy));
          }
          return res;
        })
        .catch(() => cached);
      return cached || fromNetwork;
    })
  );
});
