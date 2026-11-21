/* Tiny DOM helpers. No framework, no innerHTML — everything is text nodes. */

export function el(tag, props = null, ...children) {
  const node = document.createElement(tag);
  if (props) {
    for (const [key, value] of Object.entries(props)) {
      if (value === null || value === undefined || value === false) continue;
      if (key === 'class') node.className = value;
      else if (key === 'dataset') Object.assign(node.dataset, value);
      else if (key === 'style') Object.assign(node.style, value);
      else if (key.startsWith('on') && typeof value === 'function') {
        node.addEventListener(key.slice(2).toLowerCase(), value);
      } else if (value === true) node.setAttribute(key, '');
      else node.setAttribute(key, String(value));
    }
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

export function clear(node) {
  node.replaceChildren();
}

export function fmtClock(ms) {
  const total = Math.max(0, Math.round((ms || 0) / 1000));
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${minutes}:${String(seconds).padStart(2, '0')}`;
}

export function fmtMinutes(ms) {
  const minutes = Math.round((ms || 0) / 60000);
  if (minutes < 1) return 'unter 1 Min.';
  return `${minutes} Min.`;
}

/* Authored prose arrives with straight apostrophes and three dots. Set them
   as typographic characters at the point of display, never in the data. */
export function typo(text) {
  return String(text ?? '')
    .replace(/'/g, '\u2019')
    .replace(/\.\.\./g, '\u2026');
}

export function setPill(text) {
  const pill = document.getElementById('level-pill');
  if (!pill) return;
  pill.textContent = text || '';
  pill.hidden = !text;
}

let toastTimer = null;

export function toast(message) {
  const node = document.getElementById('toast');
  if (!node) return;
  node.textContent = message;
  node.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    node.hidden = true;
  }, 2600);
}

export function statusBlock(title, body, actions = []) {
  return el(
    'section',
    { class: 'empty' },
    el('h2', {}, title),
    el('p', { class: 'muted' }, body),
    actions.length ? el('div', { class: 'button-row' }, ...actions) : null,
  );
}

export function link(href, label, cls = 'button') {
  return el('a', { class: cls, href }, label);
}
