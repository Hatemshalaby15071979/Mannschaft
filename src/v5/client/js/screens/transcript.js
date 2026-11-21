/* Screen 4 — Transcript. Shares the persistent player; sync is driven by the
   measured timeline.json start_ms, never by estimation. Words are tappable and
   open the dictionary; the small arrow jumps the audio to that line. */

import { api } from '../api.js';
import { player } from '../player.js';
import { getDetail, prefs } from '../store.js';
import { el, fmtClock, setPill, statusBlock } from '../ui.js';

export async function render([id]) {
  let detail;
  try {
    detail = await getDetail(id);
  } catch (error) {
    return statusBlock('Kein Transkript', error.message);
  }

  setPill(detail.lesson.level);

  const timeline = Array.isArray(detail.timeline) ? detail.timeline : [];
  const segments = new Map((detail.lesson.segments || []).map((segment) => [segment.id, segment]));
  const byEntry = new Map(timeline.map((entry) => [entry.id, entry]));

  if (player.detail && player.detail.lesson.id === id) {
    /* already loaded — the shared player keeps playing */
  } else {
    player.load(detail, {});
  }

  const root = el('section', {},
    el('h1', {}, detail.lesson.title.de),
    timeline.length
      ? el('p', { class: 'muted' }, `${timeline.length} Zeilen · synchron aus timeline.json`)
      : el('p', { class: 'muted' }, 'Noch keine Timeline — Textansicht, ohne Synchronisation.'),
    el('p', { class: 'mono-label' }, 'Wort antippen → Wörterbuch · Pfeil → an diese Stelle springen'),
  );

  const list = el('ol', { class: 'transcript' });
  const entries = timeline.length ? timeline : (detail.lesson.segments || []).map((segment) => ({
    id: segment.id,
    start_ms: 0,
    end_ms: 0,
    speaker: segment.speaker,
    voice: segment.speaker,
    type: segment.type,
    text: segment.text,
  }));

  for (const entry of entries) {
    const segment = segments.get(entry.id);
    const measured = Boolean(byEntry.has(entry.id));
    list.append(
      el(
        'li',
        { class: entry.type === 'check' ? 'check' : '' },
        el(
          'div',
          { class: 'line-block', 'data-seg': entry.id, 'aria-current': 'false' },
          el('p', { class: 'de' }, ...wordButtons(entry.text)),
          prefs.translations && segment && segment.translation
            ? el('p', { class: 'en' }, segment.translation)
            : null,
          el('span', { class: 'meta' },
            [entry.speaker, entry.type && entry.type !== 'line' ? entry.type : null]
              .filter(Boolean)
              .join(' · ')),
          el(
            'button',
            {
              class: 'seek',
              type: 'button',
              'data-seg': entry.id,
              ...(measured ? {} : { disabled: true }),
              title: measured ? 'Zum Zeitpunkt springen' : 'Nicht synchronisiert',
            },
            measured ? `↦ ${fmtClock(entry.start_ms)}` : 'ohne Zeit',
          ),
        ),
      ),
    );
  }
  root.append(list);

  list.addEventListener('click', (event) => {
    const word = event.target.closest('button.word');
    if (word) {
      location.hash = `#/dict?q=${encodeURIComponent(word.dataset.word)}`;
      return;
    }
    const button = event.target.closest('button.seek');
    if (!button || button.disabled) return;
    const entry = byEntry.get(button.dataset.seg);
    if (!entry) return;
    player.seek(entry.start_ms + 50);
    player.play().catch(() => {});
    location.hash = `#/play/${id}`;
  });

  document.getElementById('screen').append(root);

  const paint = () => {
    const current = player.currentEntry;
    list.querySelectorAll('.line-block').forEach((node) => {
      const active = current && node.dataset.seg === current.id;
      node.setAttribute('aria-current', String(Boolean(active)));
      if (active) node.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    });
  };

  const unsubscribe = player.subscribe(paint);
  return {
    node: root,
    cleanup() {
      unsubscribe();
    },
  };
}

function wordButtons(text) {
  const nodes = [];
  for (const part of String(text).split(/(\s+)/)) {
    if (!part.trim()) {
      nodes.push(part);
      continue;
    }
    const clean = part.replace(/^[^\p{L}\p{N}]+|[^\p{L}\p{N}]+$/gu, '');
    if (!clean) {
      nodes.push(part);
      continue;
    }
    nodes.push(
      el('button', { class: 'word', type: 'button', 'data-word': clean }, part),
    );
  }
  return nodes;
}
