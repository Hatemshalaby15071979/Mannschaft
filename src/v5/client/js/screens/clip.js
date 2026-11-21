/* Screen 9 — Clip. One recommended video for this lesson, embedded from the
   privacy-enhanced host. Never autoplays; the user presses play. If the corpus
   has no suitable clip the screen says so and points at the rendered audio. */

import { api } from '../api.js';
import { getDetail } from '../store.js';
import { el, link, setPill, statusBlock } from '../ui.js';

export async function render([id]) {
  let media;
  let detail = null;
  try {
    [media, detail] = await Promise.all([
      api.media(id),
      Promise.resolve(getDetail(id)).catch(() => null),
    ]);
  } catch (error) {
    return statusBlock('Kein Video', error.message);
  }

  if (detail) setPill(detail.lesson.level);
  const title = detail ? detail.lesson.title.de : id;

  const root = el('section', { class: 'accent-video' });
  root.append(
    el('span', { class: 'mono-label' }, 'Video · ein Clip, kein Autoplay'),
    el('h1', {}, title),
  );

  if (!media.primary) {
    root.append(
      el('div', { class: 'clip-frame is-empty' },
        el('p', {},
          el('strong', {}, 'Kein passender freier Clip gefunden. '),
          'Die App nutzt dein gerendertes Audio — das ist ehrlicher als ein unpassendes Video.'),
      ),
      el('div', { class: 'button-row' },
        link(`#/play/${id}`, 'Gerendertes Audio hören'),
        link(`#/lesson/${id}`, 'Zur Lektion', 'button quiet'),
      ),
    );
    document.getElementById('screen').append(root);
    return { node: root };
  }

  const frame = el('div', { class: 'clip-frame' });
  const iframe = el('iframe', {
    src: media.embed_url,
    title: `Video zur Lektion ${title}`,
    loading: 'lazy',
    allow: 'accelerometer; clipboard-write; encrypted-media; gyroscope; picture-in-picture',
    allowfullscreen: true,
    referrerpolicy: 'strict-origin-when-cross-origin',
  });
  frame.append(iframe);
  root.append(frame);

  const pick = media.primary;
  const watch = `https://www.youtube.com/watch?v=${pick.video_id}&t=${Math.floor(pick.start_s)}s`;
  root.append(
    el('div', { class: 'clip-actions' },
      el('a', { href: watch, target: '_blank', rel: 'noopener noreferrer' }, 'Auf YouTube ansehen ↗'),
      link(`#/cards/${id}`, 'Karten üben', 'button quiet'),
      link(`#/play/${id}`, 'Audio hören', 'button quiet'),
    ),
  );

  const note = el('div', { class: 'clip-note' });
  note.append(el('p', {}, pick.reason || 'Empfohlener Clip für diese Lektion.'));
  if (media.relevance && media.relevance.level_gap > 0) {
    note.append(
      el('p', {},
        el('strong', {}, `Niveau-Abstand ${media.relevance.level_gap}: `),
        'Der Korpus hat keinen Clip auf genau diesem Niveau. Der Clip ist als Material gedacht, nicht als Prüfung.'),
    );
  }
  root.append(note);

  if (media.alternates && media.alternates.length) {
    const list = el('ul', { class: 'row-list' });
    for (const alt of media.alternates) {
      list.append(
        el('li', {},
          el('button', {
            type: 'button',
            class: 'button quiet',
            onClick: () => {
              iframe.src = `https://www.youtube-nocookie.com/embed/${alt.video_id}?start=${Math.floor(alt.start_s)}&end=${Math.floor(alt.end_s)}&rel=0`;
            },
          }, 'Anderer Clip'),
          ` ${Math.floor(alt.start_s)}–${Math.floor(alt.end_s)}s`,
        ),
      );
    }
    root.append(el('h2', {}, 'Alternativen'), list);
  }

  /* Fire-and-forget: the clip event is additive, never a reason to fail. */
  api
    .event({
      lesson_id: id,
      event: 'clip_opened',
      detail: { clip_id: pick.clip_id, video_id: pick.video_id },
    })
    .catch(() => {});

  document.getElementById('screen').append(root);
  return { node: root };
}
