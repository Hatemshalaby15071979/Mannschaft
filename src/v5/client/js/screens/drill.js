/* Screen 6 — Drill. Two lanes: vocabulary reveal/self-grade, and — for
   lessons with echo/drill segments — listen-and-repeat the actual clip. */

import { api } from '../api.js';
import { getDetail } from '../store.js';
import { el, setPill, statusBlock, toast } from '../ui.js';

const KEY = (id) => `v5.drill.${id}`;

export async function render([id]) {
  let detail;
  try {
    detail = await getDetail(id);
  } catch (error) {
    return statusBlock('Keine Lektion', error.message);
  }

  setPill(detail.lesson.level);
  const entries = shuffle([...(detail.lesson.glossary || [])]);
  const repeatSegments = (detail.lesson.segments || []).filter(
    (segment) => segment.type === 'echo' || segment.type === 'drill',
  );

  const stats = loadStats(id, entries.length);
  let index = 0;
  let revealed = false;

  const root = el('section', {}, el('h1', {}, `${detail.lesson.title.de} — Übung`));

  /* ---- lane 1: vocabulary ------------------------------------------- */

  const counter = el('p', { class: 'muted' });
  const card = el('div', { class: 'card', 'aria-live': 'polite' });
  const buttons = el('div', { class: 'button-row' });
  root.append(counter, card, buttons);

  const audio = repeatSegments.length
    ? el('audio', {
        controls: true,
        style: { width: '100%', marginBottom: '10px' },
        src: api.lineUrl(id, repeatSegments[0].id),
      })
    : null;
  if (audio) root.append(audio);

  function loadStats(lessonId, length) {
    try {
      const raw = JSON.parse(localStorage.getItem(KEY(lessonId)) || 'null');
      if (raw && Array.isArray(raw.seen) && raw.seen.length === length) return raw;
    } catch {
      /* fall through */
    }
    return { seen: Array(length).fill(0), right: Array(length).fill(0), total: 0 };
  }

  function save() {
    localStorage.setItem(KEY(id), JSON.stringify(stats));
  }

  function paint() {
    counter.textContent =
      entries.length === 0
        ? 'Diese Lektion hat noch kein Glossar (M9 fügt es aus).'
        : `Eintrag ${index + 1} von ${entries.length} · gewusst ${stats.right.filter(Boolean).length}`;
    card.replaceChildren();
    if (!entries.length) {
      card.append(el('p', {}, 'Kein Glossar.'));
      buttons.replaceChildren();
      return;
    }
    const entry = entries[index];
    card.append(
      el('div', { class: 'gloss-term' }, entry.de),
      revealed
        ? el('div', {}, entry.en,
            entry.example_de ? el('div', { class: 'gloss-example' }, entry.example_de) : null)
        : el('div', { class: 'muted' }, '— Umschalten für die Bedeutung'),
    );
    buttons.replaceChildren(
      el('button', { type: 'button', 'data-act': 'flip' }, revealed ? 'Verbergen' : 'Umschalten'),
      ...revealed
        ? [
            el('button', { type: 'button', 'data-act': 'right', class: 'primary' }, 'Gewusst'),
            el('button', { type: 'button', 'data-act': 'again' }, 'Nochmal'),
          ]
        : [],
      ...(index < entries.length - 1 ? [el('button', { type: 'button', 'data-act': 'skip' }, 'Überspringen')] : []),
    );
  }

  buttons.addEventListener('click', (event) => {
    const action = event.target.closest('[data-act]');
    if (!action || !entries.length) return;
    const act = action.dataset.act;
    if (act === 'flip') {
      revealed = !revealed;
    } else if (act === 'right') {
      stats.right[index] = 1;
      stats.total += 1;
      stats.seen[index] += 1;
      save();
      advance();
      toast('Gut.');
    } else if (act === 'again') {
      stats.total += 1;
      stats.seen[index] += 1;
      save();
      toast('Steht weiter oben.');
    } else if (act === 'skip') {
      advance();
    } else {
      return;
    }
    if (act !== 'again') revealed = false;
    paint();
  });

  function advance() {
    if (index < entries.length - 1) {
      index += 1;
    } else {
      const pending = stats.right.findIndex((flag, i) => !flag);
      index = pending === -1 ? 0 : pending;
      toast('Runde geschafft — nächste Runde mit den offenen Wörtern.');
    }
  }

  paint();

  /* ---- lane 2: repeat the actual lines ------------------------------ */

  if (repeatSegments.length) {
    root.append(
      el('h2', {}, 'Nachsprechen'),
      el('p', { class: 'muted' },
        'Hör den Satz, sprich ihn nach. Das Clip ist das eigentliche Material — nicht ein neu synthetisiertes.'),
      el('ol', { class: 'row-list' },
        ...repeatSegments.map(
          (segment, i) =>
            el('li', {},
              el('button', {
                type: 'button',
                class: 'button quiet',
                'data-i': String(i),
                'aria-label': `Satz ${i + 1} abspielen`,
              }, '▶ Clip'),
              ' ',
              segment.text,
              segment.translation ? el('div', { class: 'muted' }, segment.translation) : null),
        ),
      ),
    );
    root.querySelector('ol.row-list').addEventListener('click', (event) => {
      const button = event.target.closest('[data-i]');
      if (!button) return;
      audio.src = api.lineUrl(id, repeatSegments[Number(button.dataset.i)].id);
      audio.play().catch(() => toast('Clip noch nicht gerendert?'));
    });
  }

  document.getElementById('screen').append(root);
  return { node: root };
}

function shuffle(items) {
  const out = [...items];
  for (let i = out.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}
