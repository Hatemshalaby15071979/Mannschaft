/* Screen 4 — Transcript. Shares the persistent player; sync is driven by the
   measured timeline.json start_ms, never by estimation. */

import { api, ApiError } from '../api.js';
import { player } from '../player.js';
import { getDetail, prefs } from '../store.js';
import { el, setPill, statusBlock } from '../ui.js';

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
          'button',
          {
            class: 'line',
            type: 'button',
            'data-seg': entry.id,
            'aria-current': 'false',
            ...(measured ? {} : { disabled: true }),
            title: measured ? 'Zum Zeitpunkt springen' : 'Nicht synchronisiert',
          },
          el('span', { class: 'de' }, entry.text),
          prefs.translations && segment && segment.translation
            ? el('span', { class: 'en' }, segment.translation)
            : null,
          el('span', { class: 'meta' },
            [entry.speaker, entry.type && entry.type !== 'line' ? entry.type : null]
              .filter(Boolean)
              .join(' · ')),
        ),
      ),
    );
  }
  root.append(list);

  list.addEventListener('click', (event) => {
    const button = event.target.closest('button.line');
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
    list.querySelectorAll('button.line').forEach((node) => {
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
