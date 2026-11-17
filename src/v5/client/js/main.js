/* Screen router + app shell wiring. Hash routes, one screen at a time. */

import { el, clear, statusBlock } from './ui.js';
import * as home from './screens/home.js';
import * as library from './screens/library.js';
import * as lesson from './screens/lesson.js';
import * as play from './screens/play.js';
import * as transcript from './screens/transcript.js';
import * as glossary from './screens/glossary.js';
import * as drill from './screens/drill.js';
import * as progressScreen from './screens/progress.js';

const ROUTES = [
  { pattern: /^\/$/, screen: home, nav: 'home' },
  { pattern: /^\/library$/, screen: library, nav: 'library' },
  { pattern: /^\/lesson\/([^/?#]+)/, screen: lesson, nav: null },
  { pattern: /^\/play\/([^/?#]+)/, screen: play, nav: null },
  { pattern: /^\/transcript\/([^/?#]+)/, screen: transcript, nav: null },
  { pattern: /^\/glossary\/?([^/?#]*)$/, screen: glossary, nav: 'library' },
  { pattern: /^\/drill\/([^/?#]+)/, screen: drill, nav: 'library' },
  { pattern: /^\/progress$/, screen: progressScreen, nav: 'progress' },
];

let token = 0;
let cleanup = null;

function currentLocation() {
  const raw = location.hash.replace(/^#/, '') || '/';
  const [path, query = ''] = raw.split('?');
  return { path, query: new URLSearchParams(query) };
}

function navFor(path) {
  for (const route of ROUTES) {
    if (route.pattern.test(path)) return route.nav;
  }
  return null;
}

function setActiveNav() {
  const active = navFor(currentLocation().path);
  document.querySelectorAll('.tabbar a').forEach((node) => {
    node.setAttribute('aria-current', node.dataset.nav === active ? 'page' : undefined);
  });
}

async function route() {
  const myToken = ++token;
  if (typeof cleanup === 'function') {
    cleanup();
    cleanup = null;
  }
  clear(document.getElementById('screen'));
  document.getElementById('screen').focus();
  setActiveNav();

  const { path, query } = currentLocation();
  let match = null;
  let params = [];
  for (const candidate of ROUTES) {
    const found = path.match(candidate.pattern);
    if (found) {
      match = candidate;
      params = found.slice(1);
      break;
    }
  }

  const screen = document.getElementById('screen');
  if (!match) {
    screen.append(statusBlock('Nicht gefunden', `Unbekannter Pfad: ${path || '/'} · Nutze die Tabbar.`));
    return;
  }

  screen.append(el('p', { class: 'loading' }, 'Lädt …'));
  try {
    const result = await match.screen.render(params, query);
    if (myToken !== token) return;
    clear(screen);
    screen.append(result.node);
    cleanup = result.cleanup || null;
  } catch (error) {
    if (myToken !== token) return;
    clear(screen);
    screen.append(statusBlock('Fehler', error && error.message ? error.message : String(error)));
  }
}

function wireShell() {
  const helpToggle = document.getElementById('help-toggle');
  const panel = document.getElementById('help-panel');
  helpToggle.addEventListener('click', () => {
    const open = panel.hasAttribute('hidden');
    if (open) panel.removeAttribute('hidden');
    else panel.setAttribute('hidden', '');
    helpToggle.setAttribute('aria-expanded', String(open));
  });

  document.addEventListener('keydown', (event) => {
    if (event.target.closest('input, textarea, [contenteditable]')) return;
    if (event.key === '?') {
      event.preventDefault();
      helpToggle.click();
    } else if (event.key === 'Escape' && !panel.hasAttribute('hidden')) {
      panel.setAttribute('hidden', '');
      helpToggle.setAttribute('aria-expanded', 'false');
    }
  });

  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('/sw.js').catch(() => {});
    });
  }
}

wireShell();
window.addEventListener('hashchange', route);
window.addEventListener('pageshow', (event) => {
  if (event.persisted) route();
});
route();
