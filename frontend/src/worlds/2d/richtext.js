// richtext.js · Markdown seguro + tablas premium (filtro, orden, copiar, CSV, Excel)
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const FILE_RE = /\.(pdf|xlsx?|csv|docx?|pptx?|zip|txt)(\?|#|$)/i;

function anchor(label, url) {
  const clean = url.replace(/&amp;/g, "&");
  if (!/^(https?:\/\/|mailto:|\/)/i.test(clean)) return label;
  const file = clean.match(FILE_RE);
  const badge = file ? `<b class="lnk-ext">${file[1].toUpperCase()}</b>` : "";
  return `<a class="lnk${file ? " lnk-file" : ""}" href="${esc(clean)}" target="_blank" rel="noopener noreferrer">${label}${badge}</a>`;
}

function shortUrl(u) {
  const clean = u.replace(/&amp;/g, "&");
  try {
    const x = new URL(clean, location.origin);
    const last = decodeURIComponent(x.pathname.split("/").filter(Boolean).pop() || "");
    return FILE_RE.test(clean) && last ? last : x.hostname.replace(/^www\./, "") + (x.pathname.length > 1 ? "/…" : "");
  } catch { return u; }
}

function inline(text) {
  const keep = [];
  const hold = (html) => `\u0000${keep.push(html) - 1}\u0000`;
  let s = esc(text)
    .replace(/`([^`]+)`/g, (_, c) => hold(`<code>${c}</code>`))
    .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_, l, u) => hold(anchor(l, u)))
    .replace(/(^|[\s(>])(https?:\/\/[^\s<)]*[^\s<).,;:!?])/g, (_, p, u) => p + hold(anchor(shortUrl(u), u)))
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[\s(])\*(?!\s)(.+?)\*(?=[\s).,;:]|$)/g, "$1<em>$2</em>");
  return s.replace(/\u0000(\d+)\u0000/g, (_, i) => keep[+i]);
}

const cells = (line) => line.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
const isSep = (l) => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(l || "");

export function renderMarkdown(src) {
  const lines = String(src ?? "").replace(/\r/g, "").split("\n");
  const out = [];
  for (let i = 0; i < lines.length; ) {
    const l = lines[i];
    if (!l.trim()) { i++; continue; }
    if (l.includes("|") && isSep(lines[i + 1])) {
      const head = cells(l);
      const rows = [];
      i += 2;
      while (i < lines.length && lines[i].includes("|") && lines[i].trim()) rows.push(cells(lines[i++]));
      out.push(`<table><thead><tr>${head.map((h) => `<th>${inline(h)}</th>`).join("")}</tr></thead><tbody>${rows
        .map((r) => `<tr>${head.map((_, k) => `<td>${inline(r[k] ?? "")}</td>`).join("")}</tr>`).join("")}</tbody></table>`);
      continue;
    }
    let m;
    if ((m = l.match(/^(#{1,4})\s+(.+)/))) { out.push(`<h4 class="md-h">${inline(m[2])}</h4>`); i++; continue; }
    if (/^\s*([-*_])\1{2,}\s*$/.test(l)) { out.push("<hr>"); i++; continue; }
    if (/^\s*>\s?/.test(l)) {
      const q = [];
      while (i < lines.length && /^\s*>\s?/.test(lines[i])) q.push(lines[i++].replace(/^\s*>\s?/, ""));
      out.push(`<blockquote>${inline(q.join(" "))}</blockquote>`); continue;
    }
    if (/^\s*([-*•]|\d+[.)])\s+/.test(l)) {
      const ordered = /^\s*\d/.test(l), items = [];
      while (i < lines.length && /^\s*([-*•]|\d+[.)])\s+/.test(lines[i])) items.push(lines[i++].replace(/^\s*([-*•]|\d+[.)])\s+/, ""));
      out.push(`<${ordered ? "ol" : "ul"}>${items.map((x) => `<li>${inline(x)}</li>`).join("")}</${ordered ? "ol" : "ul"}>`); continue;
    }
    const p = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|\s*>|\s*([-*•]|\d+[.)])\s)/.test(lines[i]) && !(lines[i].includes("|") && isSep(lines[i + 1]))) p.push(lines[i++]);
    out.push(`<p>${p.map(inline).join("<br>")}</p>`);
  }
  return out.join("");
}

function download(name, mime, content) {
  const url = URL.createObjectURL(new Blob([content], { type: mime }));
  const a = Object.assign(document.createElement("a"), { href: url, download: name });
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

const stamp = () => new Date().toISOString().slice(0, 10);

export function enhanceTables(root, toast = () => {}) {
  root.querySelectorAll("a[href]").forEach((a) => { a.target = "_blank"; a.rel = "noopener noreferrer"; });
  root.querySelectorAll("table:not([data-enhanced])").forEach((table) => {
    table.dataset.enhanced = "1";
    const head = [...table.querySelectorAll("thead th, tr:first-child th")].map((th) => th.textContent.trim());
    const body = [...table.querySelectorAll("tbody tr")];
    const wrap = document.createElement("div");
    wrap.className = "dt";
    wrap.innerHTML = `<div class="dt-bar"><span class="dt-count"></span>${body.length > 6 ? '<input class="dt-filter" type="search" placeholder="Filtrar filas…" aria-label="Filtrar filas">' : ""}<span class="dt-actions"><button type="button" data-a="copy">Copiar</button><button type="button" data-a="csv">CSV</button><button type="button" data-a="xls">Excel</button></span></div><div class="dt-scroll"></div>`;
    table.replaceWith(wrap);
    wrap.querySelector(".dt-scroll").appendChild(table);
    const count = wrap.querySelector(".dt-count");
    const visible = () => body.filter((r) => !r.hidden).map((r) => [...r.cells].map((c) => c.textContent.trim()));
    const refresh = () => { const n = visible().length; count.textContent = `${n} ${n === 1 ? "fila" : "filas"}`; };
    refresh();

    wrap.querySelector(".dt-filter")?.addEventListener("input", (e) => {
      const q = e.target.value.toLowerCase();
      body.forEach((r) => (r.hidden = !!q && !r.textContent.toLowerCase().includes(q)));
      refresh();
    });

    table.querySelectorAll("thead th").forEach((th, col) => {
      th.tabIndex = 0; th.title = "Ordenar";
      const sort = () => {
        const dir = th.dataset.dir === "asc" ? "desc" : "asc";
        table.querySelectorAll("th").forEach((x) => delete x.dataset.dir);
        th.dataset.dir = dir;
        const tb = table.tBodies[0];
        [...body].sort((a, b) => a.cells[col].textContent.localeCompare(b.cells[col].textContent, "es", { numeric: true }) * (dir === "asc" ? 1 : -1)).forEach((r) => tb.appendChild(r));
      };
      th.addEventListener("click", sort);
      th.addEventListener("keydown", (e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), sort()));
    });

    wrap.querySelector(".dt-actions").addEventListener("click", (e) => {
      const act = e.target.dataset.a;
      if (!act) return;
      const rows = visible();
      if (act === "copy") {
        navigator.clipboard?.writeText([head, ...rows].map((r) => r.join("\t")).join("\n")).then(() => toast("Tabla copiada"), () => toast("No se pudo copiar"));
      } else if (act === "csv") {
        const q = (v) => `"${v.replace(/"/g, '""')}"`;
        download(`mIA_listado_${stamp()}.csv`, "text/csv;charset=utf-8", "\ufeff" + [head, ...rows].map((r) => r.map(q).join(";")).join("\r\n"));
        toast(`CSV descargado · ${rows.length} filas`);
      } else {
        const t = `<table><tr>${head.map((h) => `<th>${esc(h)}</th>`).join("")}</tr>${rows.map((r) => `<tr>${r.map((c) => `<td>${esc(c)}</td>`).join("")}</tr>`).join("")}</table>`;
        download(`mIA_listado_${stamp()}.xls`, "application/vnd.ms-excel", `<html><head><meta charset="utf-8"></head><body>${t}</body></html>`);
        toast(`Excel descargado · ${rows.length} filas`);
      }
    });
  });
}
