/* Screen 1 — Home. The matrix shell with German content: masthead, honest
   notice strip, KPI tiles, level tabs and expandable lesson rows.

   One primary action stays the rule: the "Heute" card is the only loud thing
   on the page. Everything else is calm, dense and skimmable. */

import { api } from '../api.js';
import { el, fmtClock, fmtMinutes, link, statusBlock } from '../ui.js';

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
      `Kein v5-Server erreichbar: ${error.message} · Starte mit <code>make serve</code> (Port 8766).`,
    );
  }
  health = await api.health().catch(() => null);

  const byId = new Map(lessons.map((lesson) => [lesson.id, lesson]));
  const resume = progress.resume;
  const resumed = resume ? byId.get(resume.lesson_id) : null;
  const next = lessons.find((lesson) => lesson.id !== (resume && resume.lesson_id)) || null;
  const target = resumed || next;

  const root = el('div', {});
  root.append(masthead(lessons), kpis(lessons, progress, health), todayCard(target, resume, byId));
  root.append(lessonSection(lessons));
  root.append(healthLine(health));

  document.getElementById('screen').append(root);
  return { node: root };
}

/* ------------------------------------------------------------------ pieces */

function masthead(lessons) {
  const levels = [...new Set(lessons.map((lesson) => lesson.level))].sort();
  const span = levels.length ? `${levels[0]}–${levels[levels.length - 1]}` : 'A1–C2';
  return el(
    'header',
    { class: 'masthead' },
    el(
      'div',
      { class: 'masthead-top' },
      el(
        'div',
        {},
        el('span', { class: 'mono-label' }, `Mannschaft · ${span}`),
        el('h1', { class: 'headline' }, 'Hören zuerst. ', el('strong', {}, 'Verstehen kommt nach.')),
        el(
          'p',
          { class: 'lede' },
          'Eine Lektion, eine Hauptaktion. Zwölf handgeschriebene Pilot-Lektionen von A1 bis C2, mit Audio, Video und Karten aus demselben Material.',
        ),
      ),
      el(
        'div',
        { class: 'identity-meta' },
        el('span', {}, `${lessons.length} Lektionen`),
        el('span', {}, '2 pro Niveau'),
        el('span', {}, 'lokal · Port 8766'),
      ),
    ),
    el(
      'div',
      { class: 'notice-strip', role: 'note' },
      el('span', { class: 'notice-strip-icon', 'aria-hidden': 'true' }, '!'),
      el(
        'p',
        {},
        el('strong', {}, 'Ehrlich: '),
        '12 Pilot-Lektionen, synthetischer Korpus, kein zertifizierter Kurs. Der Video-Korpus ist unausgewogen — wo kein passender Clip existiert, sagt die App das und nutzt dein gerendertes Audio.',
      ),
    ),
  );
}

function kpis(lessons, progress, health) {
  const rendered = lessons.filter((lesson) => lesson.rendered).length;
  const clips = health && health.corpus ? health.corpus.clips : null;
  const days = streak(progress.lessons);
  return el(
    'div',
    { class: 'kpi-grid' },
    tile('Lektionen', lessons.length, `${LEVELS.filter((l) => lessons.some((x) => x.level === l)).length} Niveaus`, 'var(--accent-hoeren)'),
    tile('Gerendert', rendered, `${lessons.length - rendered} ohne Audio`, 'var(--accent-karten)'),
    tile('Videoquellen', clips === null ? '—' : clips, 'bewertete Korpus-Clips', 'var(--accent-video)'),
    tile('Serie', `${days} ${days === 1 ? 'Tag' : 'Tage'}`, 'aufeinanderfolgende Tage', 'var(--accent-fortschritt)'),
  );
}

function tile(label, value, helper, accent) {
  return el(
    'div',
    { class: 'kpi-tile', style: { '--tile-accent': accent } },
    el('span', { class: 'kpi-label' }, label),
    el('span', { class: 'kpi-value' }, String(value)),
    el('span', { class: 'kpi-helper' }, helper),
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

function todayCard(target, resume, byId) {
  const section = el(
    'section',
    { class: 'section-head accent-hoeren' },
    el('h2', { class: 'section-heading' }, 'Heute'),
    el('span', { class: 'mono-label' }, 'eine Hauptaktion'),
  );
  if (!target) {
    return el(
      'div',
      {},
      section,
      statusBlock('Noch keine Lektion', 'Unter <code>v5/content/lessons/</code> liegt nichts.'),
    );
  }

  const position =
    resume && resume.lesson_id === target.id && !resume.completed ? resume.position_ms : 0;
  const duration = target.duration_ms || target.minutes * 60000;
  const card = el(
    'div',
    { class: 'card', 'data-accent': '' },
    el('h2', {}, target.title.de),
    el('p', { class: 'muted' }, target.title.en),
    el(
      'p',
      {},
      target.rendered
        ? position > 5000
          ? `${fmtClock(position)} von ${fmtMinutes(duration)} — weiterhören`
          : `Beginn · ${fmtMinutes(duration)}`
        : 'Noch nicht gerendert — Lektion ansehen',
    ),
    el(
      'div',
      { class: 'button-row' },
      target.rendered
        ? link(`#/play/${target.id}`, resume ? 'Weiterhören' : 'Hören')
        : link(`#/lesson/${target.id}`, 'Lektion ansehen'),
      link(`#/lesson/${target.id}`, 'Überblick', 'button quiet'),
    ),
  );
  card.querySelector('a').classList.add('primary');
  return el('div', {}, section, card);
}

function lessonSection(lessons) {
  const state = { level: null };
  const shell = el('div', {});
  const head = el(
    'div',
    { class: 'section-head accent-hoeren' },
    el('h2', { class: 'section-heading' }, 'Lektionen'),
    el('span', { class: 'mono-label' }, `${lessons.length} Einträge`),
  );

  const tabs = el('div', { class: 'domain-tabs', role: 'tablist', 'aria-label': 'Niveau' });
  const list = el('div', { class: 'matrix-shell' });

  const counts = new Map(LEVELS.map((level) => [level, lessons.filter((l) => l.level === level).length]));
  const options = [{ level: null, label: 'Alle', count: lessons.length }].concat(
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
        el('span', { class: 'tab-count' }, String(option.count)),
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
    el(
      'span',
      {},
      el('span', { class: 'problem-title' }, lesson.title.de),
      el('span', { class: 'problem-desc' }, lesson.title.en),
    ),
    el(
      'span',
      {},
      el('span', { class: 'repo-slug' }, `${lesson.level} · ${lesson.segments} Segmente`),
      el('span', { class: 'problem-desc' }, lesson.can_do.en),
    ),
    el(
      'span',
      { class: 'evidence-cell' },
      lesson.rendered
        ? el('span', { class: 'badge ok' }, 'Audio')
        : el('span', { class: 'badge' }, 'Text'),
      el('span', { class: 'mono-label' }, fmtMinutes(lesson.duration_ms || lesson.minutes * 60000)),
    ),
    el('span', { class: 'expand-chevron', 'aria-hidden': 'true' }, '▾'),
  );

  const detail = el('div', { class: 'matrix-detail', id: detailId, hidden: true },
    el('div', { class: 'detail-block' },
      el('h3', { class: 'detail-block-title' }, 'Szene'),
      el('p', {}, lesson.tags.length ? lesson.tags.join(' · ') : '—'),
      el('p', { class: 'problem-desc' }, lesson.can_do.de),
    ),
    el('div', { class: 'detail-block' },
      el('h3', { class: 'detail-block-title' }, 'Grammatik'),
      el('div', { class: 'chip-row' },
        ...(lesson.grammar_focus.length
          ? lesson.grammar_focus.map((item) => el('span', { class: 'chip' }, item))
          : [el('span', { class: 'chip' }, '—')])),
    ),
    el('div', { class: 'detail-block' },
      el('h3', { class: 'detail-block-title' }, 'Weiter'),
      el('div', { class: 'button-row' },
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
  if (!health) return el('p', { class: 'loading' }, 'Health unklar — der Server antwortet nicht.');
  const bits = [];
  if (!health.voices_ok) {
    bits.push(`${health.missing_voices.length}/6 Stimmen fehlen (VoiceStudio-Design)`);
  }
  if (!health.voicestudio.up) {
    bits.push('VoiceStudio läuft nicht — gerenderte Lektionen spielen trotzdem');
  }
  return el(
    'p',
    { class: 'mono-label', style: { marginTop: '1.5rem' } },
    bits.length ? bits.join(' · ') : 'Alles bereit · lokal · kein Tracking',
  );
}
