/**
 * Service Worker for Lekkersappie Standalone Mobile PWA (/lekkersappie/)
 * Enables app installation (beforeinstallprompt) and caches only the static application shell.
 * Authenticated API responses are never persisted to Cache Storage.
 */

const CACHE_NAME = "lekkersappie-pwa-v0.3.7";
const APP_SHELL = [
  "/lekkersappie/index.html",
  "/lekkersappie/styles.css",
  "/lekkersappie/app.js",
  "/lekkersappie/manifest.webmanifest",
  "/lekkersappie/icon-192.png",
  "/lekkersappie/icon-512.png",
  "/lekkersappie/icon-maskable-512.png",
  "/lekkersappie/apple-touch-icon.png",
  "/lekkersappie/icon.svg",
];

self.addEventListener("install", (event) => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL)).catch(() => {})
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((k) => k.startsWith("lekkersappie-pwa-") && k !== CACHE_NAME)
            .map((k) => caches.delete(k))
        )
      )
      .then(() => self.clients.claim())
  );
});

self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "CLEAR_AUTH_CACHE") {
    event.waitUntil(
      caches.open(CACHE_NAME).then((cache) =>
        cache.keys().then((requests) =>
          Promise.all(
            requests
              .filter((r) => new URL(r.url).pathname.startsWith("/api/"))
              .map((r) => cache.delete(r))
          )
        )
      )
    );
  }
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;

  const url = new URL(req.url);
  // Authenticated API calls always bypass Cache Storage for data security
  if (url.pathname.startsWith("/api/")) {
    return;
  }

  // Static app shell assets: network first with fast cache fallback
  if (url.pathname.startsWith("/lekkersappie")) {
    event.respondWith(
      fetch(req)
        .then((res) => {
          if (res.ok) {
            const clone = res.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(req, clone));
          }
          return res;
        })
        .catch(() => caches.match(req).then((hit) => hit || caches.match("/lekkersappie/index.html")))
    );
  }
});
