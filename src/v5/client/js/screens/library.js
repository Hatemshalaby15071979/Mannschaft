/* Screen 8, Library. Filter chips + rows, client-side, no fetch per tap. */

import { api } from '../api.js';
import { el, link, statusBlock } from '../ui.js';

const LEVELS = ['A1', 'A2', 'B1', 'B2', 'C1', 'C2'];

export async function render() {
  let all;
  try {
    ({ lessons: all } = await api.lessons());
  } catch (error) {
    return statusBlock('Keine Bibliothek', error.message);
  }

  const levels = [...new Set(all.map((lesson) => lesson.level))].sort();
  const state = { level: null, tag: null };

  const root = el('div', {});
  root.append(
    el('h1', {}, 'Bibliothek'),
    el('p', { class: 'muted' }, all.length === 1 ? 'eine Lektion' : `${all.length} Lektionen`),
  );

  const chips = el('div', { class: 'chips', role: 'group', 'aria-label': 'Filter' },
    chip('Alle', () => {
      state.level = null;
      state.tag = null;
      paint();
    }),
  );
  for (const level of levels) {
    chips.append(
      chip(level, () => {
        state.level = state.level === level ? null : level;
        state.tag = null;
        paint();
      }),
    );
  }
  root.append(chips);

  const tagChips = el('div', { class: 'chips chips--tag', role: 'group', 'aria-label': 'Thema' });
  const tags = [...new Set(all.flatMap((lesson) => lesson.tags))].sort();
  for (const tag of tags.slice(0, 12)) {
    tagChips.append(
      chip(tag, () => {
        state.tag = state.tag === tag ? null : tag;
        paint();
      }),
    );
  }
  root.append(tagChips);

  const list = el('ol', { class: 'row-list', id: 'library-list' });
  root.append(list);

  function paint() {
    const rows = all.filter(
      (lesson) =>
        (!state.level || lesson.level === state.level) &&
        (!state.tag || lesson.tags.includes(state.tag)),
    );
    list.replaceChildren(
      ...rows.map(
        (lesson) =>
          el(
            'li',
            {},
            el(
              'a',
              { class: 'row', href: `#/lesson/${lesson.id}` },
              el('span', { class: 'grow' },
                el('span', { class: 'title' }, lesson.title.de),
                el('span', { class: 'sub' }, `${lesson.level}, ${lesson.title.en}`),
              ),
              lesson.rendered
                ? el('span', { class: 'badge ok' }, 'Audio')
                : el('span', { class: 'badge' }, 'Text'),
            ),
          ),
      ),
      ...(!rows.length ? [el('li', { class: 'loading' }, 'Keine Treffer.')] : []),
    );
    chips.querySelectorAll('.chip').forEach((node) => {
      const label = node.textContent;
      node.setAttribute('aria-pressed', label === 'Alle' ? !state.level : state.level === label);
    });
    tagChips.querySelectorAll('.chip').forEach((node) => {
      node.setAttribute('aria-pressed', state.tag === node.textContent);
    });
  }
  paint();

  function chip(label, onClick) {
    return el('button', { class: 'chip', type: 'button', 'aria-pressed': 'false', onClick }, label);
  }

  return { node: root };
}
