/* Offline shell + byte-range slicing from the cached audio buffer.
   Strategy:
   - SHELL: precached on install, served cache-first.
   - /api/audio/*: pass ranged requests to the server (its ETag/206 are
     authoritative); warm the FULL body under the range-less URL and slice it
     only when offline (206 / 416 with correct headers).
   - /api/lessons/*: network-first with cache fallback (lesson content can be
     re-authored; audio is immutable once rendered). */

const VERSION = 'v10';
const SHELL = `mannschaft-${VERSION}`;
const DATA = `mannschaft-data-${VERSION}`;

/* Cross-origin media must never be intercepted: a YouTube iframe is not ours
   to cache, and a stale cached player is a broken player. */
const VIDEO_ORIGINS = /(^|\.)(youtube\.com|youtube-nocookie\.com|ytimg\.com|googlevideo\.com)$/;

const SHELL_URLS = [
  '/',
  '/index.html',
  '/manifest.webmanifest',
  '/assets/logo-mark.png',
  '/assets/fonts/bodoni.woff2',
  '/assets/fonts/geist400.woff2',
  '/assets/fonts/geist500.woff2',
  '/assets/fonts/geistmono400.woff2',
  '/assets/fonts/geistmono500.woff2',
  '/css/tokens.css',
  '/css/base.css',
  '/css/app.css',
  '/css/v6-shell.css',
  '/css/v6.css',
  '/css/specimen.css',
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
      const stale = names.filter((name) => name !== SHELL && name !== DATA);
      await Promise.all(stale.map((name) => caches.delete(name)));
      await self.clients.claim();
      /* On an upgrade, reload open windows so the visible DOM is the new
         shell even when the old page predates the controllerchange listener. */
      if (stale.length) {
        const windows = await self.clients.matchAll({ type: 'window' });
        await Promise.all(
          windows.map((client) => client.navigate(client.url).catch(() => {})),
        );
      }
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
    /* Keep a full body for offline use without delaying playback: the ranged
       response goes straight back, the full copy is warmed in the background. */
    event.waitUntil(warmAudio(event.request));
    return;
  }

  /* A live probe is never cached: a stale "up" is worse than no answer. */
  if (url.pathname === '/api/health') {
    event.respondWith(fetch(event.request).catch(() => new Response(null, { status: 503 })));
    return;
  }

  /* Every other API call is fresh-first. They used to fall through to the
     shell cache, which froze progress and lesson JSON on the first answer. */
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(networkFirst(event.request));
    return;
  }

  /* A navigation must never be answered from a stale shell: a cache-first
     index is how a rebrand ships and nobody sees it. Online wins; offline
     falls back to the precached shell. */
  if (event.request.mode === 'navigate') {
    event.respondWith(navigationFirst(event.request));
    return;
  }

  /* The cache answers first, the network replaces it. waitUntil is called
     here, synchronously, never from inside the async helper: extending a
     fetch event's life after dispatch has ended throws. */
  event.respondWith(shellFirst(event.request));
  event.waitUntil(refresh(event.request));
});

async function refresh(fetchRequest) {
  try {
    const cache = await caches.open(SHELL);
    const response = await fetch(fetchRequest);
    if (response && response.ok) await cache.put(fetchRequest, response.clone());
  } catch {
    /* offline: the cached copy already answered */
  }
}

/* Online: pass the browser's ranged request straight to the server, which
   implements byte ranges correctly (206 + ETag + Content-Range). Synthesising
   our own 206 from a cached buffer produces a different ETag; when an early
   preload escaped this worker before it claimed control, FFmpeg then rejects
   the mixed stream and playback stalls after ~2 s. Only fall back to slicing
   the cached body when offline. */
async function audioFromCache(request) {
  const range = request.headers.get('range');
  try {
    const fresh = await fetch(request);
    if (fresh.ok) return fresh;
  } catch {
    /* offline: use the warmed full body below */
  }
  const cache = await caches.open(DATA);
  const key = new Request(request.url, { method: 'GET' });
  const cached = await cache.match(key, { ignoreVary: true });
  if (!cached) return new Response(null, { status: 503 });
  const buffer = await cached.arrayBuffer();
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

/* Download the full body once so playback keeps working offline. Keyed by the
   range-less URL; the ranged requests themselves are never cached (206 + Range
   vary would otherwise multiply entries). */
async function warmAudio(request) {
  try {
    const cache = await caches.open(DATA);
    const key = new Request(request.url, { method: 'GET' });
    if (await cache.match(key, { ignoreVary: true })) return;
    const full = await fetch(key);
    if (full.ok) await cache.put(key, full.clone());
  } catch {
    /* offline or aborted — the ranged response already went back */
  }
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

async function navigationFirst(request) {
  const cache = await caches.open(SHELL);
  try {
    const fresh = await fetch(request);
    if (fresh.ok) await cache.put('/index.html', fresh.clone());
    return fresh;
  } catch {
    const cached = await cache.match('/index.html');
    if (cached) return cached;
    return new Response(null, { status: 503 });
  }
}

/* Stale-while-revalidate. A cache-first shell with no revalidation is how a
   design ships and one file stays behind: the page then imports a module the
   cache never replaced, and sits on its loading line forever. Paint from the
   cache, and let the caller replace it in the background. */
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
