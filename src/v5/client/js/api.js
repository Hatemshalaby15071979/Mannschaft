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

async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(path, options);
  } catch (cause) {
    throw new ApiError('Keine Verbindung zum lokalen Server.', 0, String(cause));
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
  audioUrl: (id) => `/api/audio/${encodeURIComponent(id)}`,
  lineUrl: (id, segmentId) =>
    `/api/audio/${encodeURIComponent(id)}/lines/${encodeURIComponent(segmentId)}`,
};
