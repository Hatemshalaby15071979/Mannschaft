/* Screen 1, Home. A specimen book's opening page: the masthead, four figures,
   one German line set as a specimen with its translation, then the twelve
   lessons as a ruled index.

   One primary action stays the rule: the line's own button. The index is the
   picker, so every row is a link, not a card. */

import { api } from '../api.js';
import { el, fmtClock, fmtMinutes, link, statusBlock, typo } from '../ui.js';

const LEVELS = ['A1', 'A2', 'B1', 'B2', 'C1', 'C2'];

export async function render() {
  let progress = { resume: null, lessons: [] };
  let lessons = [];
  let health = null;
  try {
    const [p, catalogue] = await Promise.all([api.progress(), api.lessons()]);
    progress = p;
    lessons = catalogue.lessons;
  } catch (error) {
    return statusBlock(
      'Kein lokaler Server',
      `Kein Mannschaft-Server erreichbar: ${error.message}. Starte mit <code>make serve</code> (Port 8766).`,
    );
  }
  health = await api.health().catch(() => null);

  const byId = new Map(lessons.map((lesson) => [lesson.id, lesson]));
  const resume = progress.resume;
  const resumed = resume ? byId.get(resume.lesson_id) : null;
  const next = lessons.find((lesson) => lesson.id !== (resume && resume.lesson_id)) || null;
  const target = resumed || next;
  const opening = await openingLine(target);

  const root = el('div', {});
  root.append(masthead(lessons), figures(lessons, progress, health));
  if (target) root.append(specimen(target, resume, opening));
  root.append(lessonSection(lessons));
  root.append(healthLine(health));

  document.getElementById('screen').append(root);
  return { node: root };
}

/* ------------------------------------------------------------------ pieces */

async function openingLine(lesson) {
  if (!lesson) return null;
  try {
    const detail = await api.lesson(lesson.id);
    const segments = (detail.lesson && detail.lesson.segments) || [];
    const line = segments.find((segment) => segment.type === 'line' && segment.text);
    if (!line) return null;
    return { de: line.text, en: typo(line.translation || '') };
  } catch {
    return null;
  }
}

function masthead(lessons) {
  const levels = [...new Set(lessons.map((lesson) => lesson.level))].sort();
  const span = levels.length ? `${levels[0]} bis ${levels[levels.length - 1]}` : 'A1 bis C2';
  return el(
    'header',
    { class: 'masthead' },
    el('h1', { class: 'headline' }, 'Hören zuerst.'),
    el(
      'p',
      { class: 'lede' },
      `Lektionen von ${span}, mit Audio, Video und Karten aus demselben Material.`,
    ),
    el(
      'div',
      { class: 'identity-meta' },
      el('span', {}, 'zwei pro Niveau'),
      el('span', {}, 'lokal, Port 8766'),
    ),
    el(
      'div',
      { class: 'notice-strip', role: 'note' },
      el(
        'p',
        {},
        el('strong', {}, 'Ehrlich: '),
        'Pilot-Lektionen, synthetischer Korpus, kein zertifizierter Kurs. Der Video-Korpus ist unausgewogen. Wo kein passender Clip existiert, sagt die App das und spielt dein gerendertes Audio.',
      ),
    ),
  );
}

function figures(lessons, progress, health) {
  const minutes = Math.round(
    lessons.reduce((sum, lesson) => sum + (lesson.duration_ms || 0), 0) / 60000,
  );
  const clips = health && health.corpus ? health.corpus.clips : null;
  const days = streak(progress.lessons);
  return el(
    'div',
    { class: 'figures' },
    cell(String(lessons.length), 'Lektionen'),
    cell(minutes ? String(minutes) : 'k. A.', 'Minuten Audio'),
    cell(clips === null ? 'k. A.' : String(clips), 'Videoquellen'),
    cell(`${days} ${days === 1 ? 'Tag' : 'Tage'}`, 'in Folge'),
  );
}

function cell(value, label) {
  return el(
    'div',
    { class: 'figure-cell' },
    el('span', { class: 'figure-value' }, value),
    el('span', { class: 'figure-label' }, label),
  );
}

function streak(rows) {
  if (!Array.isArray(rows) || !rows.length) return 0;
  const days = new Set(
    rows
      .map((row) => (row.updated_at || '').slice(0, 10))
      .filter(Boolean),
  );
  const cursor = new Date();
  let count = 0;
  for (let i = 0; i < 400; i += 1) {
    const key = cursor.toISOString().slice(0, 10);
    if (!days.has(key)) {
      if (i === 0) {
        cursor.setUTCDate(cursor.getUTCDate() - 1);
        continue;
      }
      break;
    }
    count += 1;
    cursor.setUTCDate(cursor.getUTCDate() - 1);
  }
  return count;
}

/* The signature: one German line at display size, its cap height, x-height and
   baseline ruled in the margin, the English under it. */

function specimen(target, resume, opening) {
  const duration = target.duration_ms || target.minutes * 60000;
  const position =
    resume && resume.lesson_id === target.id && !resume.completed ? resume.position_ms : 0;
  const de = opening && opening.de ? opening.de : target.title.de;
  const en = opening && opening.en ? opening.en : target.title.en;
  const action = target.rendered
    ? link(`#/play/${target.id}`, position > 5000 ? 'Weiterhören' : 'Hören', 'button primary')
    : link(`#/lesson/${target.id}`, 'Lektion ansehen', 'button primary');

  return el(
    'section',
    { class: 'specimen', 'aria-labelledby': 'today-head' },
    el(
      'div',
      { class: 'specimen-head' },
      el('h2', { id: 'today-head' }, 'Heute'),
      el(
        'span',
        { class: 'specimen-meta' },
        `${target.id}, ${position > 5000 ? `${fmtClock(position)} von ` : ''}${fmtMinutes(duration)}`,
      ),
    ),
    el(
      'div',
      { class: 'specimen-line' },
      el(
        'div',
        { class: 'specimen-rail', 'aria-hidden': 'true' },
        el('span', { class: 'tick tick-cap' }, el('i', {}, 'H')),
        el('span', { class: 'tick tick-x' }, el('i', {}, 'x')),
        el('span', { class: 'tick tick-base' }, el('i', {}, 'p')),
      ),
      el(
        'div',
        {},
        el('p', { class: 'specimen-de', lang: 'de' }, de),
        en ? el('p', { class: 'specimen-en', lang: 'en' }, en) : null,
        el(
          'p',
          { class: 'specimen-caption' },
          'Bodoni Moda. H Versalhöhe, x x-Höhe, p Grundlinie.',
        ),
      ),
    ),
    el(
      'div',
      { class: 'specimen-foot' },
      action,
      link(`#/lesson/${target.id}`, 'Überblick', 'button quiet'),
    ),
  );
}

function lessonSection(lessons) {
  const state = { level: null };
  const shell = el('div', {});
  const head = el(
    'div',
    { class: 'section-head accent-hoeren' },
    el('h2', { class: 'section-heading' }, 'Lektionen'),
    el('span', { class: 'mono-label' }, 'nach Niveau'),
  );

  const tabs = el('div', { class: 'domain-tabs', role: 'tablist', 'aria-label': 'Niveau' });
  const list = el('div', { class: 'matrix-shell' });

  const counts = new Map(LEVELS.map((level) => [level, lessons.filter((l) => l.level === level).length]));
  const options = [{ level: null, label: 'Alle', count: null }].concat(
    LEVELS.map((level) => ({ level, label: level, count: counts.get(level) })),
  );

  for (const option of options) {
    tabs.append(
      el(
        'button',
        {
          type: 'button',
          class: 'tab-btn',
          role: 'tab',
          'aria-selected': String(option.level === null),
          'data-level': option.level || '',
          onClick: () => {
            state.level = option.level;
            tabs.querySelectorAll('.tab-btn').forEach((node) => {
              node.setAttribute('aria-selected', String((node.dataset.level || null) === (option.level || '')));
            });
            paint();
          },
        },
        option.label,
        option.count === null ? null : el('span', { class: 'tab-count' }, String(option.count)),
      ),
    );
  }

  function paint() {
    const rows = lessons.filter((lesson) => !state.level || lesson.level === state.level);
    list.replaceChildren(...rows.map(rowFor));
    if (!rows.length) list.append(el('p', { class: 'loading' }, 'Keine Lektion auf diesem Niveau.'));
  }

  shell.append(head, tabs, list);
  paint();
  return shell;
}

function rowFor(lesson) {
  const detailId = `detail-${lesson.id}`;
  const entry = el('div', { class: 'matrix-entry' });
  const button = el(
    'button',
    {
      type: 'button',
      class: 'matrix-row-btn',
      'aria-expanded': 'false',
      'aria-controls': detailId,
    },
    el('span', { class: 'index-level' }, lesson.level),
    el(
      'span',
      {},
      el('span', { class: 'problem-title' }, lesson.title.de),
      el('span', { class: 'problem-desc' }, lesson.title.en),
    ),
    el(
      'span',
      {},
      el('span', { class: 'repo-slug' }, fmtMinutes(lesson.duration_ms || lesson.minutes * 60000)),
      el('span', { class: 'repo-slug' }, `${lesson.segments} Sätze`),
    ),
    el(
      'span',
      { class: 'evidence-cell' },
      lesson.rendered
        ? el('span', { class: 'badge ok' }, 'Audio')
        : el('span', { class: 'badge' }, 'Text'),
    ),
    el('span', { class: 'expand-chevron', 'aria-hidden': 'true' }, '+'),
  );

  const detail = el(
    'div',
    { class: 'matrix-detail', id: detailId, hidden: true },
    el(
      'div',
      { class: 'detail-block' },
      el('h3', { class: 'detail-block-title' }, 'Szene'),
      el('p', {}, lesson.tags.length ? lesson.tags.join(', ') : 'ohne Angabe'),
      el('p', { class: 'problem-desc' }, lesson.can_do.de),
    ),
    el(
      'div',
      { class: 'detail-block' },
      el('h3', { class: 'detail-block-title' }, 'Grammatik'),
      el(
        'div',
        { class: 'chip-row' },
        ...(lesson.grammar_focus.length
          ? lesson.grammar_focus.map((item) => el('span', { class: 'chip' }, item))
          : [el('span', { class: 'chip' }, 'ohne Angabe')]),
      ),
    ),
    el(
      'div',
      { class: 'detail-block' },
      el('h3', { class: 'detail-block-title' }, 'Weiter'),
      el(
        'div',
        { class: 'button-row' },
        lesson.rendered
          ? link(`#/play/${lesson.id}`, 'Hören', 'button')
          : link(`#/lesson/${lesson.id}`, 'Lektion', 'button'),
        link(`#/clip/${lesson.id}`, 'Video', 'button quiet'),
        link(`#/cards/${lesson.id}`, 'Karten', 'button quiet'),
        link(`#/lesson/${lesson.id}`, 'Details', 'button quiet'),
      ),
    ),
  );

  button.addEventListener('click', () => {
    const open = button.getAttribute('aria-expanded') === 'true';
    button.setAttribute('aria-expanded', String(!open));
    detail.hidden = open;
    entry.classList.toggle('is-expanded', !open);
  });

  entry.append(button, detail);
  return entry;
}

function healthLine(health) {
  if (!health) return el('p', { class: 'loading' }, 'Health unklar, der Server antwortet nicht.');
  const bits = [];
  if (!health.voices_ok) {
    bits.push(`${health.missing_voices.length} von 6 Stimmen fehlen`);
  }
  if (!health.voicestudio.up) {
    bits.push('VoiceStudio läuft nicht, gerenderte Lektionen spielen trotzdem');
  }
  return el(
    'p',
    { class: 'mono-label health-line' },
    bits.length ? bits.join(', ') : 'Alles bereit, lokal, kein Tracking',
  );
}
