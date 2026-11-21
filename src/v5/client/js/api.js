/* The only place that knows about endpoints. */

const JSON_HEADERS = { Accept: 'application/json' };

export class ApiError extends Error {
  constructor(message, status, detail) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

function detailMessage(detail) {
  if (!detail) return '';
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) return detail.map(detailMessage).filter(Boolean).slice(0, 3).join('; ');
  if (typeof detail.message === 'string') {
    const issues = Array.isArray(detail.issues) ? detail.issues.slice(0, 3).join('; ') : '';
    return issues ? `${detail.message}: ${issues}` : detail.message;
  }
  return '';
}

/* A fetch that never settles is worse than one that fails: the screen stays on
   its loading line and nothing says why. Eight seconds is generous on loopback. */
const TIMEOUT_MS = 8000;

async function request(path, options = {}) {
  let response;
  const init = { ...options };
  if (!init.signal && typeof AbortSignal !== 'undefined' && AbortSignal.timeout) {
    init.signal = AbortSignal.timeout(TIMEOUT_MS);
  }
  try {
    response = await fetch(path, init);
  } catch (cause) {
    const timedOut = cause && cause.name === 'TimeoutError';
    throw new ApiError(
      timedOut
        ? 'Der lokale Server antwortet nicht (8 s ohne Antwort).'
        : 'Keine Verbindung zum lokalen Server.',
      0,
      String(cause),
    );
  }
  const type = response.headers.get('content-type') || '';
  const payload = type.includes('json') ? await response.json().catch(() => null) : null;
  if (!response.ok) {
    const detail = payload && 'detail' in payload ? payload.detail : payload;
    throw new ApiError(
      detailMessage(detail) || `HTTP ${response.status}`,
      response.status,
      detail,
    );
  }
  return payload;
}

function qs(params) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params || {})) {
    if (value !== null && value !== undefined && value !== '') search.set(key, value);
  }
  const text = search.toString();
  return text ? `?${text}` : '';
}

export const api = {
  health: () => request('/api/health'),
  lessons: (params) => request(`/api/lessons${qs(params)}`, { headers: JSON_HEADERS }),
  lesson: (id) => request(`/api/lessons/${encodeURIComponent(id)}`, { headers: JSON_HEADERS }),
  progress: (params) => request(`/api/progress${qs(params)}`, { headers: JSON_HEADERS }),
  saveProgress: (body) =>
    request('/api/progress', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...JSON_HEADERS },
      body: JSON.stringify(body),
    }),
  render: (id) => request(`/api/render/${encodeURIComponent(id)}`, { method: 'POST' }),
  job: (id) => request(`/api/render/${encodeURIComponent(id)}`, { headers: JSON_HEADERS }),
  corpusSuggest: (params) => request(`/api/corpus/suggest${qs(params)}`),
  media: (id) => request(`/api/media/${encodeURIComponent(id)}`, { headers: JSON_HEADERS }),
  cards: (id) => request(`/api/cards/${encodeURIComponent(id)}`, { headers: JSON_HEADERS }),
  dict: (q) => request(`/api/dict${qs({ q })}`, { headers: JSON_HEADERS }),
  context: (id) =>
    request(`/api/lesson/${encodeURIComponent(id)}/context`, { headers: JSON_HEADERS }),
  event: (body) =>
    request('/api/progress', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...JSON_HEADERS },
      body: JSON.stringify(body),
    }),
  audioUrl: (id) => `/api/audio/${encodeURIComponent(id)}`,
  lineUrl: (id, segmentId) =>
    `/api/audio/${encodeURIComponent(id)}/lines/${encodeURIComponent(segmentId)}`,
};
