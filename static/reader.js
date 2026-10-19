// Lesemodus
const $ = (s, r = document) => r.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const bookId = Number(location.pathname.split("/").filter(Boolean).pop());
const root = document.documentElement;

const FONTS = [
  { id: "literata", name: "Literata", note: "für Bildschirme gemacht", css: '"Literata", Georgia, serif' },
  { id: "atkinson", name: "Hyperlegible", note: "besonders deutlich", css: '"Atkinson Hyperlegible Next", "Atkinson Hyperlegible", sans-serif' },
  { id: "georgia", name: "Georgia", note: "klassische Serifenschrift", css: 'Georgia, "Times New Roman", serif' },
  { id: "system", name: "Systemschrift", note: "wie auf dem Handy", css: 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif' },
];
const THEMES = [
  { id: "papier", name: "Papier", bg: "#f6f4ee", fg: "#22262a" },
  { id: "weiss", name: "Weiß", bg: "#ffffff", fg: "#1a1a1a" },
  { id: "sepia", name: "Sepia", bg: "#efe3c8", fg: "#3b2f22" },
  { id: "grau", name: "Grau", bg: "#d8dcd5", fg: "#1f2428" },
  { id: "nacht", name: "Nacht", bg: "#1d2226", fg: "#c8cec7" },
  { id: "schwarz", name: "Schwarz", bg: "#000000", fg: "#b4b4b4" },
];
const LINEHEIGHTS = [{ id: 1.4, name: "eng" }, { id: 1.6, name: "normal" }, { id: 1.85, name: "weit" }];
const MARGINS = [{ id: "s", name: "schmal", pad: "0.6rem" }, { id: "m", name: "mittel", pad: "1.25rem" }, { id: "l", name: "breit", pad: "2.5rem" }];
const DEFAULTS = { size: 22, font: "literata", theme: "papier", bg: "#f6f4ee", fg: "#22262a", lh: 1.6, margin: "m", justify: false };

function load(key, fallback) { try { const v = localStorage.getItem(key); return v ? JSON.parse(v) : fallback; } catch { return fallback; } }
function save(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* privat */ } }

let prefs = { ...DEFAULTS, ...load("lesen.reader", {}) };

function luminance(hex) {
  const n = parseInt(hex.slice(1), 16);
  const ch = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => {
    v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2];
}

function applyPrefs() {
  const font = FONTS.find((f) => f.id === prefs.font) || FONTS[0];
  const margin = MARGINS.find((m) => m.id === prefs.margin) || MARGINS[1];
  root.style.setProperty("--font", font.css);
  root.style.setProperty("--size", `${prefs.size}px`);
  root.style.setProperty("--lh", prefs.lh);
  root.style.setProperty("--pad", margin.pad);
  root.style.setProperty("--bg", prefs.bg);
  root.style.setProperty("--fg", prefs.fg);
  const dark = luminance(prefs.bg) < 0.2;
  root.classList.toggle("dim-images", dark);
  root.style.colorScheme = dark ? "dark" : "light";
  $("#theme-color").content = prefs.bg;
  $("#text").classList.toggle("justify", !!prefs.justify);
  save("lesen.reader", prefs);
  renderSettings();
}

function setPref(patch) {
  const anchor = currentAnchor();
  prefs = { ...prefs, ...patch };
  applyPrefs();
  restoreAnchor(anchor);
}

// Beim Umstellen von Schrift/Größe an derselben Textstelle bleiben
function currentAnchor() {
  const blocks = $("#text").children;
  const top = 80;
  for (const el of blocks) {
    const r = el.getBoundingClientRect();
    if (r.bottom > top) return { el, offset: r.top - top };
  }
  return null;
}
function restoreAnchor(a) {
  if (!a || !a.el.isConnected) return;
  window.scrollTo(0, window.scrollY + a.el.getBoundingClientRect().top - 80 - a.offset);
}

// ---------------------------------------------------------------------------
// Einstellungs-Blatt
// ---------------------------------------------------------------------------
function choiceGroup(container, items, current, render, onPick) {
  container.innerHTML = items.map((it) =>
    `<button type="button" class="choice" role="radio" aria-checked="${String(it.id) === String(current)}" data-id="${esc(it.id)}">${render(it)}</button>`).join("");
  container.onclick = (e) => {
    const b = e.target.closest(".choice");
    if (b) onPick(items.find((it) => String(it.id) === b.dataset.id));
  };
}

function renderSettings() {
  $("#size").value = prefs.size;
  choiceGroup($("#fonts"), FONTS, prefs.font,
    (f) => `<span style='font-family:${f.css.replace(/'/g, "")}'>${esc(f.name)}</span><small>${esc(f.note)}</small>`,
    (f) => setPref({ font: f.id }));
  choiceGroup($("#themes"), THEMES, prefs.theme,
    (t) => `<span class="sr-only">${esc(t.name)}</span>`,
    (t) => setPref({ theme: t.id, bg: t.bg, fg: t.fg }));
  [...$("#themes").children].forEach((b, i) => {
    b.style.background = THEMES[i].bg; b.style.color = THEMES[i].fg;
    b.textContent = "A"; b.title = THEMES[i].name; b.setAttribute("aria-label", THEMES[i].name);
  });
  $("#custom-bg").value = prefs.bg;
  choiceGroup($("#lineheights"), LINEHEIGHTS, prefs.lh, (l) => esc(l.name), (l) => setPref({ lh: l.id }));
  choiceGroup($("#margins"), MARGINS, prefs.margin, (m) => esc(m.name), (m) => setPref({ margin: m.id }));
  $("#justify").checked = !!prefs.justify;
}

$("#size").addEventListener("input", (e) => setPref({ size: Number(e.target.value) }));
$("#size-down").addEventListener("click", () => setPref({ size: Math.max(16, prefs.size - 1) }));
$("#size-up").addEventListener("click", () => setPref({ size: Math.min(48, prefs.size + 1) }));
$("#custom-bg").addEventListener("input", (e) => {
  const bg = e.target.value;
  setPref({ theme: "eigene", bg, fg: luminance(bg) < 0.2 ? "#d0d5cf" : "#1f2428" });
});
$("#justify").addEventListener("change", (e) => setPref({ justify: e.target.checked }));

// Blätter öffnen/schließen
function openSheet(id) {
  closeSheets();
  $(`#${id}`).hidden = false;
  $("#scrim").hidden = false;
  $(`[aria-controls="${id}"]`).setAttribute("aria-expanded", "true");
  $(`#${id} [data-close]`).focus();
}
function closeSheets() {
  for (const id of ["toc", "settings"]) {
    $(`#${id}`).hidden = true;
    $(`[aria-controls="${id}"]`).setAttribute("aria-expanded", "false");
  }
  $("#scrim").hidden = true;
}
$("#open-toc").addEventListener("click", () => openSheet("toc"));
$("#open-settings").addEventListener("click", () => openSheet("settings"));
$("#scrim").addEventListener("click", closeSheets);
document.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", closeSheets));
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeSheets(); });

// ---------------------------------------------------------------------------
// Buch und Kapitel
// ---------------------------------------------------------------------------
let book = null;
let current = -1;
const posKey = `lesen.pos.${bookId}`;

async function api(path) {
  const r = await fetch(path);
  const data = await r.json().catch(() => null);
  if (!r.ok) throw new Error((data && data.detail) || `Fehler ${r.status}`);
  return data;
}

function renderToc() {
  $("#toc-list").innerHTML = book.chapters.map((c, i) => `
    <li><a href="#" data-chapter="${i}" ${i === current ? 'aria-current="true"' : ""}>${esc(c.title)}</a>
      ${c.sections.filter((s) => s.level === 2).length ? `<ol>${c.sections.filter((s) => s.level === 2)
        .map((s) => `<li><a href="#" data-chapter="${i}" data-section="${esc(s.id)}">${esc(s.title)}</a></li>`).join("")}</ol>` : ""}
    </li>`).join("");
}

function renderChapterNav() {
  const prev = book.chapters[current - 1];
  const next = book.chapters[current + 1];
  $("#chapter-nav").innerHTML =
    (next ? `<a href="#" class="next" data-chapter="${current + 1}"><small>Nächstes Kapitel</small><strong>${esc(next.title)}</strong></a>` : `<p style="text-align:center;color:var(--soft)">Ende des Buchs</p>`) +
    (prev ? `<a href="#" data-chapter="${current - 1}"><small>Vorheriges Kapitel</small><strong>${esc(prev.title)}</strong></a>` : "");
}

async function showChapter(index, { section = null, frac = null } = {}) {
  if (index < 0 || index >= book.chapters.length) return;
  closeSheets();
  if (index !== current) {
    $("#text").innerHTML = '<p class="loading">Kapitel wird geladen …</p>';
    try {
      const ch = await api(`/api/books/${bookId}/chapters/${index}`);
      $("#text").innerHTML = ch.html;
      $("#text").lang = ch.lang;
      current = index;
    } catch (e) {
      $("#text").innerHTML = `<p class="loading">Das Kapitel konnte nicht geladen werden: ${esc(e.message)}</p>`;
      return;
    }
    $("#chapter-title").textContent = book.chapters[index].title;
    document.title = `${book.chapters[index].title} – ${book.title}`;
    renderToc();
    renderChapterNav();
  }
  if (section) {
    const el = document.getElementById(section);
    if (el) { el.scrollIntoView(); showBar(); savePos(); return; }
  }
  if (frac != null) {
    // Bilder können die Höhe noch ändern – kurz nachjustieren
    const go = () => window.scrollTo(0, frac * (document.documentElement.scrollHeight - innerHeight));
    go(); setTimeout(go, 300); setTimeout(go, 1200);
  } else {
    window.scrollTo(0, 0);
  }
  savePos();
}

document.addEventListener("click", (e) => {
  const a = e.target.closest("a[data-chapter]");
  if (!a) return;
  e.preventDefault();
  showChapter(Number(a.dataset.chapter), { section: a.dataset.section || null });
});

// ---------------------------------------------------------------------------
// Position merken, Leiste aus-/einblenden, Fortschritt
// ---------------------------------------------------------------------------
function scrollFrac() {
  const max = document.documentElement.scrollHeight - innerHeight;
  return max > 0 ? Math.min(1, Math.max(0, scrollY / max)) : 0;
}
let saveTimer;
function savePos() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => save(posKey, { ch: current, frac: scrollFrac() }), 400);
}

let lastY = 0;
function showBar() { $("#bar").classList.remove("hidden"); }
addEventListener("scroll", () => {
  const y = scrollY;
  if (y > lastY + 8 && y > 120) $("#bar").classList.add("hidden");
  else if (y < lastY - 8) showBar();
  lastY = y;
  $("#progress-bar").style.width = `${(scrollFrac() * 100).toFixed(1)}%`;
  savePos();
}, { passive: true });

// Tippen in den Text blendet die Leiste ein oder aus
$("#text").addEventListener("click", (e) => {
  if (e.target.closest("a, button") || getSelection().toString()) return;
  $("#bar").classList.toggle("hidden");
});

// ---------------------------------------------------------------------------
// Start
// ---------------------------------------------------------------------------
(async function init() {
  applyPrefs();
  try {
    book = await api(`/api/books/${bookId}`);
  } catch (e) {
    $("#text").innerHTML = `<p class="loading">Dieses Buch gibt es nicht (mehr). <a href="/#/bibliothek">Zur Bibliothek</a></p>`;
    return;
  }
  $("#book-title").textContent = book.title;
  const pos = load(posKey, null);
  if (pos && pos.ch >= 0 && pos.ch < book.chapters.length) await showChapter(pos.ch, { frac: pos.frac });
  else await showChapter(0);
})();
