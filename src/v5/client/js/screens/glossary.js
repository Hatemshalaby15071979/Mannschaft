/* Screen 5, Glossary. With a lesson id: that lesson's words. Without: a
   search across everything that is loaded, which stays honest (only what
   exists today is shown). */

import { api } from '../api.js';
import { getDetail } from '../store.js';
import { el, link, setPill, statusBlock } from '../ui.js';

export async function render([id]) {
  let entries = [];
  let title = 'Glossar';
  let pill = '';

  if (id) {
    let detail;
    try {
      detail = await getDetail(id);
    } catch (error) {
      return statusBlock('Keine Lektion', error.message);
    }
    entries = detail.lesson.glossary || [];
    title = `${detail.lesson.title.de}, Glossar`;
    pill = detail.lesson.level;
  } else {
    const { lessons } = await api.lessons();
    const details = await Promise.allSettled(lessons.map((lesson) => getDetail(lesson.id)));
    for (const result of details) {
      if (result.status !== 'fulfilled') continue;
      for (const entry of result.value.lesson.glossary || []) {
        entries.push({ ...entry, lesson: result.value.lesson.id });
      }
    }
  }

  setPill(pill);

  const root = el('section', {}, el('h1', {}, title),
    el('p', { class: 'muted' }, `${entries.length} Eintrag${entries.length === 1 ? '' : 'e'}`));

  const search = el('input', {
    type: 'search',
    placeholder: 'Suchen …',
    'aria-label': 'Glossar durchsuchen',
  });
  root.append(search);

  const list = el('ul', { class: 'row-list' });
  root.append(list);

  function paint() {
    const needle = search.value.trim().toLowerCase();
    const rows = entries.filter(
      (entry) =>
        !needle ||
        entry.de.toLowerCase().includes(needle) ||
        entry.en.toLowerCase().includes(needle) ||
        (entry.example_de || '').toLowerCase().includes(needle),
    );
    list.replaceChildren(
      ...rows.map(
        (entry) =>
          el('li', { class: 'card' },
            el('div', {},
              el('span', { class: 'gloss-term' }, entry.de),
              ' ',
              el('span', { class: 'muted' }, entry.pos || ''),
              entry.plural ? el('span', { class: 'muted' }, `, ${entry.plural}`) : null,
              entry.lesson ? el('span', { class: 'badge' }, entry.lesson) : null,
            ),
            el('div', {}, entry.en),
            entry.example_de ? el('div', { class: 'gloss-example' }, entry.example_de) : null,
            entry.example_en ? el('div', { class: 'gloss-example muted' }, entry.example_en) : null,
            entry.note_de ? el('div', { class: 'gloss-note' }, entry.note_de) : null,
            entry.note_en ? el('div', { class: 'gloss-note muted' }, entry.note_en) : null,
            el('div', { class: 'chip-row', style: { marginTop: '0.5rem' } },
              link(`#/dict?q=${encodeURIComponent(entry.de)}`, 'Wörterbuch', 'chip'),
              el('a', {
                class: 'chip',
                href: `https://www.dwds.de/wb/${encodeURIComponent(entry.de)}`,
                target: '_blank',
                rel: 'noopener noreferrer',
              }, 'DWDS ↗'),
            ),
          ),
      ),
      ...(!rows.length ? [el('li', { class: 'loading' }, 'Nichts gefunden.')] : []),
    );
  }
  search.addEventListener('input', paint);
  paint();

  document.getElementById('screen').append(root);
  return { node: root };
}
