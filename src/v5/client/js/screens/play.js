/* Screen 2, Player. One primary action: play/pause. */

import { api, ApiError } from '../api.js';
import { player } from '../player.js';
import { getDetail, prefs, cycleRate, savePrefs, RATES } from '../store.js';
import { el, fmtClock, setPill, statusBlock, toast, typo } from '../ui.js';

export async function render([id], query = {}) {
  let detail, progress;
  try {
    [detail, progress] = await Promise.all([
      getDetail(id),
      api.progress({ _ts: Date.now() }),
    ]);
  } catch (error) {
    return statusBlock('Nicht erreichbar', error.message);
  }
  setPill(detail.lesson.level);
  const row = (progress.lessons || []).find((entry) => entry.lesson_id === id);
  const resumeAt =
    row && !row.completed ? row.position_ms : (query.get('t') ? Number(query.get('t')) : null);
  const autoplay = query.get('play') === '1' || (resumeAt !== null && resumeAt > 0);

  player.load(detail, { positionMs: resumeAt, autoplay });

  const segments = new Map((detail.lesson.segments || []).map((segment) => [segment.id, segment]));
  const root = el('section', { class: 'player-screen' });

  const bar = el('div', { class: 'session-bar' }, el('i', { style: { transform: 'scaleX(0)' } }));
  root.append(bar);

  const now = el('div', { class: 'now' });
  root.append(now);

  const scrub = el('div', { class: 'scrub' },
    el('span', { id: 'time-now' }, '0:00'),
    el('input', {
      type: 'range',
      id: 'seek',
      min: '0',
      max: '0',
      step: '100',
      'aria-label': 'Position',
      value: '0',
    }),
    el('span', { id: 'time-max' }, '0:00'),
  );
  root.append(scrub);

  const transport = el('div', { class: 'transport' });
  root.append(transport);

  const controls = el('div', { class: 'button-row', 'aria-label': 'Wiedergabe' });
  root.append(controls);

  const answer = el('div', { class: 'answer', hidden: true });
  root.append(answer);

  const actions = el('div', { class: 'button-row' },
    el('a', { class: 'button quiet', href: `#/transcript/${id}` }, 'Transkript'),
    el('a', { class: 'button quiet', href: `#/glossary/${id}` }, 'Glossar'),
    el('a', { class: 'button quiet', href: `#/drill/${id}` }, 'Übung'),
  );
  root.append(actions);

  document.getElementById('screen').append(root);

  /* paint -------------------------------------------------------------- */

  let scrubbing = false;
  const seek = scrub.querySelector('#seek');

  function paint(_player, _reason) {
    const entry = _player.currentEntry;
    const duration = _player.durationMs || 1;
    bar.firstElementChild.style.transform = `scaleX(${Math.min(1, _player.positionMs / duration)})`;
    seek.max = String(Math.round(duration / 100) * 100);
    if (!scrubbing) seek.value = String(Math.round(_player.positionMs));
    document.getElementById('time-now').textContent = fmtClock(_player.positionMs);
    document.getElementById('time-max').textContent = fmtClock(duration);

    now.replaceChildren();
    if (entry) {
      const segment = segments.get(entry.id);
      const meta = [entry.speaker, entry.type && entry.type !== 'line' ? entry.type : null]
        .filter(Boolean)
        .join(', ');
      now.append(
        meta ? el('span', { class: 'speaker' }, meta) : null,
        el(
          'div',
          { class: 'now-line' },
          el(
            'div',
            { class: 'specimen-rail', 'aria-hidden': 'true' },
            el('span', { class: 'tick tick-cap' }, el('i', {}, 'H')),
            el('span', { class: 'tick tick-x' }, el('i', {}, 'x')),
            el('span', { class: 'tick tick-base' }, el('i', {}, 'p')),
          ),
          el('div', { class: 'de', lang: 'de' }, entry.text),
        ),
        prefs.translations && segment && segment.translation
          ? el('div', { class: 'en', lang: 'en' }, typo(segment.translation))
          : null,
      );
      paintAnswer(segment);
    } else {
      now.append(el('div', { class: 'de' }, '…'));
      answer.hidden = true;
    }

    const play = transport.querySelector('[data-action=play]');
    if (play) {
      play.textContent = _player.isPlaying ? 'Pause' : 'Abspielen';
      play.setAttribute('aria-label', _player.isPlaying ? 'Pause' : 'Abspielen');
    }
  }

  function paintAnswer(segment) {
    const isCheck = segment && segment.type === 'check';
    answer.hidden = !isCheck || !document.getElementById('show-answer').checked;
    if (answer.hidden) return;
    const answers = (segment.answers || []).join(', ') || 'keine Antwort hinterlegt';
    answer.replaceChildren(el('strong', {}, 'Antwort: '), answers);
  }

  transport.replaceChildren(
    el('button', { class: 'step', type: 'button', 'data-action': 'prev', title: 'Vorheriger Satz (J)' }, 'Zurück'),
    el('button', {
      class: 'primary-play', type: 'button', 'data-action': 'play',
      title: 'Abspielen/Pause (Space)',
    }, 'Abspielen'),
    el('button', { class: 'step', type: 'button', 'data-action': 'next', title: 'Nächster Satz (K)' }, 'Weiter'),
  );
  transport.addEventListener('click', (event) => {
    const action = event.target.closest('[data-action]');
    if (!action) return;
    if (action.dataset.action === 'play') player.toggle();
    else if (action.dataset.action === 'next') player.next();
    else if (action.dataset.action === 'prev') player.prev();
  });

  controls.replaceChildren(
    ...RATES.map((rate) => {
      const label = rate === 1 ? '1,0' : String(rate).replace('.', ',');
      return el('button', {
        class: 'chip', type: 'button', 'data-rate': String(rate),
        'aria-pressed': String(prefs.rate === rate),
        title: `Tempo ${label}`,
      }, label);
    }),
    el('button', {
      class: 'chip', type: 'button', id: 'show-answer',
      'aria-pressed': 'false', title: 'Übersetzung zeigen (T)',
    }, 'Übersetzung'),
    el('button', { class: 'chip', type: 'button', id: 'repeat-line', 'aria-pressed': 'false' }, 'Wiederholen'),
  );
  const showAnswer = document.getElementById('show-answer');
  showAnswer.addEventListener('click', () => {
    const on = showAnswer.getAttribute('aria-pressed') !== 'true';
    showAnswer.setAttribute('aria-pressed', String(on));
    paintAnswer(segments.get(player.currentEntry ? player.currentEntry.id : null));
  });
  controls.querySelectorAll('[data-rate]').forEach((node) => {
    node.addEventListener('click', () => {
      prefs.rate = Number(node.dataset.rate);
      savePrefs();
      player.setRate(prefs.rate);
      controls.querySelectorAll('[data-rate]').forEach((other) =>
        other.setAttribute('aria-pressed', String(other === node)),
      );
    });
  });
  document.getElementById('repeat-line').addEventListener('click', () => {
    const entry = player.currentEntry;
    if (entry) {
      player.seek(entry.start_ms + 50);
      player.play();
    }
  });

  seek.addEventListener('input', () => {
    scrubbing = true;
    player.seek(Number(seek.value));
  });
  seek.addEventListener('change', () => {
    scrubbing = false;
  });

  /* keyboard ----------------------------------------------------------- */

  const keydown = (event) => {
    if (event.target.closest('input, textarea')) return;
    switch (event.key) {
      case ' ':
        event.preventDefault();
        player.toggle();
        break;
      case 'ArrowLeft':
        player.seek(player.positionMs - 5000);
        break;
      case 'ArrowRight':
        player.seek(player.positionMs + 5000);
        break;
      case 'j':
      case 'J':
        player.prev();
        break;
      case 'k':
      case 'K':
        player.next();
        break;
      case 't':
      case 'T':
        showAnswer.click();
        break;
      case 's':
      case 'S': {
        const rate = cycleRate();
        player.setRate(rate);
        controls.querySelectorAll('[data-rate]').forEach((other) =>
          other.setAttribute('aria-pressed', String(Number(other.dataset.rate) === rate)),
        );
        toast(`Tempo ${String(rate).replace('.', ',')}`);
        break;
      }
      default:
        break;
    }
  };
  document.addEventListener('keydown', keydown);

  const unsubscribe = player.subscribe(paint);
  return {
    node: root,
    cleanup() {
      unsubscribe();
      document.removeEventListener('keydown', keydown);
    },
  };
}
