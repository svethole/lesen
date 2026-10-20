// Wikipedia-Lesemodus: Suche, Verlauf, Favoriten und Artikelansicht
import { $, esc, load, save, api, closeSheets, showBar, scrollFrac, initReaderChrome } from "/static/reader-common.js";

const state = {
  settings: null,
  lang: "de",
  query: "",
  results: [],
  nextOffset: null,
  article: null,          // {lang, title, …} des offenen Artikels
  tab: load("lesen.wikitab", "history"),
};

const ICON_REMOVE = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>';
const ICON_STAR = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z"/></svg>';

// ---------------------------------------------------------------------------
// Adressen und Navigation (Zurück-Taste des Handys funktioniert)
// ---------------------------------------------------------------------------
const articlePath = (lang, title) => `/wiki/${encodeURIComponent(lang)}/${encodeURIComponent(title.replace(/ /g, "_"))}`;
const sameTitle = (a, b) => a.replace(/_/g, " ").trim() === b.replace(/_/g, " ").trim();

function parsePath() {
  const m = location.pathname.match(/^\/wiki\/([^/]+)\/(.+)$/);
  if (!m) return null;
  return { lang: decodeURIComponent(m[1]), title: decodeURIComponent(m[2]).replace(/_/g, " ") };
}

function go(url) {
  flushPos();
  history.pushState(null, "", url);
  route();
}

function route() {
  closeSheets();
  const target = parsePath();
  if (target) showArticle(target.lang, target.title);
  else showHome();
}

document.addEventListener("click", (e) => {
  const a = e.target.closest("a[data-nav]");
  if (a && !e.metaKey && !e.ctrlKey) {
    e.preventDefault();
    go(a.getAttribute("href"));
  }
});
addEventListener("popstate", () => { flushPos(); route(); });

// ---------------------------------------------------------------------------
// Startseite
// ---------------------------------------------------------------------------
const rel = new Intl.RelativeTimeFormat("de", { numeric: "auto" });
function ago(iso) {
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "gerade eben";
  if (s < 3600) return rel.format(-Math.round(s / 60), "minute");
  if (s < 86400) return rel.format(-Math.round(s / 3600), "hour");
  if (s < 86400 * 30) return rel.format(-Math.round(s / 86400), "day");
  return new Date(iso).toLocaleDateString("de-DE", { day: "numeric", month: "short", year: "numeric" });
}

function langTag(code) {
  return code !== state.settings.default_lang ? `<span class="lang-tag">${esc(code)}</span>` : "";
}

function entry({ lang, title, text = "", meta = "", tool = "" }) {
  return `<li class="entry">
    <a class="entry-link" href="${articlePath(lang, title)}" data-nav>
      <span class="entry-title">${esc(title)}${langTag(lang)}</span>
      ${text ? `<span class="entry-text">${text}</span>` : ""}
      ${meta ? `<span class="entry-meta">${meta}</span>` : ""}
    </a>
    ${tool}
  </li>`;
}

function showHome() {
  state.article = null;
  $("#article").hidden = true;
  $("#home").hidden = false;
  document.title = "Wikipedia lesen";
  window.scrollTo(0, 0);
  renderResults();
  selectTab(state.tab);
}

function fillLangSelect() {
  const sel = $("#lang");
  sel.innerHTML = state.settings.languages.map((l) => `<option value="${esc(l.code)}">${esc(l.name)}</option>`).join("");
  const codes = state.settings.languages.map((l) => l.code);
  const remembered = load("lesen.wikilang", state.settings.default_lang);
  sel.value = codes.includes(remembered) ? remembered : state.settings.default_lang;
  state.lang = sel.value;
}

async function runSearch(append = false) {
  const meta = $("#results-meta");
  if (!append) {
    state.query = $("#q").value.trim();
    state.lang = $("#lang").value;
    state.results = [];
    state.nextOffset = 0;
    if (!state.query) return;
    meta.textContent = "Suche läuft …";
    $("#q").blur(); // Tastatur am Handy schließen
  }
  try {
    const data = await api(`/api/search?lang=${encodeURIComponent(state.lang)}&q=${encodeURIComponent(state.query)}&offset=${state.nextOffset || 0}`);
    state.results = state.results.concat(data.results.map((r) => ({ ...r, lang: state.lang })));
    state.nextOffset = data.next_offset;
    meta.textContent = data.total ? "" : `Keine Treffer für „${state.query}“.`;
    renderResults();
  } catch (e) {
    meta.textContent = `Die Suche hat nicht geklappt: ${e.message}`;
  }
}

function renderResults() {
  $("#results").innerHTML = state.results.map((r) =>
    entry({ lang: r.lang, title: r.title, text: r.description ? esc(r.description) : (r.snippet ? `${r.snippet} …` : "") })).join("");
  $("#more").hidden = state.nextOffset == null || !state.results.length;
}

$("#search-form").addEventListener("submit", (e) => { e.preventDefault(); runSearch(false); });
$("#lang").addEventListener("change", () => {
  save("lesen.wikilang", $("#lang").value);
  if ($("#q").value.trim()) runSearch(false);
});
$("#more").addEventListener("click", () => runSearch(true));
$("#random").addEventListener("click", async () => {
  try {
    const { title } = await api(`/api/random?lang=${encodeURIComponent($("#lang").value)}`);
    go(articlePath($("#lang").value, title));
  } catch (e) { $("#results-meta").textContent = e.message; }
});

// Verlauf und Favoriten
function selectTab(tab) {
  state.tab = tab;
  save("lesen.wikitab", tab);
  for (const t of ["history", "favorites"]) {
    $(`#tab-${t}`).setAttribute("aria-selected", String(t === tab));
    $(`#list-${t}`).hidden = t !== tab;
  }
  if (tab === "history") loadHistory(); else loadFavorites();
}
$("#tab-history").addEventListener("click", () => selectTab("history"));
$("#tab-favorites").addEventListener("click", () => selectTab("favorites"));

async function loadHistory() {
  const items = await api("/api/read/history").catch(() => []);
  $("#history").innerHTML = items.map((it) => {
    const pct = Math.round(it.frac * 100);
    const progress = pct >= 97 ? "gelesen" : pct > 2 ? `${pct} % gelesen` : "";
    return entry({
      lang: it.lang, title: it.title, text: esc(it.excerpt),
      meta: [ago(it.last_read), progress].filter(Boolean).join(", ") + (it.fav_at ? ' <span class="fav-mark" title="Favorit">★</span>' : ""),
      tool: `<button type="button" class="entry-tool" data-forget="${esc(it.lang)}|${esc(it.title)}" aria-label="„${esc(it.title)}“ aus dem Verlauf entfernen">${ICON_REMOVE}</button>`,
    });
  }).join("");
  $("#history-empty").hidden = items.length > 0;
  $("#history-clear").hidden = items.length === 0;
}

async function loadFavorites() {
  const items = await api("/api/read/favorites").catch(() => []);
  $("#favorites").innerHTML = items.map((it) => entry({
    lang: it.lang, title: it.title, text: esc(it.excerpt),
    meta: `gemerkt ${ago(it.fav_at)}`,
    tool: `<button type="button" class="entry-tool star" aria-pressed="true" data-unfav="${esc(it.lang)}|${esc(it.title)}" aria-label="„${esc(it.title)}“ aus den Favoriten entfernen">${ICON_STAR}</button>`,
  })).join("");
  $("#favorites-empty").hidden = items.length > 0;
}

$("#home").addEventListener("click", async (e) => {
  const forget = e.target.closest("[data-forget]");
  const unfav = e.target.closest("[data-unfav]");
  if (forget) {
    const [lang, title] = forget.dataset.forget.split("|");
    await api(`/api/read/history?lang=${encodeURIComponent(lang)}&title=${encodeURIComponent(title)}`, { method: "DELETE" });
    loadHistory();
  } else if (unfav) {
    const [lang, title] = unfav.dataset.unfav.split("|");
    await api("/api/read/state", { method: "POST", body: { lang, title, favorite: false } });
    loadFavorites();
  }
});
$("#history-clear").addEventListener("click", async () => {
  if (!confirm("Den ganzen Verlauf löschen? Favoriten bleiben erhalten.")) return;
  await api("/api/read/history", { method: "DELETE" });
  loadHistory();
});

// ---------------------------------------------------------------------------
// Artikel
// ---------------------------------------------------------------------------
let loadSeq = 0;

async function showArticle(lang, title) {
  const seq = ++loadSeq;
  $("#home").hidden = true;
  $("#article").hidden = false;
  $("#article-end").hidden = true;
  $("#article-title").textContent = title;
  $("#article-lang").textContent = langName(lang);
  $("#text").innerHTML = '<p class="loading">Artikel wird geladen …</p>';
  $("#text").lang = lang;
  hideResume();
  showBar();
  window.scrollTo(0, 0);

  let data;
  try {
    data = await api(`/api/read?lang=${encodeURIComponent(lang)}&title=${encodeURIComponent(title)}`);
  } catch (e) {
    if (seq !== loadSeq) return;
    $("#text").innerHTML = e.status === 404
      ? `<h1>${esc(title)}</h1><p class="loading">Diesen Artikel gibt es in der Wikipedia (${esc(langName(lang))}) nicht.</p><p class="loading"><a href="/wiki" data-nav>Zur Suche</a></p>`
      : `<p class="loading">Der Artikel konnte nicht geladen werden: ${esc(e.message)}</p><p class="loading"><a href="${articlePath(lang, title)}" data-nav>Nochmal versuchen</a></p>`;
    return;
  }
  if (seq !== loadSeq) return;
  state.article = data;
  // Weiterleitungen: Adresse auf den richtigen Titel umschreiben
  if (!sameTitle(data.title, title)) history.replaceState(null, "", articlePath(lang, data.title));

  document.title = `${data.title} – Wikipedia lesen`;
  $("#article-title").textContent = data.title;
  $("#text").innerHTML = `<h1>${esc(data.title)}</h1>${data.html}`;
  renderFav();
  renderToc();
  renderEnd();
  $("#article-end").hidden = false;

  if (data.frac > 0.03 && data.frac < 0.97) {
    window.scrollTo(0, data.frac * (document.documentElement.scrollHeight - innerHeight));
    showResume(data.frac);
  }
}

function langName(code) {
  return state.settings?.languages.find((l) => l.code === code)?.name || code;
}

// Links im Artikel bleiben im Lesemodus
$("#text").addEventListener("click", (e) => {
  const a = e.target.closest("a[data-wiki]");
  if (!a) return;
  e.preventDefault();
  if (state.article && sameTitle(a.dataset.wiki, state.article.title)) return;
  go(articlePath(state.article?.lang || state.lang, a.dataset.wiki));
});

// Favorit
function renderFav() {
  const on = !!state.article?.favorite;
  $("#fav").setAttribute("aria-pressed", String(on));
  $("#fav").setAttribute("aria-label", on ? "Aus den Favoriten entfernen" : "Als Favorit merken");
}
$("#fav").addEventListener("click", async () => {
  const a = state.article;
  if (!a) return;
  a.favorite = !a.favorite;
  renderFav();
  renderEnd();
  try {
    const res = await api("/api/read/state", { method: "POST", body: { lang: a.lang, title: a.title, favorite: a.favorite } });
    a.favorite = res.favorite;
  } catch { a.favorite = !a.favorite; }
  renderFav();
  renderEnd();
});

// Sammelband (teilt sich den Speicher mit der Hauptseite)
const stack = () => load("lesen.stack", []);
const inStack = (a) => stack().some((s) => s.lang === a.lang && sameTitle(s.title, a.title));
function toggleStack() {
  const a = state.article;
  if (!a) return;
  const list = stack();
  if (inStack(a)) save("lesen.stack", list.filter((s) => !(s.lang === a.lang && sameTitle(s.title, a.title))));
  else save("lesen.stack", [...list, { lang: a.lang, title: a.title }]);
  renderToc();
  renderEnd();
}

// Inhaltsverzeichnis, Sprachen, Aktionen
function renderToc() {
  const a = state.article;
  const secs = a.sections.filter((s) => s.level <= 3);
  $("#toc-list").innerHTML = `<li><a href="#" data-top>${esc(a.title)}</a></li>` + secs.map((s) =>
    `<li class="lvl${s.level}"><a href="#${esc(s.id)}" data-section="${esc(s.id)}">${esc(s.title)}</a></li>`).join("");
  $("#toc-langs").innerHTML = a.langlinks.length ? `
    <h3>In anderen Sprachen lesen</h3>
    <ul class="langs">${a.langlinks.map((l) => `
      <li><a href="${articlePath(l.lang, l.title)}" data-nav lang="${esc(l.lang)}">
        <span>${esc(l.autonym)}</span><small>${esc(l.title)}</small></a></li>`).join("")}
    </ul>` : "";
  $("#toc-actions").innerHTML = `
    <button type="button" class="pill-btn" data-stack>${inStack(a) ? "Aus dem Sammelband nehmen" : "In den Sammelband fürs ePub"}</button>
    <a class="pill-btn quiet" href="${esc(a.url)}" target="_blank" rel="noopener">Auf Wikipedia öffnen</a>`;
}

function renderEnd() {
  const a = state.article;
  if (!a) return;
  $("#article-end").innerHTML = `
    <button type="button" class="pill-btn" data-fav-end aria-pressed="${a.favorite}">${a.favorite ? "★ Favorit" : "☆ Als Favorit merken"}</button>
    <button type="button" class="pill-btn" data-stack>${inStack(a) ? "Im Sammelband ✓" : "In den Sammelband"}</button>
    <a class="pill-btn quiet" href="/wiki" data-nav>Neuer Artikel</a>
    <p class="license">Text aus der Wikipedia (<a href="${esc(a.url)}" target="_blank" rel="noopener">Original und Autoren</a>), Lizenz CC BY-SA 4.0.</p>`;
}

document.addEventListener("click", (e) => {
  if (e.target.closest("[data-stack]")) { toggleStack(); return; }
  if (e.target.closest("[data-fav-end]")) { $("#fav").click(); return; }
  const top = e.target.closest("#toc [data-top]");
  const sec = e.target.closest("#toc [data-section]");
  if (top || sec) {
    e.preventDefault();
    closeSheets();
    if (top) window.scrollTo(0, 0);
    else document.getElementById(sec.dataset.section)?.scrollIntoView();
    showBar();
  }
});

// ---------------------------------------------------------------------------
// Leseposition (auf dem Server, damit Handy und Rechner sie teilen)
// ---------------------------------------------------------------------------
let posTimer = null;
function queuePos() {
  if (!state.article) return;
  clearTimeout(posTimer);
  posTimer = setTimeout(flushPos, 1500);
}
function flushPos() {
  clearTimeout(posTimer);
  posTimer = null;
  const a = state.article;
  if (!a || $("#article").hidden) return;
  const frac = scrollFrac();
  if (Math.abs(frac - (a.frac || 0)) < 0.005) return;
  a.frac = frac;
  fetch("/api/read/state", {
    method: "POST", keepalive: true, headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ lang: a.lang, title: a.title, frac }),
  }).catch(() => {});
}
document.addEventListener("visibilitychange", () => { if (document.hidden) flushPos(); });
addEventListener("pagehide", flushPos);

// „Weiter, wo Du aufgehört hast“
let resumeTimer;
function showResume(frac) {
  const box = $("#resume");
  box.innerHTML = `<span>Weiter bei ${Math.round(frac * 100)} %</span><button type="button" id="resume-top">Zum Anfang</button>`;
  box.hidden = false;
  $("#resume-top").onclick = () => { window.scrollTo(0, 0); hideResume(); };
  clearTimeout(resumeTimer);
  resumeTimer = setTimeout(hideResume, 6000);
}
function hideResume() { $("#resume").hidden = true; }

// ---------------------------------------------------------------------------
// Start
// ---------------------------------------------------------------------------
(async function init() {
  initReaderChrome({ onScroll: queuePos });
  try {
    state.settings = await api("/api/settings");
  } catch (e) {
    state.settings = { languages: [{ code: "de", name: "Deutsch" }], default_lang: "de" };
  }
  fillLangSelect();
  route();
})();
