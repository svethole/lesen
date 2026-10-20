// Lesemodus für erstellte ePubs
import { $, esc, load, save, api, closeSheets, showBar, scrollFrac, initReaderChrome } from "/static/reader-common.js";

const bookId = Number(location.pathname.split("/").filter(Boolean).pop());

// ---------------------------------------------------------------------------
// Buch und Kapitel
// ---------------------------------------------------------------------------
let book = null;
let current = -1;
const posKey = `lesen.pos.${bookId}`;

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
let saveTimer;
function savePos() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => save(posKey, { ch: current, frac: scrollFrac() }), 400);
}

// ---------------------------------------------------------------------------
// Start
// ---------------------------------------------------------------------------
(async function init() {
  initReaderChrome({ onScroll: savePos });
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
