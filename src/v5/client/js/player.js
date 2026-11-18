/* One <audio> element for the whole app. Navigating between #/play and
   #/transcript never stops playback — the player outlives its screens. */

import { api } from './api.js';
import { prefs } from './store.js';

const SAVE_INTERVAL_MS = 4000;

function indexAt(timeline, ms) {
  let lo = 0;
  let hi = timeline.length - 1;
  let found = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (timeline[mid].start_ms <= ms) {
      found = mid;
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }
  return found;
}

class Player {
  constructor() {
    this.audio = new Audio();
    this.audio.preload = 'metadata';
    this.detail = null;
    this.timeline = [];
    this.listeners = new Set();
    this._restoreTo = null;
    this._lastSaved = 0;
    this._error = null;

    this.audio.addEventListener('timeupdate', () => {
      this._maybeSave();
      this.emit('time');
    });
    this.audio.addEventListener('play', () => this.emit('state'));
    this.audio.addEventListener('pause', () => {
      this._save(true);
      this.emit('state');
    });
    this.audio.addEventListener('ended', () => {
      this._save(true, true);
      this.emit('state');
    });
    this.audio.addEventListener('loadedmetadata', () => {
      if (this._restoreTo !== null) {
        this.seek(this._restoreTo);
        this._restoreTo = null;
      }
      this.emit('loaded');
    });
    this.audio.addEventListener('error', () => {
      this._error = 'audio';
      this.emit('error');
    });
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) this._save(true);
    });
    window.addEventListener('pagehide', () => this._save(true));
    window.addEventListener('beforeunload', () => this._save(true));
  }

  /* ---- lifecycle ---------------------------------------------------- */

  load(detail, { positionMs = null, autoplay = false } = {}) {
    const same = this.detail && this.detail.lesson.id === detail.lesson.id;
    // Keep the detail: progress saving (_maybeSave/_save) needs lesson id,
    // segments and currentEntry. Without it every save returns early.
    this.detail = detail;
    this.timeline = Array.isArray(detail.timeline) ? detail.timeline : [];
    this._error = null;
    if (!same) {
      this.audio.src = api.audioUrl(detail.lesson.id);
      this.audio.playbackRate = prefs.rate;
      this._restoreTo = positionMs;
      this.audio.load();
    } else if (positionMs !== null) {
      this.seek(positionMs);
    }
    this.emit('load');
    if (autoplay) {
      this.audio.play().catch(() => {
        /* autoplay blocked — the big play button is one tap away */
      });
    }
    return this;
  }

  subscribe(listener) {
    this.listeners.add(listener);
    listener(this, 'subscribe');
    return () => this.listeners.delete(listener);
  }

  emit(reason) {
    for (const listener of [...this.listeners]) {
      try {
        listener(this, reason);
      } catch (error) {
        console.error('player listener', error);
      }
    }
  }

  /* ---- accessors ------------------------------------------------------ */

  get positionMs() {
    return this.audio.currentTime * 1000;
  }

  get durationMs() {
    if (Number.isFinite(this.audio.duration) && this.audio.duration > 0) {
      return this.audio.duration * 1000;
    }
    return this.timeline.length ? this.timeline[this.timeline.length - 1].end_ms : 0;
  }

  get currentIndex() {
    return indexAt(this.timeline, this.positionMs);
  }

  get currentEntry() {
    const index = this.currentIndex;
    return index >= 0 ? this.timeline[index] : null;
  }

  get isPlaying() {
    return !this.audio.paused;
  }

  get error() {
    return this._error;
  }

  /* ---- transport ------------------------------------------------------ */

  play() {
    return this.audio.play();
  }

  pause() {
    this.audio.pause();
  }

  toggle() {
    if (this.audio.paused) return this.play();
    this.pause();
    return Promise.resolve();
  }

  seek(ms) {
    const max = this.durationMs;
    const target = Math.max(0, Math.min(ms, max > 0 ? max - 100 : ms));
    try {
      this.audio.currentTime = target / 1000;
    } catch {
      /* metadata not loaded yet — remember it for loadedmetadata */
      this._restoreTo = target;
    }
    this.emit('seek');
  }

  next() {
    const index = this.currentIndex + 1;
    if (index < this.timeline.length) this.seek(this.timeline[index].start_ms);
    else this.pause();
  }

  prev() {
    const entry = this.currentEntry;
    if (entry && this.positionMs - entry.start_ms > 1500) {
      this.seek(entry.start_ms);
      return;
    }
    if (this.currentIndex > 0) this.seek(this.timeline[this.currentIndex - 1].start_ms);
    else this.seek(0);
  }

  setRate(rate) {
    this.audio.playbackRate = rate;
  }

  /* ---- progress ------------------------------------------------------- */

  _maybeSave() {
    if (!this.detail || this.audio.paused) return;
    if (performance.now() - this._lastSaved < SAVE_INTERVAL_MS) return;
    this._save(false);
  }

  _save(force = false, completed = false) {
    if (!this.detail || (!force && this.audio.paused)) return;
    const entry = this.currentEntry;
    const fallback =
      (this.detail.lesson.segments && this.detail.lesson.segments[0] && this.detail.lesson.segments[0].id) ||
      's1';
    this._lastSaved = performance.now();
    const payload = {
      lesson_id: this.detail.lesson.id,
      seg_id: (entry && entry.id) || fallback,
      position_ms: Math.max(0, Math.round(this.positionMs)),
      completed,
    };
    if (force) {
      fetch('/api/progress', {
        method: 'POST',
        keepalive: true,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      }).catch(() => {});
      return;
    }
    api.saveProgress(payload).catch(() => {});
  }
}

export const player = new Player();
