/* Screen 11 — Wörterbuch. Local seed first (built from the 12 lessons' own
   glossaries, with source attribution), then clearly labelled outbound links.
   The app never scrapes or stores a dictionary page. */

import { api } from '../api.js';
import { el, link, statusBlock } from '../ui.js';

const SUGGESTIONS = ['ich bin', 'hallo', 'Termin', 'Bescheid', 'obwohl'];

export async function render(_params, query) {
  const initial = (query && query.get('q')) || '';
  let payload;
  try {
    payload = await api.dict(initial);
  } catch (error) {
    return statusBlock('Wörterbuch nicht erreichbar', error.message);
  }

  const root = el('section', { class: 'accent-woerter' });
  root.append(
    el('span', { class: 'mono-label' }, 'Wörterbuch · lokal zuerst'),
    el('h1', {}, 'Wort nachschlagen'),
    el('p', { class: 'lede' },
      payload.count
        ? `${payload.count} Einträge aus den eigenen Lektionen. Erst lokal, dann Links zu DWDS, Wiktionary, Cambridge und Collins.`
        : 'Der lokale Bestand ist noch nicht erzeugt. Die Links funktionieren trotzdem.'),
  );

  const input = el('input', {
    type: 'search',
    name: 'q',
    value: initial,
    placeholder: 'z. B. Bescheid, obwohl, ich bin …',
    'aria-label': 'Wort suchen',
    autocomplete: 'off',
  });
  const form = el('form', {
    class: 'dict-search',
    onSubmit: (event) => {
      event.preventDefault();
      const q = input.value.trim();
      location.hash = q ? `#/dict?q=${encodeURIComponent(q)}` : '#/dict';
    },
  },
    input,
    el('button', { type: 'submit', class: 'button' }, 'Suchen'),
  );
  root.append(form);

  if (!initial) {
    root.append(
      el('div', { class: 'chip-row' },
        ...SUGGESTIONS.map((word) =>
          link(`#/dict?q=${encodeURIComponent(word)}`, word, 'chip'))),
    );
  }

  const results = el('div', {});
  const local = payload.local || [];
  if (initial && !local.length) {
    results.append(
      el('p', { class: 'loading' },
        `„${initial}“ steht nicht im lokalen Bestand. Die Links unten sind der ehrliche nächste Schritt.`),
    );
  } else if (!initial) {
    results.append(el('h2', { class: 'section-heading' }, 'Bestand'),
      el('p', { class: 'muted' }, 'Erste Einträge — suche oben nach einem Wort.'));
  }

  for (const entry of local.slice(0, 30)) {
    results.append(entryCard(entry));
  }
  root.append(results);

  if (payload.links && payload.links.length) {
    root.append(
      el('h2', { class: 'section-heading' }, 'Extern nachschlagen'),
      el('div', { class: 'dict-links' },
        ...payload.links.map((item) =>
          el('a', { href: item.url, target: '_blank', rel: 'noopener noreferrer' },
            item.label,
            el('span', {}, item.note || '↗')))),
      el('p', { class: 'dict-source' },
        'Links öffnen die Seite des Anbieters. Es wird nichts heruntergeladen oder gespeichert.'),
    );
  }

  document.getElementById('screen').append(root);
  return { node: root };
}

function entryCard(entry) {
  return el('article', { class: 'dict-result', style: { marginBottom: '0.75rem' } },
    el('div', { style: { display: 'flex', gap: '0.5rem', alignItems: 'baseline', flexWrap: 'wrap' } },
      el('h2', {}, entry.de),
      entry.pos ? el('span', { class: 'dict-pos' }, entry.pos) : null,
      entry.plural ? el('span', { class: 'dict-pos' }, entry.plural) : null,
    ),
    el('p', { class: 'dict-en' }, entry.en),
    entry.example_de ? el('p', { class: 'dict-example' }, entry.example_de) : null,
    entry.example_en ? el('p', { class: 'dict-example' }, entry.example_en) : null,
    entry.note_de ? el('p', { class: 'muted' }, entry.note_de) : null,
    el('p', { class: 'dict-source' },
      `Quelle: ${entry.source || 'Lektionsglossar'} · ${(entry.sources || [entry.source_lesson]).join(', ')}`),
  );
}
