// app.js — helpers shared by index.html and book.html.
// No build step: relies on marked.js (loaded via CDN in the HTML pages).

/* ---------------- Frontmatter + Markdown ---------------- */

function parseFrontmatter(raw) {
  const match = raw.match(/^---\s*\n([\s\S]*?)\n---\s*\n?([\s\S]*)$/);
  if (!match) return { meta: {}, body: raw };

  const [, fmBlock, body] = match;
  const meta = {};
  fmBlock.split('\n').forEach((line) => {
    const m = line.match(/^([a-zA-Z_]+):\s*(.*)$/);
    if (!m) return;
    const key = m[1].trim();
    let value = m[2].trim();
    if (value.startsWith('[') && value.endsWith(']')) {
      value = value
        .slice(1, -1)
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean);
    }
    meta[key] = value;
  });
  return { meta, body: body.trim() };
}

// Splits the markdown body into ## sections: [{ heading, content }, ...]
function splitSections(body) {
  const parts = body.split(/\n(?=##\s+)/).map((s) => s.trim()).filter(Boolean);
  return parts.map((part) => {
    const m = part.match(/^##\s+(.+)\n?([\s\S]*)$/);
    if (!m) return { heading: '', content: part };
    return { heading: m[1].trim(), content: m[2].trim() };
  });
}

async function fetchBook(slug) {
  const res = await fetch(`books/${slug}.md`);
  if (!res.ok) throw new Error(`کتاب یافت نشد: ${slug}`);
  const raw = await res.text();
  const { meta, body } = parseFrontmatter(raw);
  return { slug, meta, body };
}

let manifestCache = null;
async function fetchManifest() {
  if (manifestCache) return manifestCache;
  const res = await fetch('books.json');
  manifestCache = await res.json();
  return manifestCache;
}

async function fetchAllBooks() {
  const slugs = await fetchManifest();
  return Promise.all(slugs.map(fetchBook));
}

/* ---------------- Cover generation ---------------- */

const COVER_PALETTE = [
  { bg: 'linear-gradient(155deg,#e9d7a8,#cfa94f)', text: '#3a2b0c' },
  { bg: 'linear-gradient(155deg,#3c5548,#233329)', text: '#eef1ea' },
  { bg: 'linear-gradient(155deg,#c98a63,#a1583a)', text: '#fff8ef' },
  { bg: 'linear-gradient(155deg,#4a5877,#2c3550)', text: '#eceaf0' },
  { bg: 'linear-gradient(155deg,#332f28,#1c1a15)', text: '#e8e2d0' },
];

function hashStr(str) {
  let h = 0;
  for (let i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) >>> 0;
  return h;
}

function coverStyle(slug) {
  return COVER_PALETTE[hashStr(slug) % COVER_PALETTE.length];
}

/* ---------------- Small inline icons ---------------- */

const ICONS = {
  search: '<svg class="icon" viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg>',
  sun: '<svg class="icon" viewBox="0 0 24 24"><circle cx="12" cy="12" r="4.5"/><path d="M12 2v2.2M12 19.8V22M4.9 4.9l1.6 1.6M17.5 17.5l1.6 1.6M2 12h2.2M19.8 12H22M4.9 19.1l1.6-1.6M17.5 6.5l1.6-1.6"/></svg>',
  moon: '<svg class="icon" viewBox="0 0 24 24"><path d="M20 14.5A8.5 8.5 0 1 1 9.5 4a7 7 0 0 0 10.5 10.5z"/></svg>',
  calendar: '<svg class="icon" viewBox="0 0 24 24"><rect x="3.5" y="5" width="17" height="16" rx="2"/><path d="M3.5 10h17M8 3v4M16 3v4"/></svg>',
  clock: '<svg class="icon" viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/></svg>',
  tag: '<svg class="icon" viewBox="0 0 24 24"><path d="M11.5 3.5H5a1.5 1.5 0 0 0-1.5 1.5v6.5L13 21l8-8-9.5-9.5z"/><circle cx="8.2" cy="8.2" r="1.3"/></svg>',
  arrowLeft: '<svg class="icon" viewBox="0 0 24 24"><path d="M19 12H5M11 6l-6 6 6 6"/></svg>',
  arrowRight: '<svg class="icon" viewBox="0 0 24 24"><path d="M5 12h14M13 6l6 6-6 6"/></svg>',
};

function starString(rating) {
  const n = parseInt(rating, 10);
  if (!n || n < 1) return '';
  return '★'.repeat(Math.min(n, 5)) + '☆'.repeat(Math.max(0, 5 - n));
}

/* ---------------- Theme toggle ---------------- */

function initTheme() {
  const saved = localStorage.getItem('theme');
  if (saved) document.documentElement.setAttribute('data-theme', saved);

  const btn = document.getElementById('theme-toggle');
  if (!btn) return;

  const paintIcon = () => {
    const isDark =
      document.documentElement.getAttribute('data-theme') === 'dark' ||
      (!document.documentElement.hasAttribute('data-theme') &&
        window.matchMedia('(prefers-color-scheme: dark)').matches);
    btn.innerHTML = isDark ? ICONS.sun : ICONS.moon;
  };
  paintIcon();

  btn.addEventListener('click', () => {
    const current = document.documentElement.getAttribute('data-theme');
    const isDarkNow =
      current === 'dark' ||
      (!current && window.matchMedia('(prefers-color-scheme: dark)').matches);
    const next = isDarkNow ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('theme', next);
    paintIcon();
  });
}

document.addEventListener('DOMContentLoaded', initTheme);
