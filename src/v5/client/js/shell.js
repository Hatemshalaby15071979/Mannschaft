/* V6 shell behaviour: theme, intensity, motion, focus mode, active index.

   State is a per-device preference in localStorage, exactly like v5's playback
   prefs. Nothing here talks to the server. The controls are plain buttons so
   they stay keyboard-reachable and work before any screen has loaded. */

const KEY = 'v6.shell';
const THEMES = ['dark', 'light'];
const INTENSITIES = ['calm', 'balanced', 'vivid'];
const INTENSITY_LABEL = { calm: 'Ruhig', balanced: 'Ausgewogen', vivid: 'Kräftig' };

function read() {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) || '{}');
    return {
      theme: THEMES.includes(raw.theme) ? raw.theme : 'dark',
      intensity: INTENSITIES.includes(raw.intensity) ? raw.intensity : 'balanced',
      motion: raw.motion !== false,
      focus: raw.focus === true,
    };
  } catch {
    return { theme: 'dark', intensity: 'balanced', motion: true, focus: false };
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

  const themeBtn = document.querySelector('[data-shell="theme"]');
  if (themeBtn) {
    themeBtn.textContent = shell.theme === 'dark' ? 'Hell' : 'Dunkel';
    themeBtn.setAttribute('aria-pressed', String(shell.theme === 'light'));
    themeBtn.setAttribute('aria-label', 'Farbschema umschalten');
  }
  const intensityBtn = document.querySelector('[data-shell="intensity"]');
  if (intensityBtn) {
    intensityBtn.textContent = INTENSITY_LABEL[shell.intensity];
    intensityBtn.setAttribute('aria-label', `Intensität: ${INTENSITY_LABEL[shell.intensity]}`);
  }
  const motionBtn = document.querySelector('[data-shell="motion"]');
  if (motionBtn) {
    motionBtn.textContent = shell.motion ? 'Bewegung an' : 'Bewegung aus';
    motionBtn.setAttribute('aria-pressed', String(!shell.motion));
  }
  const focusBtn = document.querySelector('[data-shell="focus"]');
  if (focusBtn) {
    focusBtn.textContent = 'Fokus';
    focusBtn.setAttribute('aria-pressed', String(shell.focus));
    focusBtn.setAttribute('aria-label', 'Fokusmodus (F)');
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

const NAV_FOR_PATH = [
  [/^\/$/, 'heute'],
  [/^\/library/, 'bibliothek'],
  [/^\/clip\//, 'video'],
  [/^\/cards\//, 'karten'],
  [/^\/drill\//, 'karten'],
  [/^\/dict/, 'woerter'],
  [/^\/glossary/, 'woerter'],
  [/^\/progress/, 'fortschritt'],
  [/^\/lesson\//, 'lektion'],
  [/^\/play\//, 'lektion'],
  [/^\/transcript\//, 'lektion'],
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
    const link = document.querySelector(`.side-index nav a[data-nav="${nav}"]`);
    if (link) link.setAttribute('href', href);
  }
}

export function paintNav() {
  const path = currentPath();
  rememberLesson(path);
  let active = null;
  for (const [pattern, name] of NAV_FOR_PATH) {
    if (pattern.test(path)) {
      active = name;
      break;
    }
  }
  document.querySelectorAll('.side-index nav a[data-nav]').forEach((node) => {
    const on = node.dataset.nav === active;
    node.classList.toggle('is-active', on);
    if (on) node.setAttribute('aria-current', 'page');
    else node.removeAttribute('aria-current');
  });
}

export function wireShellControls() {
  ensureExitButton();

  document.querySelector('[data-shell="theme"]')?.addEventListener('click', () => {
    shell.theme = shell.theme === 'dark' ? 'light' : 'dark';
    save();
    paint();
  });
  document.querySelector('[data-shell="intensity"]')?.addEventListener('click', () => {
    shell.intensity = cycle(INTENSITIES, shell.intensity);
    save();
    paint();
  });
  document.querySelector('[data-shell="motion"]')?.addEventListener('click', () => {
    shell.motion = !shell.motion;
    save();
    paint();
  });
  document.querySelector('[data-shell="focus"]')?.addEventListener('click', () => {
    shell.focus = !shell.focus;
    save();
    paint();
  });

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
