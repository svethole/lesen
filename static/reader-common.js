// Gemeinsame Teile von ePub-Reader und Wikipedia-Lesemodus:
// Darstellungs-Einstellungen, Seitenblätter, Kopfleiste, Fortschritt.
export const $ = (s, r = document) => r.querySelector(s);
export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const root = document.documentElement;

export function load(key, fallback) { try { const v = localStorage.getItem(key); return v ? JSON.parse(v) : fallback; } catch { return fallback; } }
export function save(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* privat */ } }

export async function api(path, opts = {}) {
  const r = await fetch(path, {
    headers: opts.body ? { "Content-Type": "application/json" } : {},
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const data = await r.json().catch(() => null);
  if (!r.ok) {
    const err = new Error((data && data.detail) || `Fehler ${r.status}`);
    err.status = r.status;
    throw err;
  }
  return data;
}

export const FONTS = [
  { id: "literata", name: "Literata", note: "für Bildschirme gemacht", css: '"Literata", Georgia, serif' },
  { id: "atkinson", name: "Hyperlegible", note: "besonders deutlich", css: '"Atkinson Hyperlegible Next", "Atkinson Hyperlegible", sans-serif' },
  { id: "georgia", name: "Georgia", note: "klassische Serifenschrift", css: 'Georgia, "Times New Roman", serif' },
  { id: "system", name: "Systemschrift", note: "wie auf dem Handy", css: 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif' },
];
export const THEMES = [
  { id: "papier", name: "Papier", bg: "#f6f4ee", fg: "#22262a" },
  { id: "weiss", name: "Weiß", bg: "#ffffff", fg: "#1a1a1a" },
  { id: "sepia", name: "Sepia", bg: "#efe3c8", fg: "#3b2f22" },
  { id: "grau", name: "Grau", bg: "#d8dcd5", fg: "#1f2428" },
  { id: "nacht", name: "Nacht", bg: "#1d2226", fg: "#c8cec7" },
  { id: "glut", name: "Glut (warm, für die Nacht)", bg: "#140f0a", fg: "#c9955a" },
  { id: "schwarz", name: "Schwarz", bg: "#000000", fg: "#b4b4b4" },
];
const LINEHEIGHTS = [{ id: 1.4, name: "eng" }, { id: 1.6, name: "normal" }, { id: 1.85, name: "weit" }];
const MARGINS = [{ id: "s", name: "schmal", pad: "0.6rem" }, { id: "m", name: "mittel", pad: "1.25rem" }, { id: "l", name: "breit", pad: "2.5rem" }];
const DEFAULTS = { size: 22, font: "literata", theme: "papier", bg: "#f6f4ee", fg: "#22262a", lh: 1.6, margin: "m", justify: false, dim: 0 };

export let prefs = { ...DEFAULTS, ...load("lesen.reader", {}) };

function luminance(hex) {
  const n = parseInt(hex.slice(1), 16);
  const ch = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => {
    v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2];
}

export function applyPrefs() {
  const font = FONTS.find((f) => f.id === prefs.font) || FONTS[0];
  const margin = MARGINS.find((m) => m.id === prefs.margin) || MARGINS[1];
  root.style.setProperty("--font", font.css);
  root.style.setProperty("--size", `${prefs.size}px`);
  root.style.setProperty("--lh", prefs.lh);
  root.style.setProperty("--pad", margin.pad);
  root.style.setProperty("--bg", prefs.bg);
  root.style.setProperty("--fg", prefs.fg);
  root.style.setProperty("--dim", prefs.dim || 0);
  const dark = luminance(prefs.bg) < 0.2;
  root.classList.toggle("dim-images", dark);
  root.style.colorScheme = dark ? "dark" : "light";
  const meta = $("#theme-color");
  if (meta) meta.content = prefs.bg;
  const text = $("#text");
  if (text) text.classList.toggle("justify", !!prefs.justify);
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
  const text = $("#text");
  if (!text) return null;
  const top = 80;
  for (const el of text.children) {
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
// Einstellungs-Blatt (wird in <aside id="settings"> eingesetzt)
// ---------------------------------------------------------------------------
const SETTINGS_HTML = `
  <div class="sheet-head">
    <h2>Darstellung</h2>
    <button type="button" class="icon-btn" data-close aria-label="Schließen">
      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>
    </button>
  </div>
  <div class="row">
    <span class="label">Schriftgröße</span>
    <div class="sizer">
      <button type="button" class="step" id="size-down" aria-label="Kleiner">A</button>
      <input type="range" id="size" min="16" max="48" step="1" aria-label="Schriftgröße">
      <button type="button" class="step big" id="size-up" aria-label="Größer">A</button>
    </div>
  </div>
  <div class="row">
    <span class="label">Schrift</span>
    <div class="choices fonts" id="fonts" role="radiogroup" aria-label="Schrift"></div>
  </div>
  <div class="row">
    <span class="label">Hintergrund</span>
    <div class="choices swatches" id="themes" role="radiogroup" aria-label="Hintergrund"></div>
    <label class="custom-color">
      <input type="color" id="custom-bg" value="#f6f4ee">
      <span>Eigene Farbe</span>
    </label>
  </div>
  <div class="row">
    <span class="label" id="dim-label">Zusätzlich abdunkeln</span>
    <div class="sizer">
      <svg class="dim-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M5.6 18.4L7 17M17 7l1.4-1.4"/></svg>
      <input type="range" id="dim" min="0" max="0.7" step="0.05" aria-labelledby="dim-label">
      <svg class="dim-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/></svg>
    </div>
    <p class="hint">Dunkler als die geringste Bildschirmhelligkeit – für das Lesen im Bett.</p>
  </div>
  <div class="row two">
    <div>
      <span class="label">Zeilenabstand</span>
      <div class="choices" id="lineheights" role="radiogroup" aria-label="Zeilenabstand"></div>
    </div>
    <div>
      <span class="label">Seitenrand</span>
      <div class="choices" id="margins" role="radiogroup" aria-label="Seitenrand"></div>
    </div>
  </div>
  <label class="toggle">
    <input type="checkbox" id="justify">
    <span>Blocksatz mit Silbentrennung</span>
  </label>`;

function choiceGroup(container, items, current, render, onPick) {
  container.innerHTML = items.map((it) =>
    `<button type="button" class="choice" role="radio" aria-checked="${String(it.id) === String(current)}" data-id="${esc(it.id)}">${render(it)}</button>`).join("");
  container.onclick = (e) => {
    const b = e.target.closest(".choice");
    if (b) onPick(items.find((it) => String(it.id) === b.dataset.id));
  };
}

function renderSettings() {
  if (!$("#size")) return;
  $("#size").value = prefs.size;
  $("#dim").value = prefs.dim || 0;
  choiceGroup($("#fonts"), FONTS, prefs.font,
    (f) => `<span style='font-family:${f.css.replace(/'/g, "")}'>${esc(f.name)}</span><small>${esc(f.note)}</small>`,
    (f) => setPref({ font: f.id }));
  choiceGroup($("#themes"), THEMES, prefs.theme, () => "A",
    (t) => setPref({ theme: t.id, bg: t.bg, fg: t.fg }));
  [...$("#themes").children].forEach((b, i) => {
    b.style.background = THEMES[i].bg; b.style.color = THEMES[i].fg;
    b.title = THEMES[i].name; b.setAttribute("aria-label", THEMES[i].name);
  });
  $("#custom-bg").value = prefs.bg;
  choiceGroup($("#lineheights"), LINEHEIGHTS, prefs.lh, (l) => esc(l.name), (l) => setPref({ lh: l.id }));
  choiceGroup($("#margins"), MARGINS, prefs.margin, (m) => esc(m.name), (m) => setPref({ margin: m.id }));
  $("#justify").checked = !!prefs.justify;
}

function mountSettings() {
  const aside = $("#settings");
  if (!aside) return;
  aside.innerHTML = SETTINGS_HTML;
  $("#size").addEventListener("input", (e) => setPref({ size: Number(e.target.value) }));
  $("#size-down").addEventListener("click", () => setPref({ size: Math.max(16, prefs.size - 1) }));
  $("#size-up").addEventListener("click", () => setPref({ size: Math.min(48, prefs.size + 1) }));
  $("#dim").addEventListener("input", (e) => setPref({ dim: Number(e.target.value) }));
  $("#custom-bg").addEventListener("input", (e) => {
    const bg = e.target.value;
    setPref({ theme: "eigene", bg, fg: luminance(bg) < 0.2 ? "#d0d5cf" : "#1f2428" });
  });
  $("#justify").addEventListener("change", (e) => setPref({ justify: e.target.checked }));
}

// ---------------------------------------------------------------------------
// Seitenblätter
// ---------------------------------------------------------------------------
const SHEETS = () => [...document.querySelectorAll(".sheet")].map((s) => s.id);

export function openSheet(id) {
  closeSheets();
  $(`#${id}`).hidden = false;
  $("#scrim").hidden = false;
  document.querySelectorAll(`[aria-controls="${id}"]`).forEach((b) => b.setAttribute("aria-expanded", "true"));
  $(`#${id} [data-close]`)?.focus();
}
export function closeSheets() {
  for (const id of SHEETS()) {
    $(`#${id}`).hidden = true;
    document.querySelectorAll(`[aria-controls="${id}"]`).forEach((b) => b.setAttribute("aria-expanded", "false"));
  }
  $("#scrim").hidden = true;
}

// ---------------------------------------------------------------------------
// Kopfleiste ein-/ausblenden, Fortschrittsbalken
// ---------------------------------------------------------------------------
export function scrollFrac() {
  const max = document.documentElement.scrollHeight - innerHeight;
  return max > 0 ? Math.min(1, Math.max(0, scrollY / max)) : 0;
}
export function showBar() { $("#bar")?.classList.remove("hidden"); }

export function initReaderChrome({ onScroll } = {}) {
  mountSettings();
  applyPrefs();
  document.querySelectorAll("[aria-controls]").forEach((b) => {
    const id = b.getAttribute("aria-controls");
    if ($(`#${id}`)?.classList.contains("sheet")) b.addEventListener("click", () => openSheet(id));
  });
  $("#scrim").addEventListener("click", closeSheets);
  document.addEventListener("click", (e) => { if (e.target.closest("[data-close]")) closeSheets(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeSheets(); });

  let lastY = 0;
  addEventListener("scroll", () => {
    const y = scrollY;
    const bar = $("#bar");
    if (bar && !bar.dataset.pinned) {
      if (y > lastY + 8 && y > 120) bar.classList.add("hidden");
      else if (y < lastY - 8) showBar();
    }
    lastY = y;
    const pb = $("#progress-bar");
    if (pb) pb.style.width = `${(scrollFrac() * 100).toFixed(1)}%`;
    onScroll?.();
  }, { passive: true });

  // Tippen in den Text blendet die Leiste ein oder aus
  $("#text")?.addEventListener("click", (e) => {
    if (e.target.closest("a, button") || getSelection().toString()) return;
    $("#bar")?.classList.toggle("hidden");
  });
}
