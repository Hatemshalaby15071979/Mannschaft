/* Screen 7, Progress. The numbers come from the server's SQLite, not from
   local memory: this is the page that answers "where was I?" */

import { api } from '../api.js';
import { el, fmtClock, fmtMinutes, link, statusBlock } from '../ui.js';

export async function render() {
  let progress;
  let lessons;
  try {
    progress = await api.progress();
    ({ lessons } = await api.lessons());
  } catch (error) {
    return statusBlock('Kein Fortschritt', error.message);
  }

  const byId = new Map(lessons.map((lesson) => [lesson.id, lesson]));
  const rows = progress.lessons || [];
  const completed = rows.filter((row) => row.completed).length;
  const started = rows.filter((row) => !row.completed && row.position_ms > 5000).length;
  const heardMs = rows.reduce((sum, row) => sum + (row.position_ms || 0), 0);

  const root = el('section', {},
    el('h1', {}, 'Fortschritt'),
    el('p', { class: 'muted' },
      `${completed} abgeschlossen, ${started} in Arbeit, ${fmtMinutes(heardMs)} gehört`),
  );

  if (rows.length) {
    root.append(
      el('ol', { class: 'row-list' },
        ...rows.map(
          (row) => {
            const lesson = byId.get(row.lesson_id);
            const summary = lesson || {
              id: row.lesson_id,
              level: '?',
              title: { de: row.lesson_id, en: '' },
            };
            const total = (summary.duration_ms) || 0;
            return el('li', {},
              el('a', { class: 'row', href: `#/play/${row.lesson_id}` },
                el('span', { class: 'grow' },
                  el('span', { class: 'title' }, summary.title.de),
                  el('span', { class: 'sub' },
                    `${summary.level}, ${fmtClock(row.position_ms)}${total ? ` von ${fmtClock(total)}` : ''}`),
                ),
                row.completed
                  ? el('span', { class: 'badge ok' }, 'fertig')
                  : el('span', { class: 'badge' }, 'offen'),
              ),
            );
          },
        ),
      ),
    );
  } else {
    root.append(
      statusBlock(
        'Noch keine Fortschrittsdaten',
        'Sobald du eine Lektion angehört hast, erscheint sie hier, gespeichert im Server-SQLite, nicht im Browser.',
        [link('#/library', 'Zur Bibliothek', 'button')],
      ),
    );
  }

  document.getElementById('screen').append(root);
  return { node: root };
}
