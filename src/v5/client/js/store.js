/* Prefs live in localStorage (they are per-device choices); lesson detail is
   cached in memory only, so a content edit is picked up on the next navigation. */

import { api } from './api.js';

const PREFS_KEY = 'v5.prefs';
const RATES = [0.7, 0.85, 1.0];

function readPrefs() {
  try {
    const raw = JSON.parse(localStorage.getItem(PREFS_KEY) || '{}');
    return {
      rate: RATES.includes(raw.rate) ? raw.rate : 1.0,
      translations: raw.translations !== false,
    };
  } catch {
    return { rate: 1.0, translations: true };
  }
}

export const prefs = readPrefs();
export { RATES };

export function savePrefs() {
  try {
    localStorage.setItem(PREFS_KEY, JSON.stringify(prefs));
  } catch {
    /* private mode — in-memory only */
  }
}

const detailCache = new Map();

export function getDetail(lessonId) {
  const cached = detailCache.get(lessonId);
  if (cached) return cached;
  const pending = api.lesson(lessonId).then(
    (detail) => {
      detailCache.set(lessonId, detail);
      return detail;
    },
    (error) => {
      detailCache.delete(lessonId);
      throw error;
    },
  );
  detailCache.set(lessonId, pending);
  return pending;
}

export function invalidateDetail(lessonId) {
  detailCache.delete(lessonId);
}

export function cycleRate() {
  const index = RATES.indexOf(prefs.rate);
  prefs.rate = RATES[(index + 1) % RATES.length];
  savePrefs();
  return prefs.rate;
}
