// mia-2d-patch.js · no toca tu main.js: captura la respuesta y mejora lo que se pinta
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const FILE = /\.(pdf|xlsx?|csv|docx?|pptx?|zip)(\?|#|$)/i;
let last = null;

// 1) Captura el JSON de /api/mia/* (también disponible en consola como miaLast)
const _fetch = window.fetch.bind(window);
window.fetch = async (...a) => {
  const r = await _fetch(...a);
  try {
    if (String(a[0]?.url || a[0]).includes("/api/mia/")) {
      const ct = r.headers.get("content-type") || "", c = r.clone();
      if (ct.includes("ndjson")) c.text().then((t) => {
        const ev = t.split("\n").map((l) => { try { return JSON.parse(l); } catch { return null; } }).filter((e) => e?.type === "result").pop();
        if (ev?.payload) { last = ev.payload; window.miaLast = last; }
      }).catch(() => {});
      else if (ct.includes("json")) c.json().then((j) => { last = j; window.miaLast = j; }).catch(() => {});
    }
  } catch {}
  return r;
};

const toast = (t) => {
  const d = Object.assign(document.createElement("div"), { className: "p-toast", textContent: t });
  document.body.appendChild(d); setTimeout(() => d.remove(), 2400);
};
const save = (name, mime, body) => {
  const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(new Blob([body], { type: mime })), download: name });
  document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 2000);
};
const day = () => new Date().toISOString().slice(0, 10);
const pretty = (k) => String(k).replace(/_/g, " ").replace(/([a-záéíóú])([A-Z])/g, "$1 $2").replace(/^./, (c) => c.toUpperCase());
const fmt = (v) => {
  if (v === true) return "Sí"; if (v === false) return "No";
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "number") return v.toLocaleString("es-ES", { maximumFractionDigits: 2 });
  const m = String(v).match(/^(\d{4})-(\d{2})-(\d{2})(T.*)?$/);
  return m ? `${m[3]}/${m[2]}/${m[1]}` : String(v);
};

// 2) Tabla premium con filtro, orden, copiar, CSV y Excel
function buildTable(head, rows) {
  const w = document.createElement("div");
  w.className = "dt";
  w.innerHTML = `<div class="dt-bar"><span class="dt-count"></span>${rows.length > 6 ? '<input class="dt-filter" type="search" placeholder="Filtrar filas…">' : ""}<span class="dt-actions"><button data-a="copy">Copiar</button><button data-a="csv">CSV</button><button data-a="xls">Excel</button></span></div><div class="dt-scroll"><table><thead><tr>${head.map((h) => `<th>${esc(h)}</th>`).join("")}</tr></thead><tbody>${rows.map((r) => `<tr>${head.map((_, i) => `<td>${esc(r[i])}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  const tb = w.querySelector("tbody"), body = [...tb.rows], count = w.querySelector(".dt-count");
  const shown = () => body.filter((r) => !r.hidden).map((r) => [...r.cells].map((c) => c.textContent.trim()));
  const refresh = () => { const n = shown().length; count.textContent = `${n} ${n === 1 ? "fila" : "filas"}`; };
  refresh();
  w.querySelector(".dt-filter")?.addEventListener("input", (e) => {
    const q = e.target.value.toLowerCase();
    body.forEach((r) => (r.hidden = !!q && !r.textContent.toLowerCase().includes(q))); refresh();
  });
  w.querySelectorAll("th").forEach((th, c) => th.addEventListener("click", () => {
    const d = th.dataset.dir === "asc" ? "desc" : "asc";
    w.querySelectorAll("th").forEach((x) => delete x.dataset.dir); th.dataset.dir = d;
    [...body].sort((a, b) => a.cells[c].textContent.localeCompare(b.cells[c].textContent, "es", { numeric: true }) * (d === "asc" ? 1 : -1)).forEach((r) => tb.appendChild(r));
  }));
  bindExport(w.querySelector(".dt-actions"), () => head, shown);
  return w;
}

function bindExport(box, getHead, getRows) {
  box.addEventListener("click", (e) => {
    const a = e.target.dataset.a; if (!a) return;
    const head = getHead(), rows = getRows();
    if (a === "copy") navigator.clipboard?.writeText([head, ...rows].map((r) => r.join("\t")).join("\n")).then(() => toast("Tabla copiada"));
    else if (a === "csv") { save(`mIA_listado_${day()}.csv`, "text/csv;charset=utf-8", "\ufeff" + [head, ...rows].map((r) => r.map((v) => `"${v.replace(/"/g, '""')}"`).join(";")).join("\r\n")); toast(`CSV descargado · ${rows.length} filas`); }
    else { save(`mIA_listado_${day()}.xls`, "application/vnd.ms-excel", `<html><head><meta charset="utf-8"></head><body><table><tr>${head.map((h) => `<th>${esc(h)}</th>`).join("")}</tr>${rows.map((r) => `<tr>${r.map((v) => `<td>${esc(v)}</td>`).join("")}</tr>`).join("")}</table></body></html>`); toast(`Excel descargado · ${rows.length} filas`); }
  });
}

// 3) Tablas markdown que llegan como líneas de texto "| a | b |"
function mdTables(root) {
  root.querySelectorAll(".mia-answer").forEach((box) => {
    const kids = [...box.children];
    for (let i = 0; i < kids.length; i++) {
      if (!kids[i].textContent.trim().startsWith("|")) continue;
      let j = i; while (j < kids.length && kids[j].textContent.trim().startsWith("|")) j++;
      const run = kids.slice(i, j).map((k) => k.textContent.trim());
      if (run.length >= 2 && /^\|?[\s:|-]+\|?$/.test(run[1])) {
        const cells = (l) => l.replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
        const head = cells(run[0]);
        kids[i].replaceWith(buildTable(head, run.slice(2).map((l) => head.map((_, k) => cells(l)[k] ?? ""))));
        kids.slice(i + 1, j).forEach((k) => k.remove());
      }
      i = j - 1;
    }
  });
}

// 4) Paneles de visualización vacíos (Personas, Ficha 360…): render genérico del payload
const isObj = (v) => v && typeof v === "object" && !Array.isArray(v);
function fromArray(d, cols) {
  const keys = cols?.length ? cols.map((c) => c.key ?? c) : [...new Set(d.flatMap((x) => Object.keys(x)))].filter((k) => !/^(id|_)/i.test(k));
  const labels = cols?.length ? cols.map((c) => c.label ?? pretty(c.key ?? c)) : keys.map(pretty);
  return buildTable(labels, d.map((x) => keys.map((k) => fmt(x[k]))));
}
function fromValue(v, depth = 0) {
  const box = document.createElement("div"); box.className = "ficha";
  if (Array.isArray(v)) {
    if (v.length && isObj(v[0])) box.appendChild(fromArray(v));
    else box.innerHTML = `<div class="chips">${v.map((x) => `<span>${esc(fmt(x))}</span>`).join("") || "—"}</div>`;
    return box;
  }
  const simple = Object.entries(v).filter(([, x]) => !x || typeof x !== "object");
  if (simple.length) {
    const g = document.createElement("div"); g.className = "defs";
    g.innerHTML = simple.filter(([, x]) => x !== null && x !== "").map(([k, x]) => `<div><small>${esc(pretty(k))}</small><b>${esc(fmt(x))}</b></div>`).join("");
    box.appendChild(g);
  }
  Object.entries(v).filter(([, x]) => x && typeof x === "object" && (!Array.isArray(x) || x.length)).forEach(([k, x]) => {
    const s = document.createElement("section"); s.innerHTML = `<h5>${esc(pretty(k))}</h5>`;
    s.appendChild(depth < 2 ? fromValue(x, depth + 1) : Object.assign(document.createElement("pre"), { textContent: JSON.stringify(x, null, 1) }));
    box.appendChild(s);
  });
  return box;
}
function fillViz(row) {
  const list = last?.visualizations || last?.data?.visualizations || [];
  row.querySelectorAll(".viz").forEach((viz, i) => {
    const bars = viz.querySelector(".bars");
    if (!bars || bars.children.length) return;
    const v = list[i]; if (!v) return;
    const d = v.rows ?? v.data ?? v.items ?? v.payload ?? v.value ?? v.fields ?? v.ficha;
    if (d === undefined || d === null) return;
    bars.className = "viz-body";
    bars.replaceChildren(Array.isArray(d) && d.length && isObj(d[0]) ? fromArray(d, v.columns) : fromValue(isObj(d) ? d : { Valor: d }));
  });
}

// 5) Enlaces clicables + botones de descarga en las tablas ya existentes
function linkify(root) {
  const re = /\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)|(https?:\/\/[^\s<)]*[^\s<).,;:!?])/g;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, { acceptNode: (n) => (n.parentElement.closest("a,code,script,style") || !/https?:\/\//.test(n.data) ? 2 : 1) });
  const nodes = []; while (walker.nextNode()) nodes.push(walker.currentNode);
  nodes.forEach((n) => {
    const f = document.createDocumentFragment(); let p = 0, m;
    while ((m = re.exec(n.data))) {
      f.append(n.data.slice(p, m.index));
      const url = m[2] || m[3], file = url.match(FILE);
      const a = Object.assign(document.createElement("a"), { href: url, target: "_blank", rel: "noopener noreferrer", className: "lnk" + (file ? " lnk-file" : "") });
      let label = m[1]; if (!label) { try { const u = new URL(url); label = file ? decodeURIComponent(u.pathname.split("/").pop()) : u.hostname.replace(/^www\./, "") + (u.pathname.length > 1 ? "/…" : ""); } catch { label = url; } }
      a.textContent = label; if (file) a.dataset.ext = file[1].toUpperCase();
      f.append(a); p = m.index + m[0].length;
    }
    f.append(n.data.slice(p)); n.replaceWith(f);
  });
  root.querySelectorAll("a[href]").forEach((a) => { a.target = "_blank"; a.rel = "noopener noreferrer"; });
}
function exportOnGeneric(root) {
  root.querySelectorAll(".generic-table-panel:not([data-x])").forEach((p) => {
    p.dataset.x = 1;
    const box = Object.assign(document.createElement("span"), { className: "dt-actions", innerHTML: '<button data-a="csv">CSV</button><button data-a="xls">Excel</button>' });
    p.querySelector(".generic-table-head")?.appendChild(box);
    bindExport(box, () => [...p.querySelectorAll("th")].map((t) => t.textContent.trim()), () => [...p.querySelectorAll("tbody tr")].filter((r) => r.cells.length > 1).map((r) => [...r.cells].map((c) => c.textContent.trim())));
  });
}

// Listas con viñetas "Nombre, Departamento, fechas" -> tabla (cabeceras deducidas del contenido)
function listTables(root) {
  root.querySelectorAll(".mia-answer").forEach((box) => {
    const kids = [...box.children], dates = /\d{1,2}[-/]\d{1,2}|\d{4}/;
    for (let i = 0; i < kids.length; i++) {
      if (!kids[i].classList.contains("mia-answer-bullet")) continue;
      let j = i; while (j < kids.length && kids[j].classList.contains("mia-answer-bullet")) j++;
      const rows = kids.slice(i, j).map((k) => k.textContent.trim().split(/,\s+/));
      const freq = {}; rows.forEach((r) => (freq[r.length] = (freq[r.length] || 0) + 1));
      const n = +Object.entries(freq).sort((a, b) => b[1] - a[1])[0][0];
      if (rows.length >= 4 && n >= 2 && n <= 6) {
        const fix = rows.map((r) => (r.length > n ? [...r.slice(0, n - 1), r.slice(n - 1).join(", ")] : [...r, ...Array(n - r.length).fill("")]));
        const head = fix[0].map((_, c) => (c === 0 ? "Nombre" : c === n - 1 && fix.every((r) => dates.test(r[c])) ? "Periodo" : c === 1 ? "Departamento" : `Dato ${c + 1}`));
        kids[i].replaceWith(buildTable(head, fix));
        kids.slice(i + 1, j).forEach((k) => k.remove());
      }
      i = j - 1;
    }
  });
}

function process(row) {
  if (row.dataset.done) return; row.dataset.done = 1;
  mdTables(row); listTables(row); fillViz(row); linkify(row); exportOnGeneric(row);
  setTimeout(() => fillViz(row), 700);
}
const start = () => {
  const c = document.getElementById("conversation"); if (!c) return void setTimeout(start, 200);
  new MutationObserver((ms) => ms.forEach((m) => m.addedNodes.forEach((n) => n.classList?.contains("msg-row") && n.classList.contains("mia") && setTimeout(() => process(n), 120)))).observe(c, { childList: true });
};
start();
