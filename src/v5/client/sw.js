/* Offline shell + byte-range slicing from the cached audio buffer.
   Strategy:
   - SHELL: precached on install, served cache-first.
   - /api/audio/*: cache the FULL body under the range-less URL; answer any
     Range request by slicing that buffer (206 / 416 with correct headers).
   - /api/lessons/*: network-first with cache fallback (lesson content can be
     re-authored; audio is immutable once rendered). */

const VERSION = 'v3';
const SHELL = `v5-${VERSION}`;
const DATA = `v5-data-${VERSION}`;

/* Cross-origin media must never be intercepted: a YouTube iframe is not ours
   to cache, and a stale cached player is a broken player. */
const VIDEO_ORIGINS = /(^|\.)(youtube\.com|youtube-nocookie\.com|ytimg\.com|googlevideo\.com)$/;

const SHELL_URLS = [
  '/',
  '/index.html',
  '/manifest.webmanifest',
  '/assets/logo-mark.png',
  '/css/app.css',
  '/css/v6-shell.css',
  '/css/v6.css',
  '/sw.js',
  '/js/main.js',
  '/js/shell.js',
  '/js/ui.js',
  '/js/api.js',
  '/js/store.js',
  '/js/player.js',
  '/js/screens/home.js',
  '/js/screens/library.js',
  '/js/screens/lesson.js',
  '/js/screens/play.js',
  '/js/screens/transcript.js',
  '/js/screens/glossary.js',
  '/js/screens/drill.js',
  '/js/screens/progress.js',
  '/js/screens/clip.js',
  '/js/screens/cards.js',
  '/js/screens/dictionary.js',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    (async () => {
      const cache = await caches.open(SHELL);
      await cache.addAll(SHELL_URLS);
      await self.skipWaiting();
    })(),
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      const names = await caches.keys();
      await Promise.all(
        names
          .filter((name) => name !== SHELL && name !== DATA)
          .map((name) => caches.delete(name)),
      );
      await self.clients.claim();
    })(),
  );
});

function rangeStatus() {
  const cache = caches.open(DATA);
  return cache;
}

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);
  if (VIDEO_ORIGINS.test(url.hostname)) return; // browser handles embeds directly
  if (event.request.method !== 'GET' || url.origin !== self.location.origin) return;

  if (url.pathname.startsWith('/api/audio/')) {
    event.respondWith(audioFromCache(event.request));
    return;
  }

  if (url.pathname.startsWith('/api/lessons/')) {
    event.respondWith(networkFirst(event.request));
    return;
  }

  event.respondWith(shellFirst(event.request));
});

async function audioFromCache(request) {
  const cache = await caches.open(DATA);
  const key = new Request(request.url, { method: 'GET' });
  let cached = await cache.match(key, { ignoreVary: true });

  if (!cached) {
    const fresh = await fetch(key);
    if (!fresh.ok) return fresh;
    await cache.put(key, fresh.clone());
    cached = fresh;
  }

  const buffer = await cached.arrayBuffer();
  const range = request.headers.get('range');
  if (!range) {
    return new Response(buffer, {
      status: 200,
      headers: {
        'Content-Type': 'audio/mpeg',
        'Accept-Ranges': 'bytes',
        'Content-Length': String(buffer.byteLength),
      },
    });
  }
  return slice(buffer, range);
}

function slice(buffer, rangeHeader) {
  const match = /^bytes=(\d*)-(\d*)$/.exec(rangeHeader.trim());
  if (!match) return new Response(null, { status: 400 });
  const total = buffer.byteLength;
  let start = match[1] === '' ? 0 : Number(match[1]);
  let end = match[2] === '' ? total - 1 : Number(match[2]);

  if (match[1] === '' && match[2] !== '') {
    /* suffix form bytes=-N: last N bytes */
    const suffix = Number(match[2]);
    start = Math.max(0, total - suffix);
    end = total - 1;
  }

  if (start >= total) {
    return new Response(null, {
      status: 416,
      headers: { 'Content-Range': `bytes */${total}` },
    });
  }
  end = Math.min(end, total - 1);
  const body = buffer.slice(start, end + 1);
  return new Response(body, {
    status: 206,
    headers: {
      'Content-Type': 'audio/mpeg',
      'Accept-Ranges': 'bytes',
      'Content-Range': `bytes ${start}-${end}/${total}`,
      'Content-Length': String(body.byteLength),
    },
  });
}

async function networkFirst(request) {
  const cache = await caches.open(DATA);
  try {
    const fresh = await fetch(request);
    if (fresh.ok) await cache.put(request, fresh.clone());
    return fresh;
  } catch {
    const cached = await cache.match(request, { ignoreVary: true });
    if (cached) return cached;
    return new Response(JSON.stringify({ offline: true }), {
      status: 503,
      headers: { 'Content-Type': 'application/json' },
    });
  }
}

async function shellFirst(request) {
  const cache = await caches.open(SHELL);
  const cached = await cache.match(request, { ignoreVary: true });
  if (cached) return cached;
  const response = await fetch(request).catch(() => null);
  if (response && response.ok) {
    await cache.put(request, response.clone());
  }
  if (response) return response;
  if (request.mode === 'navigate') {
    const index = await cache.match('/index.html');
    if (index) return index;
  }
  return new Response(null, { status: 503 });
}
