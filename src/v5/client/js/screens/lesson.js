/* Screen 3 — Lesson detail. The honest version: if there is no audio yet,
   it says so and offers to render, reporting the real blocker (M4). */

import { api, ApiError } from '../api.js';
import { getDetail, invalidateDetail } from '../store.js';
import { el, fmtMinutes, link, statusBlock } from '../ui.js';

export async function render([id]) {
  let detail;
  try {
    detail = await getDetail(id);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      return statusBlock('Keine Lektion', `Es gibt keine Lektion mit id ${id}.`);
    }
    return statusBlock('Fehler', error.message);
  }

  const { lesson, summary, timeline } = detail;
  const rendered = Boolean(timeline && summary && summary.rendered);

  const root = el('article', {});
  root.append(
    el('h1', {}, lesson.title ? lesson.title.de : id),
    el('p', { class: 'muted' }, lesson.title ? lesson.title.en : ''),
    el('p', {},
      el('strong', {}, lesson.level),
      ` · ${fmtMinutes((summary && summary.duration_ms) || lesson.minutes * 60000)}`,
      ' · ',
      `${lesson.segments.length} Segmente`,
    ),
  );

  root.append(
    el('p', {}, el('em', {}, lesson.scene.can_do_de)),
    el('p', { class: 'muted' }, lesson.scene.can_do_en),
  );

  if (lesson.scene.situation_tags.length) {
    root.append(
      el('div', { class: 'chips' },
        ...lesson.scene.situation_tags.map((tag) => el('span', { class: 'chip' }, tag))),
    );
  }

  root.append(
    el('div', { class: 'button-row' },
      link(`#/play/${id}`, rendered ? 'Hören' : 'Übung (Text)'),
      link(`#/transcript/${id}`, 'Transkript', 'button quiet'),
      link(`#/glossary/${id}`, 'Glossar', 'button quiet'),
      link(`#/drill/${id}`, 'Übung', 'button quiet'),
    ),
  );
  root.querySelector('a').classList.add('primary');

  const audioSlot = el('div', {});
  root.append(audioSlot);
  if (rendered) {
    audioSlot.append(
      el('p', {},
        el('span', { class: 'badge ok' }, 'Audio bereit'),
        ` · ${timeline.length} Zeilen im Timeline`,
      ),
    );
  } else {
    audioSlot.append(renderOffer(id, lesson));
  }

  const glossary = lesson.glossary || [];
  if (glossary.length) {
    root.append(
      el('h2', {}, 'Glossar'),
      el('ul', { class: 'row-list' },
        ...glossary.slice(0, 6).map(
          (entry) =>
            el('li', {},
              el('span', { class: 'gloss-term' }, entry.de),
              ' — ',
              entry.en,
              entry.example_de ? el('div', { class: 'gloss-example' }, entry.example_de) : null,
            ),
        ),
        ...(!glossary.length || glossary.length > 6
          ? [el('li', {}, link(`#/glossary/${id}`, `${glossary.length} Einträge ansehen`, 'button quiet'))]
          : []),
      ),
    );
  }

  document.getElementById('screen').append(root);
  return { node: root };
}

function renderOffer(id, lesson) {
  const offer = el('div', { class: 'card' },
    el('h2', {}, 'Noch kein Audio'),
    el('p', { class: 'muted' },
      'Dieser Text ist validiert, aber noch nicht synthetisiert. Starte den Render-Job — er läuft sequenziell im Hintergrund.'),
  );
  const button = el('button', { class: 'primary', type: 'button' }, 'Jetzt rendern');
  const status = el('p', { class: 'loading', 'aria-live': 'polite' }, '');
  offer.append(button, status);

  button.addEventListener('click', async () => {
    button.disabled = true;
    try {
      const { job } = await api.render(id);
      status.textContent = `Job ${job.job_id} — ${job.state}…`;
      poll(job.job_id, status, () => {
        invalidateDetail(id);
        status.textContent = '';
        button.textContent = 'Nochmal rendern';
        button.disabled = false;
      });
    } catch (error) {
      button.disabled = false;
      if (error instanceof ApiError && error.status === 409) {
        const missing = (error.detail && error.detail.missing_voices) || [];
        status.replaceChildren(
          el('strong', {}, 'Stimmen fehlen: '),
          `${missing.join(', ')}. Erstelle sie in VoiceStudio → Voice Design (M4), dann läuft der Render.`,
        );
      } else {
        status.textContent = error.message;
      }
    }
  });
  return offer;
}

function poll(jobId, status, onDone) {
  const timer = setInterval(async () => {
    try {
      const job = await api.job(jobId);
      if (job.state === 'done') {
        clearInterval(timer);
        status.textContent = `Fertig: ${job.done}/${job.total} Segmente.`;
        onDone();
      } else if (job.state === 'error') {
        clearInterval(timer);
        status.textContent = `Fehler: ${job.error}`;
      } else {
        status.textContent = `${job.done}/${job.total || '?'} Segmente…`;
      }
    } catch {
      clearInterval(timer);
      status.textContent = 'Status unklar (Server neu gestartet?).';
    }
  }, 1500);
}
