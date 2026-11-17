/* Screen 1 — Home. One primary action, never a wall of options. */

import { api, ApiError } from '../api.js';
import { el, fmtClock, fmtMinutes, link, statusBlock } from '../ui.js';

export async function render() {
  let progress = null;
  let lessons = [];
  try {
    [progress, { lessons: all }] = await Promise.all([api.progress(), api.lessons()]);
    lessons = all;
  } catch (error) {
    return statusBlock(
      'Kein lokaler Server',
      `Kein v5-Server erreichbar: ${error.message} · Starte mit <code>make serve</code> (Port 8766).`,
    );
  }

  const byId = new Map(lessons.map((lesson) => [lesson.id, lesson]));
  const resume = progress.resume;
  const resumed = resume ? byId.get(resume.lesson_id) : null;

  const next =
    resumed && !resumed.rendered
      ? null
      : lessons.find((lesson) => lesson.id !== (resume && resume.lesson_id)) || null;
  const target = resumed || next;

  const body = el('div', {});

  body.append(
    el('h1', {}, 'Guten Tag.'),
    el(
      'p',
      { class: 'muted' },
      'Hören zuerst. Eine Lektion, eine Hauptaktion, kein Wettbewerb.',
    ),
  );

  if (target) {
    const summary = target;
    const position =
      resume && resume.lesson_id === summary.id && !resume.completed ? resume.position_ms : 0;
    const card = el(
      'section',
      { class: 'card' },
      el('h2', {}, summary.title.de),
      el('p', { class: 'muted' }, summary.title.en),
      el(
        'p',
        {},
        summary.rendered
          ? position > 5000
            ? `${fmtClock(position)} von ${fmtMinutes(summary.duration_ms || summary.minutes * 60000)} — weiterhören`
            : `Beginn · ${fmtMinutes((summary.duration_ms || summary.minutes * 60000) / 1)}`
          : 'Noch nicht gerendert — Lektion ansehen',
      ),
      el(
        'div',
        { class: 'button-row' },
        summary.rendered
          ? link(`#/play/${summary.id}`, resume ? 'Weiterhören' : 'Hören')
          : link(`#/lesson/${summary.id}`, 'Lektion ansehen'),
        link(`#/library`, 'Bibliothek', 'button quiet'),
      ),
    );
    card.querySelector('button, a').classList.add('primary');
    body.append(card);
  } else if (!lessons.length) {
    body.append(
      statusBlock(
        'Noch keine Lektion',
        'Unter <code>v5/content/lessons/</code> liegt nichts. Starte mit <code>A2-01.lesson.json</code> (M9 ergänzt die restlichen 11 Piloten).',
      ),
    );
  }

  const healthSlot = el('p', { class: 'loading', id: 'home-health' }, 'Stimmen prüfen …');
  body.append(healthSlot, el('h2', {}, 'Bibliothek'), listSection(lessons, byId));
  document.getElementById('screen').append(body);
  refreshHealth(healthSlot);

  return { node: body };
}

function listSection(lessons) {
  const list = el('ol', { class: 'row-list' });
  for (const lesson of lessons.slice(0, 6)) {
    list.append(
      el(
        'li',
        {},
        el(
          'a',
          { class: 'row', href: `#/lesson/${lesson.id}`, 'data-lesson': lesson.id },
          el('span', { class: 'grow' },
            el('span', { class: 'title' }, lesson.title.de),
            el('span', { class: 'sub' }, `${lesson.level} · ${lesson.title.en}`),
          ),
          lesson.rendered ? el('span', { class: 'badge ok' }, 'Audio') : el('span', { class: 'badge' }, 'Text'),
        ),
      ),
    );
  }
  if (!lessons.length) return el('li', { class: 'loading' }, 'Leer.');
  return list;
}

function refreshHealth(slot) {
  api
    .health()
    .then((health) => {
      clearSlot(slot);
      if (!health.voices_ok) {
        slot.append(
          el('p', {},
            el('strong', {}, 'Stimmen fehlen noch '),
            `${health.missing_voices.length}/6 — VoiceStudio-Design (M4) ausstehend.`),
        );
      }
      if (!health.voicestudio.up) {
        slot.append(el('p', {}, `VoiceStudio läuft nicht (${health.voicestudio.error}). Bereits gerenderte Lektionen lassen sich abspielen.`));
      }
      if (health.voices_ok && health.voicestudio.up) {
        slot.append(el('p', { class: 'muted' }, 'Alles bereit.'));
      }
    })
    .catch((error) => {
      clearSlot(slot);
      slot.append(el('p', {}, `Health unklar: ${error.message}`));
    });
}

function clearSlot(node) {
  node.replaceChildren();
}
