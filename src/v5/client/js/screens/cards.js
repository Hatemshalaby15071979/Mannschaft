/* Screen 10 — Sentence cards. One card on screen at a time, built from the
   lesson's own segments and glossary. Audio comes from the existing per-line
   render; the browser's speech synthesis is the fallback when a line has no
   render. Grading writes a `card_graded` event and nothing else. */

import { api } from '../api.js';
import { getDetail } from '../store.js';
import { el, setPill, statusBlock, toast } from '../ui.js';

const KIND_LABEL = {
  recall: 'Erinnern · DE → EN',
  cloze: 'Lücke füllen',
  order: 'Satz ordnen',
  produce: 'Selbst sprechen',
};

export async function render([id]) {
  let deck;
  let detail = null;
  try {
    [deck, detail] = await Promise.all([
      api.cards(id),
      Promise.resolve(getDetail(id)).catch(() => null),
    ]);
  } catch (error) {
    return statusBlock(
      'Keine Karten',
      error.status === 404
        ? 'Für diese Lektion wurden noch keine Karten erzeugt (python -m v5.cards.build).'
        : error.message,
    );
  }

  if (!deck.cards || !deck.cards.length) {
    return statusBlock('Keine Karten', 'Das Deck ist leer.');
  }

  if (detail) setPill(detail.lesson.level);
  const title = detail ? detail.lesson.title.de : id;
  const cards = deck.cards;
  const state = { index: 0, revealed: false, graded: 0, built: [], checked: null };

  const root = el('section', { class: 'accent-karten' });
  const stage = el('div', { class: 'card-stage', 'aria-live': 'polite' });
  const footer = el('div', { class: 'card-footer' });
  root.append(
    el('span', { class: 'mono-label' }, 'Karten · eine pro Bildschirm'),
    el('h1', {}, title),
    stage,
    footer,
    el('p', { class: 'mono-label', style: { marginTop: '1rem' } },
      'Tippe ein Wort an, um es im Wörterbuch nachzuschlagen.'),
  );

  const audio = new Audio();

  function speak(text) {
    if ('speechSynthesis' in window) {
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = 'de-DE';
      utterance.rate = 0.9;
      window.speechSynthesis.cancel();
      window.speechSynthesis.speak(utterance);
      return;
    }
    toast('Kein Audio und keine Browser-Sprachausgabe.');
  }

  function play(card) {
    if (card.segment_id) {
      audio.src = api.lineUrl(id, card.segment_id);
      audio.play().catch(() => speak(card.prompt_de || card.answer_de || ''));
    } else {
      speak(card.answer_de || card.prompt_de || '');
    }
  }

  function words(text) {
    const nodes = [];
    const parts = String(text).split(/(\s+)/);
    for (const part of parts) {
      if (!part.trim()) {
        nodes.push(part);
        continue;
      }
      const clean = part.replace(/^[^\p{L}\p{N}]+|[^\p{L}\p{N}]+$/gu, '');
      if (!clean) {
        nodes.push(part);
        continue;
      }
      nodes.push(
        el('button', {
          type: 'button',
          class: 'word',
          onClick: () => {
            location.hash = `#/dict?q=${encodeURIComponent(clean)}`;
          },
        }, part),
      );
    }
    return nodes;
  }

  function paintPrompt(card) {
    if (card.kind === 'cloze') {
      const parts = String(card.prompt_de).split('___');
      const nodes = [];
      parts.forEach((part, i) => {
        if (i > 0) nodes.push(el('span', { class: 'blank' }, ' '));
        nodes.push(...words(part));
      });
      return el('p', { class: 'card-prompt' }, ...nodes);
    }
    return el('p', { class: 'card-prompt' }, ...words(card.prompt_de || ''));
  }

  function paint() {
    const card = cards[state.index];
    state.revealed = false;
    state.built = [];
    state.checked = null;

    stage.replaceChildren();
    stage.append(el('span', { class: 'card-kind' }, KIND_LABEL[card.kind] || card.kind));

    if (card.kind === 'order') {
      stage.append(el('p', { class: 'card-prompt' }, 'Bau den Satz.'));
      const tokens = el('div', { class: 'card-tokens' });
      const builtLine = el('p', { class: 'card-answer', style: { borderTop: '0', paddingTop: '0' } }, '');
      card.tokens.forEach((token, index) => {
        tokens.append(
          el('button', {
            type: 'button',
            class: 'chip',
            'data-token': String(index),
            onClick: (event) => {
              const button = event.currentTarget;
              if (state.built.includes(index)) {
                state.built = state.built.filter((i) => i !== index);
                button.removeAttribute('aria-pressed');
              } else {
                state.built.push(index);
                button.setAttribute('aria-pressed', 'true');
              }
              builtLine.textContent = state.built.map((i) => card.tokens[i]).join(' ');
            },
          }, token),
        );
      });
      stage.append(tokens, builtLine);
    } else if (card.kind === 'produce') {
      stage.append(
        el('p', { class: 'card-prompt' }, card.can_do_en || ''),
        el('p', { class: 'card-hint' }, 'Sag es laut auf Deutsch. Dann vergleiche.'),
      );
    } else {
      stage.append(paintPrompt(card));
      if (card.hint) stage.append(el('p', { class: 'card-hint' }, card.hint));
    }

    const answer = el('div', { class: 'card-answer', hidden: true });
    answer.append(answerFor(card));
    stage.append(answer);

    const actions = el('div', { class: 'button-row' },
      el('button', {
        type: 'button',
        class: 'button quiet',
        onClick: () => play(card),
      }, 'Anhören'),
      el('button', {
        type: 'button',
        class: 'button',
        onClick: () => {
          answer.hidden = false;
          state.revealed = true;
          paintFooter();
        },
      }, card.kind === 'order' ? 'Lösung zeigen' : 'Antwort zeigen'),
    );
    stage.append(actions);

    paintFooter();
  }

  function answerFor(card) {
    if (card.kind === 'recall') return el('p', {}, card.answer_en || '');
    if (card.kind === 'cloze') return el('p', {}, card.answer_de || '');
    if (card.kind === 'order') return el('p', {}, card.answer || '');
    return el('p', {}, card.answer_de || '');
  }

  function paintFooter() {
    footer.replaceChildren(
      el('span', { class: 'card-progress' },
        `Karte ${state.index + 1} von ${cards.length} · gewusst ${state.graded}`),
      state.revealed
        ? el('span', { class: 'card-score' },
            el('button', {
              type: 'button',
              class: 'button good',
              onClick: () => grade('good'),
            }, 'Gewusst'),
            el('button', {
              type: 'button',
              class: 'button again',
              onClick: () => grade('again'),
            }, 'Nochmal'))
        : el('span', { class: 'card-hint' }, 'Erst erinnern, dann zeigen.'),
    );
  }

  function grade(value) {
    const card = cards[state.index];
    if (value === 'good') state.graded += 1;
    api
      .event({
        lesson_id: id,
        event: 'card_graded',
        seg_id: card.segment_id || undefined,
        detail: { card_id: card.id, kind: card.kind, grade: value },
      })
      .catch(() => {});
    toast(value === 'good' ? 'Gut.' : 'Kommt wieder.');
    state.index = (state.index + 1) % cards.length;
    paint();
  }

  paint();
  document.getElementById('screen').append(root);
  return { node: root };
}
