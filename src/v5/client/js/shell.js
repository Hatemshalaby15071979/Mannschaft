/* V6 shell behaviour: theme, intensity, motion, focus mode, active index.

   State is a per-device preference in localStorage, exactly like v5's playback
   prefs. Nothing here talks to the server. The controls are plain buttons so
   they stay keyboard-reachable and work before any screen has loaded. */

const KEY = 'v6.shell';
const THEMES = ['dark', 'light'];
const INTENSITIES = ['calm', 'balanced', 'vivid'];
const INTENSITY_LABEL = { calm: 'Ruhig', balanced: 'Ausgewogen', vivid: 'Kräftig' };

/* No stored choice follows the system: a dark desktop should not open a
   paper page. The toggle still wins once the reader picks. */
function systemTheme() {
  try {
    return matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  } catch {
    return 'light';
  }
}

function read() {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) || '{}');
    return {
      theme: THEMES.includes(raw.theme) ? raw.theme : systemTheme(),
      intensity: INTENSITIES.includes(raw.intensity) ? raw.intensity : 'balanced',
      motion: raw.motion !== false,
      focus: raw.focus === true,
    };
  } catch {
    return { theme: systemTheme(), intensity: 'balanced', motion: true, focus: false };
  }
}

export const shell = read();

function save() {
  try {
    localStorage.setItem(KEY, JSON.stringify(shell));
  } catch {
    /* private mode — in-memory only */
  }
}

function paint() {
  const root = document.documentElement;
  root.dataset.theme = shell.theme;
  root.dataset.intensity = shell.intensity;
  document.body.classList.toggle('reduce-motion', !shell.motion);
  document.body.classList.toggle('focus-mode', shell.focus);

  const exit = document.getElementById('exit-focus');
  if (exit) exit.hidden = !shell.focus;

  const themeButtons = document.querySelectorAll('[data-shell="theme"]');
  for (const button of themeButtons) {
    button.textContent = shell.theme === 'dark' ? 'Hell' : 'Dunkel';
    button.setAttribute('aria-pressed', String(shell.theme === 'light'));
    button.setAttribute('aria-label', 'Farbschema umschalten');
  }
  const intensityButtons = document.querySelectorAll('[data-shell="intensity"]');
  for (const button of intensityButtons) {
    button.textContent = INTENSITY_LABEL[shell.intensity];
    button.setAttribute('aria-label', `Intensität: ${INTENSITY_LABEL[shell.intensity]}`);
  }
  const motionButtons = document.querySelectorAll('[data-shell="motion"]');
  for (const button of motionButtons) {
    button.textContent = shell.motion ? 'Bewegung an' : 'Bewegung aus';
    button.setAttribute('aria-pressed', String(!shell.motion));
  }
  const focusButtons = document.querySelectorAll('[data-shell="focus"]');
  for (const button of focusButtons) {
    button.textContent = 'Fokus';
    button.setAttribute('aria-pressed', String(shell.focus));
    button.setAttribute('aria-label', 'Fokusmodus (F)');
  }
}

function cycle(list, value) {
  const index = list.indexOf(value);
  return list[(index + 1) % list.length];
}

function ensureExitButton() {
  if (document.getElementById('exit-focus')) return;
  const button = document.createElement('button');
  button.id = 'exit-focus';
  button.type = 'button';
  button.className = 'exit-focus';
  button.textContent = 'Fokus beenden (Esc)';
  button.hidden = true;
  button.addEventListener('click', () => {
    shell.focus = false;
    save();
    paint();
  });
  document.body.append(button);
}

/* ------------------------------------------------------- active index item */

/* Two chromes carry links: the contents index and the phone tab bar. A route
   maps to every nav name it lights, so both agree on where you are. */
const NAV_FOR_PATH = [
  [/^\/$/, ['heute', 'home']],
  [/^\/library/, ['bibliothek', 'library']],
  [/^\/clip\//, ['video']],
  [/^\/cards\//, ['karten']],
  [/^\/drill\//, ['karten']],
  [/^\/dict/, ['woerter']],
  [/^\/glossary/, ['woerter']],
  [/^\/progress/, ['fortschritt', 'progress']],
  [/^\/lesson\//, ['lektion']],
  [/^\/play\//, ['lektion']],
  [/^\/transcript\//, ['lektion']],
];

function currentPath() {
  return (location.hash.replace(/^#/, '') || '/').split('?')[0];
}

const LESSON_PATH = /^\/(?:lesson|play|transcript|glossary|clip|cards|drill)\/([^/?#]+)/;

/* The sidebar's Lektion / Video / Karten links follow the lesson you last
   opened, so they are one tap away instead of pointing at a fixed example. */
function rememberLesson(path) {
  const match = LESSON_PATH.exec(path);
  if (match) {
    try {
      localStorage.setItem('v6.lastLesson', match[1]);
    } catch {
      /* private mode */
    }
  }
  let id = null;
  try {
    id = localStorage.getItem('v6.lastLesson');
  } catch {
    id = null;
  }
  if (!id) return;
  const targets = { lektion: `#/lesson/${id}`, video: `#/clip/${id}`, karten: `#/cards/${id}` };
  for (const [nav, href] of Object.entries(targets)) {
    document.querySelectorAll(`nav a[data-nav="${nav}"]`).forEach((link) => link.setAttribute('href', href));
  }
}

export function paintNav() {
  const path = currentPath();
  rememberLesson(path);
  let active = [];
  for (const [pattern, names] of NAV_FOR_PATH) {
    if (pattern.test(path)) {
      active = names;
      break;
    }
  }
  document.querySelectorAll('nav a[data-nav]').forEach((node) => {
    const on = active.includes(node.dataset.nav);
    node.classList.toggle('is-active', on);
    if (on) node.setAttribute('aria-current', 'page');
    else node.removeAttribute('aria-current');
  });
}

export function wireShellControls() {
  ensureExitButton();

  const bind = (name, act) => {
    for (const button of document.querySelectorAll(`[data-shell="${name}"]`)) {
      button.addEventListener('click', () => {
        act();
        save();
        paint();
      });
    }
  };

  bind('theme', () => { shell.theme = shell.theme === 'dark' ? 'light' : 'dark'; });
  bind('intensity', () => { shell.intensity = cycle(INTENSITIES, shell.intensity); });
  bind('motion', () => { shell.motion = !shell.motion; });
  bind('focus', () => { shell.focus = !shell.focus; });

  document.addEventListener('keydown', (event) => {
    if (event.target.closest('input, textarea, select, [contenteditable]')) return;
    if (event.key === 'f' || event.key === 'F') {
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      event.preventDefault();
      shell.focus = !shell.focus;
      save();
      paint();
    } else if (event.key === 'Escape' && shell.focus) {
      shell.focus = false;
      save();
      paint();
    }
  });

  window.addEventListener('hashchange', paintNav);
  paint();
  paintNav();
}
