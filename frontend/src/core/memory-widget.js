/**
 * Control visual de la Memoria Inteligente (V1): un botón discreto, compartido por los tres
 * mundos (2D, 3D, holograma), para activar/desactivar la memoria propia y consultar/borrar los
 * recuerdos guardados. Se monta solo (crea su propio DOM e inyecta su propio CSS) para no exigir
 * ningún cambio en el HTML de cada mundo — igual de válido en el mundo 2D en producción, cuyo
 * entry point (`mia-entry-v530.js`) ya es un módulo ES, aunque `mia-2d.js`/`mia-enhance.js` no lo
 * sean.
 *
 * Si la Memoria Inteligente no está activada globalmente en este despliegue
 * (`MIA_MEMORY__ENABLED`), `GET /api/memory/settings` responde `available:false` y el widget no
 * se muestra — nunca un botón que no hace nada ni un error visible. Igual si la petición falla
 * por cualquier otro motivo: el resto de mIA debe seguir funcionando sin este control.
 */

import { getAccessToken } from "./auth-gate.js";

const STYLE_ID = "mia-memory-widget-style";

const CSS = `
.mia-mem-launcher{position:fixed;left:18px;bottom:18px;z-index:999999;width:44px;height:44px;
  border-radius:50%;border:1px solid rgba(214,176,103,.45);background:rgba(8,32,42,.92);
  color:#d6b067;font-size:19px;display:grid;place-items:center;cursor:pointer;
  box-shadow:0 10px 26px rgba(0,0,0,.35);backdrop-filter:blur(10px);transition:.2s;}
.mia-mem-launcher:hover{transform:translateY(-2px);box-shadow:0 14px 30px rgba(0,0,0,.4);}
.mia-mem-launcher[data-on="1"]{border-color:#d6b067;box-shadow:0 0 0 3px rgba(214,176,103,.18),0 10px 26px rgba(0,0,0,.35);}
.mia-mem-panel{position:fixed;left:18px;bottom:72px;z-index:999999;width:290px;max-height:60vh;
  display:flex;flex-direction:column;border-radius:16px;border:1px solid rgba(255,255,255,.14);
  background:rgba(8,24,30,.97);backdrop-filter:blur(14px);box-shadow:0 20px 50px rgba(0,0,0,.45);
  color:#eef2f1;font:13px/1.4 system-ui,sans-serif;overflow:hidden;}
.mia-mem-panel[hidden]{display:none;}
.mia-mem-head{display:flex;align-items:center;justify-content:space-between;gap:10px;
  padding:12px 14px;border-bottom:1px solid rgba(255,255,255,.1);}
.mia-mem-title{font-weight:700;color:#d6b067;letter-spacing:.01em;}
.mia-mem-switch{position:relative;width:38px;height:22px;border-radius:999px;border:none;
  background:rgba(255,255,255,.18);cursor:pointer;flex-shrink:0;transition:.2s;}
.mia-mem-switch[aria-pressed="true"]{background:#d6b067;}
.mia-mem-switch::after{content:"";position:absolute;top:2px;left:2px;width:18px;height:18px;
  border-radius:50%;background:#0c2129;transition:.2s;}
.mia-mem-switch[aria-pressed="true"]::after{transform:translateX(16px);}
.mia-mem-hint{padding:10px 14px;color:#9fb3b0;font-size:11.5px;}
.mia-mem-list{list-style:none;margin:0;padding:0 8px;overflow-y:auto;flex:1;}
.mia-mem-item{display:flex;align-items:flex-start;gap:8px;padding:8px 6px;
  border-bottom:1px solid rgba(255,255,255,.06);}
.mia-mem-item span{flex:1;word-break:break-word;}
.mia-mem-item button{border:none;background:transparent;color:#9fb3b0;cursor:pointer;
  font-size:15px;line-height:1;padding:2px 4px;flex-shrink:0;}
.mia-mem-item button:hover{color:#e0806a;}
.mia-mem-foot{padding:10px 14px;border-top:1px solid rgba(255,255,255,.1);}
.mia-mem-clear{width:100%;border:1px solid rgba(255,255,255,.15);background:transparent;
  color:#9fb3b0;border-radius:10px;padding:7px 0;font-size:11.5px;cursor:pointer;}
.mia-mem-clear:hover{color:#e0806a;border-color:rgba(224,128,106,.4);}
`;

function injectStyle() {
  if (document.getElementById(STYLE_ID)) return;
  const style = document.createElement("style");
  style.id = STYLE_ID;
  style.textContent = CSS;
  document.head.appendChild(style);
}

async function authHeaders() {
  const token = await getAccessToken().catch(() => null);
  return token ? { Authorization: `Bearer ${token}` } : {};
}

class MemoryApi {
  constructor(apiBase) {
    this.apiBase = apiBase;
  }

  async _fetch(path, options = {}) {
    const response = await fetch(`${this.apiBase}${path}`, {
      ...options,
      headers: { "Content-Type": "application/json", ...(await authHeaders()), ...(options.headers || {}) },
    });
    if (!response.ok) throw new Error(`memoria HTTP ${response.status}`);
    return response.status === 204 ? null : response.json();
  }

  getSettings() {
    return this._fetch("/api/memory/settings");
  }

  setEnabled(enabled) {
    return this._fetch("/api/memory/settings", { method: "PUT", body: JSON.stringify({ enabled }) });
  }

  listItems() {
    return this._fetch("/api/memory/items");
  }

  deleteItem(id) {
    return this._fetch(`/api/memory/items/${encodeURIComponent(id)}`, { method: "DELETE" });
  }

  deleteAll() {
    return this._fetch("/api/memory/items", { method: "DELETE" });
  }
}

function formatDate(iso) {
  try {
    return new Date(iso).toLocaleDateString("es-ES", { day: "2-digit", month: "2-digit", year: "numeric" });
  } catch {
    return "";
  }
}

/**
 * Monta el control si la Memoria Inteligente está activada globalmente; no hace nada (ni lanza)
 * si está apagada o si la primera consulta falla por cualquier motivo.
 */
export async function mountMemoryWidget({ apiBase = "" } = {}) {
  const api = new MemoryApi(apiBase);
  let settings;
  try {
    settings = await api.getSettings();
  } catch (error) {
    console.warn("[mIA] Memoria no disponible:", error);
    return;
  }
  if (!settings?.available) return;

  injectStyle();

  const launcher = document.createElement("button");
  launcher.type = "button";
  launcher.className = "mia-mem-launcher";
  launcher.title = "Memoria de mIA";
  launcher.setAttribute("aria-label", "Memoria de mIA");
  launcher.textContent = "🧠";
  launcher.dataset.on = settings.enabled ? "1" : "0";

  const panel = document.createElement("div");
  panel.className = "mia-mem-panel";
  panel.hidden = true;

  let enabled = settings.enabled;

  async function refreshList() {
    const body = panel.querySelector(".mia-mem-body");
    body.innerHTML = "";
    if (!enabled) {
      const hint = document.createElement("p");
      hint.className = "mia-mem-hint";
      hint.textContent =
        "La memoria está desactivada: mIA no guarda ni usa ningún recuerdo. Actívala para empezar a pedirle que recuerde algo.";
      body.appendChild(hint);
      return;
    }
    const hint = document.createElement("p");
    hint.className = "mia-mem-hint";
    hint.textContent = 'Pídele a mIA "recuerda que..." en cualquier mundo y lo verás aquí.';
    body.appendChild(hint);

    let data;
    try {
      data = await api.listItems();
    } catch {
      return;
    }
    if (!data.items.length) return;

    const list = document.createElement("ul");
    list.className = "mia-mem-list";
    for (const item of data.items) {
      const row = document.createElement("li");
      row.className = "mia-mem-item";
      const text = document.createElement("span");
      text.textContent = item.content;
      text.title = formatDate(item.created_at);
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "×";
      remove.title = "Olvidar este recuerdo";
      remove.addEventListener("click", async () => {
        try {
          await api.deleteItem(item.id);
          row.remove();
        } catch (error) {
          console.warn("[mIA] No se ha podido borrar el recuerdo:", error);
        }
      });
      row.append(text, remove);
      list.appendChild(row);
    }
    body.appendChild(list);

    const foot = document.createElement("div");
    foot.className = "mia-mem-foot";
    const clear = document.createElement("button");
    clear.type = "button";
    clear.className = "mia-mem-clear";
    clear.textContent = "Borrar todos los recuerdos";
    clear.addEventListener("click", async () => {
      if (!window.confirm("¿Borrar todos los recuerdos guardados? No se puede deshacer.")) return;
      try {
        await api.deleteAll();
        await refreshList();
      } catch (error) {
        console.warn("[mIA] No se ha podido borrar la memoria:", error);
      }
    });
    foot.appendChild(clear);
    body.appendChild(foot);
  }

  const head = document.createElement("div");
  head.className = "mia-mem-head";
  const title = document.createElement("span");
  title.className = "mia-mem-title";
  title.textContent = "Memoria";
  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "mia-mem-switch";
  toggle.setAttribute("role", "switch");
  toggle.setAttribute("aria-pressed", String(enabled));
  toggle.setAttribute("aria-label", "Activar o desactivar la memoria");
  toggle.addEventListener("click", async () => {
    const next = !enabled;
    toggle.disabled = true;
    try {
      await api.setEnabled(next);
      enabled = next;
      toggle.setAttribute("aria-pressed", String(enabled));
      launcher.dataset.on = enabled ? "1" : "0";
      await refreshList();
    } catch (error) {
      console.warn("[mIA] No se ha podido cambiar la memoria:", error);
    } finally {
      toggle.disabled = false;
    }
  });
  head.append(title, toggle);

  const body = document.createElement("div");
  body.className = "mia-mem-body";

  panel.append(head, body);

  launcher.addEventListener("click", async () => {
    panel.hidden = !panel.hidden;
    if (!panel.hidden) await refreshList();
  });

  document.addEventListener("click", (event) => {
    if (!panel.hidden && !panel.contains(event.target) && event.target !== launcher) panel.hidden = true;
  });

  document.body.append(launcher, panel);
}
