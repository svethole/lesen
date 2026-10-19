// Lesen – Suche, Sammelband, Bibliothek, Einstellungen
const $ = (sel, root = document) => root.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const keyOf = (a) => `${a.lang}|${a.title}`;

const store = {
  get(k, fallback) { try { const v = localStorage.getItem("lesen." + k); return v === null ? fallback : JSON.parse(v); } catch { return fallback; } },
  set(k, v) { try { localStorage.setItem("lesen." + k, JSON.stringify(v)); } catch { /* egal */ } },
};

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: opts.body ? { "Content-Type": "application/json" } : {},
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  let data = null;
  try { data = await res.json(); } catch { /* kein JSON */ }
  if (!res.ok) throw new Error((data && data.detail) || `Fehler ${res.status}`);
  return data;
}

const ICONS = {
  up: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 15l6-6 6 6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  down: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 9l6 6 6-6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  remove: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
};

// ---------------------------------------------------------------------------
// Zustand
// ---------------------------------------------------------------------------
const state = {
  settings: null,
  query: "",
  lang: "de",
  results: [],
  nextOffset: null,
  marked: new Map(),               // key -> {lang, title}
  stack: store.get("stack", []),   // [{lang, title}]
};

function langName(code) {
  const l = state.settings?.languages.find((x) => x.code === code);
  return l ? l.name : code;
}

// ---------------------------------------------------------------------------
// Hinweise
// ---------------------------------------------------------------------------
let toastTimer;
function toast(html, { error = false, ms = 4000 } = {}) {
  const t = $("#toast");
  t.innerHTML = html;
  t.classList.toggle("error", error);
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, ms);
}

// ---------------------------------------------------------------------------
// Ansichten
// ---------------------------------------------------------------------------
const VIEWS = { "#/suche": "search", "#/bibliothek": "library", "#/einstellungen": "settings" };

function route() {
  const view = VIEWS[location.hash] || "search";
  for (const v of ["search", "library", "settings"]) $(`#view-${v}`).hidden = v !== view;
  document.querySelectorAll(".tabs a").forEach((a) => {
    if (a.dataset.view === view) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
  $("#layout").classList.toggle("no-stack", view !== "search");
  $("#pickbar").hidden = view !== "search" || state.marked.size === 0;
  if (view === "library") loadLibrary();
  if (view === "settings") renderSettings();
  if (view === "search") setTimeout(() => $("#q").focus({ preventScroll: true }), 0);
}

// ---------------------------------------------------------------------------
// Suche
// ---------------------------------------------------------------------------
function fillLangSelect() {
  const sel = $("#lang");
  const current = sel.value || state.lang;
  sel.innerHTML = state.settings.languages.map((l) => `<option value="${esc(l.code)}">${esc(l.name)}</option>`).join("");
  const codes = state.settings.languages.map((l) => l.code);
  sel.value = codes.includes(current) ? current : state.settings.default_lang;
  state.lang = sel.value;
}

async function runSearch(append = false) {
  const meta = $("#results-meta");
  if (!append) {
    state.query = $("#q").value.trim();
    state.lang = $("#lang").value;
    state.nextOffset = 0;
    state.results = [];
    if (!state.query) return;
    meta.innerHTML = '<span class="spinner"></span>Suche läuft …';
  }
  $("#more").disabled = true;
  try {
    const data = await api(`/api/search?lang=${encodeURIComponent(state.lang)}&q=${encodeURIComponent(state.query)}&offset=${state.nextOffset || 0}`);
    state.results = state.results.concat(data.results.map((r) => ({ ...r, lang: state.lang })));
    state.nextOffset = data.next_offset;
    $("#search-empty").hidden = true;
    meta.textContent = data.total
      ? `${data.total.toLocaleString("de-DE")} Treffer in der Wikipedia (${langName(state.lang)})`
      : `Keine Treffer für „${state.query}“. Probier einen anderen Begriff oder eine andere Sprache.`;
    renderResults();
  } catch (e) {
    meta.textContent = `Die Suche hat nicht geklappt: ${e.message}`;
  } finally {
    $("#more").disabled = false;
  }
}

function inStack(a) { return state.stack.some((s) => keyOf(s) === keyOf(a)); }

function renderResults() {
  const ul = $("#results");
  ul.innerHTML = state.results.map((r, i) => {
    const key = keyOf(r);
    const taken = inStack(r);
    const marked = state.marked.has(key);
    return `<li class="result${marked ? " is-marked" : ""}" data-i="${i}">
      <input type="checkbox" class="mark" aria-label="${esc(r.title)} markieren" ${marked || taken ? "checked" : ""} ${taken ? "disabled" : ""}>
      <div>
        <button type="button" class="result-title">${esc(r.title)}</button>${taken ? '<span class="in-stack">im Sammelband</span>' : ""}
        ${r.description ? `<p class="result-desc">${esc(r.description)}</p>` : ""}
        ${r.snippet ? `<p class="result-snippet">${r.snippet} …</p>` : ""}
      </div>
      ${r.thumb ? `<img class="result-thumb" src="${esc(r.thumb)}" alt="" loading="lazy">` : "<span></span>"}
    </li>`;
  }).join("");
  $("#more").hidden = state.nextOffset == null || !state.results.length;
  updatePickbar();
}

function updatePickbar() {
  const n = state.marked.size;
  $("#pickbar").hidden = n === 0 || VIEWS[location.hash] && VIEWS[location.hash] !== "search";
  $("#pick-count").innerHTML = `${n} <span class="long">Artikel </span>markiert`;
}

$("#results").addEventListener("click", (e) => {
  const li = e.target.closest(".result");
  if (!li) return;
  const r = state.results[+li.dataset.i];
  if (e.target.closest(".result-title")) {
    openPreview(r.lang, r.title);
  }
});
$("#results").addEventListener("change", (e) => {
  if (!e.target.classList.contains("mark")) return;
  const li = e.target.closest(".result");
  const r = state.results[+li.dataset.i];
  if (e.target.checked) state.marked.set(keyOf(r), { lang: r.lang, title: r.title });
  else state.marked.delete(keyOf(r));
  li.classList.toggle("is-marked", e.target.checked);
  updatePickbar();
});

$("#search-form").addEventListener("submit", (e) => { e.preventDefault(); runSearch(false); });
$("#lang").addEventListener("change", () => { if ($("#q").value.trim()) runSearch(false); });
$("#more").addEventListener("click", () => runSearch(true));

$("#pick-clear").addEventListener("click", () => { state.marked.clear(); renderResults(); });
$("#pick-take").addEventListener("click", () => {
  const items = [...state.marked.values()].filter((a) => !inStack(a));
  addToStack(items);
  state.marked.clear();
  renderResults();
  toast(items.length === 1 ? `„${esc(items[0].title)}“ ist im Sammelband.` : `${items.length} Artikel sind im Sammelband.`);
});

// ---------------------------------------------------------------------------
// Sammelband
// ---------------------------------------------------------------------------
function saveStack() { store.set("stack", state.stack); }

function addToStack(items) {
  for (const it of items) if (!inStack(it)) state.stack.push({ lang: it.lang, title: it.title });
  saveStack();
  renderStack();
}

function removeFromStack(a) {
  state.stack = state.stack.filter((s) => keyOf(s) !== keyOf(a));
  saveStack();
  renderStack();
  renderResults();
}

function renderStack() {
  const n = state.stack.length;
  const def = state.settings?.default_lang;
  $("#stack-list").innerHTML = state.stack.map((a, i) => `
    <li class="stack-item" data-i="${i}">
      <span><button type="button" class="title">${esc(a.title)}</button>${a.lang !== def ? `<span class="lang-tag" title="${esc(langName(a.lang))}">${esc(a.lang)}</span>` : ""}</span>
      <span class="tools">
        <button type="button" class="btn quiet icon" data-act="up" aria-label="„${esc(a.title)}“ nach oben" ${i === 0 ? "disabled" : ""}>${ICONS.up}</button>
        <button type="button" class="btn quiet icon" data-act="down" aria-label="„${esc(a.title)}“ nach unten" ${i === n - 1 ? "disabled" : ""}>${ICONS.down}</button>
        <button type="button" class="btn quiet icon" data-act="remove" aria-label="„${esc(a.title)}“ entfernen">${ICONS.remove}</button>
      </span>
    </li>`).join("");
  $("#stack-empty").hidden = n > 0;
  $("#build").disabled = n === 0 || building;
  $("#stack-count").textContent = n === 0 ? "leer" : n === 1 ? "1 Artikel" : `${n} Artikel`;
}

$("#stack-list").addEventListener("click", (e) => {
  const li = e.target.closest(".stack-item");
  if (!li) return;
  const i = +li.dataset.i;
  const a = state.stack[i];
  if (e.target.closest(".title")) return openPreview(a.lang, a.title);
  const act = e.target.closest("[data-act]")?.dataset.act;
  if (act === "remove") return removeFromStack(a);
  if (act === "up" && i > 0) [state.stack[i - 1], state.stack[i]] = [state.stack[i], state.stack[i - 1]];
  if (act === "down" && i < state.stack.length - 1) [state.stack[i + 1], state.stack[i]] = [state.stack[i], state.stack[i + 1]];
  saveStack();
  renderStack();
  const btn = $(`#stack-list [data-i="${act === "up" ? i - 1 : i + 1}"] [data-act="${act}"]`);
  if (btn && !btn.disabled) btn.focus();
});

$("#stack-handle").addEventListener("click", () => {
  const open = $("#stack").classList.toggle("open");
  $("#stack-handle").setAttribute("aria-expanded", String(open));
});

$("#book-title").value = store.get("title", "");
$("#book-title").addEventListener("input", (e) => store.set("title", e.target.value));
$("#with-images").checked = store.get("images", true);
$("#with-images").addEventListener("change", (e) => store.set("images", e.target.checked));

// ePub erstellen
let building = false;
$("#build").addEventListener("click", async () => {
  if (!state.stack.length || building) return;
  building = true;
  renderStack();
  const box = $("#build-status");
  box.hidden = false;
  box.classList.remove("error");
  box.innerHTML = '<p><span class="spinner"></span><span id="build-msg">Starte …</span></p>';
  try {
    const { job_id } = await api("/api/books", {
      method: "POST",
      body: { title: $("#book-title").value, articles: state.stack, images: $("#with-images").checked },
    });
    let job;
    for (;;) {
      await new Promise((r) => setTimeout(r, 900));
      job = await api(`/api/jobs/${job_id}`);
      const msg = $("#build-msg");
      if (msg) msg.textContent = job.message;
      if (job.status !== "running") break;
    }
    if (job.status === "error") throw new Error(job.message);
    const book = await api(`/api/books/${job.book_id}`);
    box.innerHTML = `
      <p><b>„${esc(book.title)}“ ist fertig.</b></p>
      ${job.warnings.map((w) => `<p class="help">${esc(w)}</p>`).join("")}
      <div class="actions">
        <a class="btn" href="/api/books/${book.id}/download">Herunterladen</a>
        <button type="button" class="btn" data-send="${book.id}">An den Reader senden</button>
        <a class="btn" href="/lesen/${book.id}">Lesen</a>
      </div>
      <div class="actions"><button type="button" class="btn quiet" id="stack-clear">Sammelband leeren</button></div>`;
  } catch (e) {
    box.classList.add("error");
    box.innerHTML = `<p>Das ePub konnte nicht erstellt werden: ${esc(e.message)}</p>`;
  } finally {
    building = false;
    renderStack();
  }
});

$("#build-status").addEventListener("click", (e) => {
  if (e.target.id === "stack-clear") {
    state.stack = [];
    saveStack();
    $("#book-title").value = "";
    store.set("title", "");
    $("#build-status").hidden = true;
    renderStack();
    renderResults();
  }
});

// Senden (in Sammelband-Status und Bibliothek)
document.addEventListener("click", async (e) => {
  const btn = e.target.closest("[data-send]");
  if (!btn) return;
  btn.disabled = true;
  const label = btn.textContent;
  btn.textContent = "Wird gesendet …";
  try {
    const res = await api(`/api/books/${btn.dataset.send}/send`, { method: "POST" });
    toast(`Gesendet an ${esc(res.to)}.`);
    btn.textContent = "Gesendet";
    if (!$("#view-library").hidden) loadLibrary();
  } catch (err) {
    toast(esc(err.message), { error: true, ms: 7000 });
    btn.textContent = label;
    btn.disabled = false;
  }
});

// ---------------------------------------------------------------------------
// Vorschau
// ---------------------------------------------------------------------------
const preview = { history: [], current: null };

async function openPreview(lang, title, { push = false, back = false } = {}) {
  const dlg = $("#preview");
  if (push && preview.current) preview.history.push({ ...preview.current });
  else if (!back) preview.history = [];
  preview.current = { lang, title };
  $("#preview-back").hidden = preview.history.length === 0;
  $("#preview-title").textContent = title;
  $("#preview-source").href = `https://${lang}.wikipedia.org/wiki/${encodeURIComponent(title.replace(/ /g, "_"))}`;
  $("#preview-body").innerHTML = '<p class="loading"><span class="spinner"></span>Artikel wird geladen …</p>';
  $("#preview-body").scrollTop = 0;
  updatePreviewToggle();
  if (!dlg.open) dlg.showModal();
  try {
    const data = await api(`/api/preview?lang=${encodeURIComponent(lang)}&title=${encodeURIComponent(title)}`);
    if (preview.current.title !== title) return;
    preview.current.title = data.title; // Weiterleitungen auflösen
    $("#preview-title").textContent = data.title;
    $("#preview-source").href = data.url;
    $("#preview-body").innerHTML = data.html || '<p class="loading">Der Artikel ist nach der Bereinigung leer.</p>';
    $("#preview-body").lang = lang;
    updatePreviewToggle();
  } catch (e) {
    $("#preview-body").innerHTML = `<p class="loading">Die Vorschau konnte nicht geladen werden: ${esc(e.message)}</p>`;
  }
}

function updatePreviewToggle() {
  const btn = $("#preview-toggle");
  const taken = preview.current && inStack(preview.current);
  btn.textContent = taken ? "Aus dem Sammelband entfernen" : "In den Sammelband";
  btn.classList.toggle("primary", !taken);
}

$("#preview-toggle").addEventListener("click", () => {
  const a = preview.current;
  if (!a) return;
  if (inStack(a)) removeFromStack(a);
  else { addToStack([a]); state.marked.delete(keyOf(a)); renderResults(); }
  updatePreviewToggle();
});
$("#preview-close").addEventListener("click", () => $("#preview").close());
$("#preview-back").addEventListener("click", () => {
  const prev = preview.history.pop();
  if (prev) openPreview(prev.lang, prev.title, { back: true });
});
$("#preview-body").addEventListener("click", (e) => {
  const a = e.target.closest("a[data-wiki]");
  if (!a) return;
  e.preventDefault();
  openPreview(preview.current.lang, a.dataset.wiki, { push: true });
});
$("#preview").addEventListener("click", (e) => { if (e.target === $("#preview")) $("#preview").close(); });

// ---------------------------------------------------------------------------
// Bibliothek
// ---------------------------------------------------------------------------
const dateFmt = new Intl.DateTimeFormat("de-DE", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
const sizeFmt = (b) => b > 1048576 ? `${(b / 1048576).toLocaleString("de-DE", { maximumFractionDigits: 1 })} MB` : `${Math.max(1, Math.round(b / 1024))} KB`;

async function loadLibrary() {
  let books;
  try { books = await api("/api/books"); } catch (e) { toast(esc(e.message), { error: true }); return; }
  $("#library-empty").hidden = books.length > 0;
  $("#shelf").innerHTML = books.map((b) => {
    const n = b.chapters.length;
    return `<li class="book" data-id="${b.id}">
      <a class="book-cover" href="/lesen/${b.id}" aria-label="„${esc(b.title)}“ lesen">
        <img src="/api/books/${b.id}/images/cover.jpg" alt="" loading="lazy">
      </a>
      <h3>${esc(b.title)}</h3>
      <p class="meta">${dateFmt.format(new Date(b.created_at))}<br>${n === 1 ? "1 Artikel" : `${n} Artikel`}, ${sizeFmt(b.size)}</p>
      ${b.sent_at ? `<p class="sent">An den Reader gesendet am ${dateFmt.format(new Date(b.sent_at))}</p>` : ""}
      <div class="actions">
        <a class="btn primary" href="/lesen/${b.id}">Lesen</a>
        <a class="btn" href="/api/books/${b.id}/download">Herunterladen</a>
        <button type="button" class="btn" data-send="${b.id}">An den Reader senden</button>
      </div>
      <details>
        <summary>Inhalt</summary>
        <ol>${b.chapters.map((c) => `<li>${esc(c.title)}</li>`).join("")}</ol>
        <button type="button" class="btn quiet danger" data-delete="${b.id}">ePub löschen</button>
      </details>
    </li>`;
  }).join("");
}

$("#shelf").addEventListener("click", async (e) => {
  const del = e.target.closest("[data-delete]");
  if (!del) return;
  const title = del.closest(".book").querySelector("h3").textContent;
  if (!confirm(`„${title}“ endgültig löschen?`)) return;
  try {
    await api(`/api/books/${del.dataset.delete}`, { method: "DELETE" });
    toast(`„${esc(title)}“ gelöscht.`);
    loadLibrary();
  } catch (err) { toast(esc(err.message), { error: true }); }
});

// ---------------------------------------------------------------------------
// Einstellungen
// ---------------------------------------------------------------------------
function langRow(l, isDefault) {
  return `<li class="lang-row">
    <input type="text" class="code" value="${esc(l.code)}" aria-label="Sprachcode" maxlength="15" required>
    <input type="text" class="name" value="${esc(l.name)}" aria-label="Name der Sprache" required>
    <label class="default"><input type="radio" name="default-lang" ${isDefault ? "checked" : ""}> Standard</label>
    <button type="button" class="btn quiet icon remove" aria-label="Sprache entfernen">${ICONS.remove}</button>
  </li>`;
}

function renderSettings() {
  const s = state.settings;
  $("#lang-editor").innerHTML = s.languages.map((l) => langRow(l, l.code === s.default_lang)).join("");
  $("#reader-email").value = s.reader_email || "";
  $("#smtp-status").innerHTML = s.smtp_configured
    ? `Gesendet wird von <b>${esc(s.smtp_sender)}</b>. Diese Adresse muss beim Reader als erlaubter Absender eingetragen sein (bei PocketBook in der PocketBook Cloud unter „Send-to-PocketBook“).`
    : "Der Mailversand ist auf dem Server noch nicht eingerichtet. Trag dazu die SMTP-Daten im Abschnitt [smtp] der config.toml ein.";
}

$("#lang-add").addEventListener("click", () => {
  $("#lang-editor").insertAdjacentHTML("beforeend", langRow({ code: "", name: "" }, false));
  $("#lang-editor .lang-row:last-child .code").focus();
});
$("#lang-editor").addEventListener("click", (e) => {
  if (e.target.closest(".remove")) e.target.closest(".lang-row").remove();
});

$("#settings-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const rows = [...document.querySelectorAll("#lang-editor .lang-row")];
  const languages = rows.map((r) => ({ code: $(".code", r).value.trim().toLowerCase(), name: $(".name", r).value.trim() }))
    .filter((l) => l.code);
  const defRow = rows.find((r) => $('input[type="radio"]', r).checked);
  const default_lang = defRow ? $(".code", defRow).value.trim().toLowerCase() : languages[0]?.code;
  try {
    state.settings = await api("/api/settings", {
      method: "PUT",
      body: { languages, default_lang, reader_email: $("#reader-email").value.trim() },
    });
    fillLangSelect();
    renderSettings();
    renderStack();
    toast("Einstellungen gespeichert.");
  } catch (err) { toast(esc(err.message), { error: true }); }
});

// ---------------------------------------------------------------------------
// Start
// ---------------------------------------------------------------------------
(async function init() {
  try {
    state.settings = await api("/api/settings");
  } catch (e) {
    toast(`Der Server antwortet nicht: ${esc(e.message)}`, { error: true, ms: 10000 });
    return;
  }
  state.lang = state.settings.default_lang;
  fillLangSelect();
  renderStack();
  window.addEventListener("hashchange", route);
  route();
})();
