/* mIA 2D · mejoras sobre el universo anterior, sin modificar mia-2d.js:
 *   1) gráficos (barras, anillo, línea) para recuentos por categorías y series temporales,
 *   2) correo: abrir un correo, proponer respuesta y confirmar el envío del borrador,
 *   3) borradores y correos abiertos como tarjetas.
 * Se engancha a renderData() y usa ask() del propio 2D para conversar. */
(function () {
  'use strict';
  if (typeof renderData !== 'function' || typeof ask !== 'function') return;
  var PALETTE = ['#172044', '#d8a565', '#4ca7a3', '#d9776b', '#5b8def', '#8a6bb0', '#7fa37a', '#c9b8a3'];
  var NS = 'http://www.w3.org/2000/svg';

  function el(tag, cls, text) { var n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; }
  function svg(tag, attrs) { var n = document.createElementNS(NS, tag); for (var k in attrs) n.setAttribute(k, attrs[k]); return n; }
  function fmtNum(v) { return Number(v).toLocaleString('es-ES', { maximumFractionDigits: 1 }); }
  function grow(fn) { requestAnimationFrame(function () { requestAnimationFrame(fn); }); }

  /* ------------------------------------------------------------------ gráficos */
  function barChart(spec) {
    var values = spec.series[0].values, max = Math.max.apply(null, values) || 1;
    var box = el('div', 'mia-bars');
    spec.labels.forEach(function (label, i) {
      var row = el('div', 'mia-bar-row');
      var name = el('span', 'mia-bar-label', label); name.title = label;
      var track = el('span', 'mia-bar-track'), fill = el('span', 'mia-bar-fill');
      track.appendChild(fill);
      row.appendChild(name); row.appendChild(track); row.appendChild(el('span', 'mia-bar-value', fmtNum(values[i])));
      box.appendChild(row);
      grow(function () { fill.style.width = Math.max(2, (values[i] / max) * 100) + '%'; });
    });
    return box;
  }

  function donutChart(spec) {
    var values = spec.series[0].values, total = values.reduce(function (a, b) { return a + b; }, 0) || 1;
    var wrap = el('div', 'mia-donut'), s = svg('svg', { viewBox: '0 0 150 150', role: 'img', 'aria-label': spec.title || 'Gráfico' });
    var R = 54, C = 2 * Math.PI * R, offset = 0;
    s.appendChild(svg('circle', { cx: 75, cy: 75, r: R, fill: 'none', stroke: 'rgba(23,32,68,.06)', 'stroke-width': 22 }));
    values.forEach(function (v, i) {
      var len = (v / total) * C;
      var arc = svg('circle', { class: 'mia-donut-arc', cx: 75, cy: 75, r: R, transform: 'rotate(-90 75 75)', stroke: PALETTE[i % PALETTE.length],
        'stroke-dasharray': '0 ' + C, 'stroke-dashoffset': -offset });
      s.appendChild(arc); offset += len;
      grow(function () { arc.setAttribute('stroke-dasharray', Math.max(0, len - 1.5) + ' ' + (C - len + 1.5)); });
    });
    var t = svg('text', { class: 'mia-donut-total', x: 75, y: 78 }); t.textContent = fmtNum(total); s.appendChild(t);
    var c = svg('text', { class: 'mia-donut-caption', x: 75, y: 94 }); c.textContent = 'TOTAL'; s.appendChild(c);
    var legend = el('div', 'mia-legend');
    spec.labels.forEach(function (label, i) {
      var row = document.createElement('div'), dot = document.createElement('i'); dot.style.background = PALETTE[i % PALETTE.length];
      row.appendChild(dot); row.appendChild(document.createTextNode(label));
      row.appendChild(el('b', null, fmtNum(values[i]) + ' · ' + Math.round((values[i] / total) * 100) + '%')); legend.appendChild(row);
    });
    wrap.appendChild(s); wrap.appendChild(legend); return wrap;
  }

  function lineChart(spec) {
    var values = spec.series[0].values, W = 560, H = 170, pad = 28, max = Math.max.apply(null, values), min = Math.min(0, Math.min.apply(null, values));
    var span = (max - min) || 1, step = values.length > 1 ? (W - 2 * pad) / (values.length - 1) : 0;
    var pts = values.map(function (v, i) { return [pad + i * step, H - 30 - ((v - min) / span) * (H - 60)]; });
    var box = el('div', 'mia-line'), s = svg('svg', { viewBox: '0 0 ' + W + ' ' + H, role: 'img', 'aria-label': spec.title || 'Gráfico' });
    var d = pts.map(function (p, i) { return (i ? 'L' : 'M') + p[0].toFixed(1) + ' ' + p[1].toFixed(1); }).join(' ');
    s.appendChild(svg('path', { class: 'mia-line-area', d: d + ' L' + pts[pts.length - 1][0] + ' ' + (H - 30) + ' L' + pts[0][0] + ' ' + (H - 30) + ' Z' }));
    var path = svg('path', { class: 'mia-line-path', d: d }); s.appendChild(path);
    pts.forEach(function (p, i) {
      s.appendChild(svg('circle', { class: 'mia-line-dot', cx: p[0], cy: p[1], r: 4 }));
      var v = svg('text', { class: 'mia-line-val', x: p[0], y: p[1] - 10 }); v.textContent = fmtNum(values[i]); s.appendChild(v);
      var a = svg('text', { class: 'mia-line-axis', x: p[0], y: H - 10 }); a.textContent = spec.labels[i]; s.appendChild(a);
    });
    box.appendChild(s); grow(function () { path.style.strokeDashoffset = 0; }); return box;
  }

  function chartCard(spec) {
    var card = el('section', 'mia-chart'); card.setAttribute('data-chart', spec.type);
    var head = el('div', 'mia-chart-head'); head.appendChild(el('strong', null, spec.title || 'Gráfico'));
    head.appendChild(el('span', null, spec.series[0].name || '')); card.appendChild(head);
    card.appendChild(spec.type === 'donut' ? donutChart(spec) : spec.type === 'line' ? lineChart(spec) : barChart(spec));
    return card;
  }

  function button(label, cls, handler) { var b = el('button', 'mia-btn' + (cls ? ' ' + cls : ''), label); b.type = 'button'; b.addEventListener('click', handler); return b; }
  /* ------------------------------------------------------------------ correo: ventanas emergentes */
  var $ = { root: function () { return (typeof context !== 'undefined' && context) || window.context || {}; } };
  function sessionId() { return $.root().session_id || null; }

  async function mailApi(action, payload) {
    var body = Object.assign({ session_id: sessionId() }, payload || {});
    try {
      // Script clasico: lee el token via el global que auth-gate.js expone (ver mia-2d.js, miaAuthHeaders).
      var token = typeof window.miaGetAccessToken === 'function' ? await window.miaGetAccessToken() : null;
      var headers = { 'Content-Type': 'application/json' };
      if (token) headers.Authorization = 'Bearer ' + token;
      var r = await fetch('/api/mia/mail/' + action, { method: 'POST', headers: headers, body: JSON.stringify(body) });
      var j = await r.json().catch(function () { return { ok: false, error: 'Respuesta no válida del servidor (' + r.status + ')' }; });
      if (j && j.session_id) { try { $.root().session_id = j.session_id; } catch (e) { /* noop */ } }
      return j;
    } catch (e) {
      return { ok: false, error: 'No he podido conectar con el servidor.' };
    }
  }

  var openModals = [];
  function initials(name) { return String(name || '?').split(/\s+/).filter(Boolean).slice(0, 2).map(function (w) { return w[0]; }).join('').toUpperCase() || '?'; }
  function fmtDate(v) { try { return new Date(v).toLocaleString('es-ES', { dateStyle: 'medium', timeStyle: 'short' }); } catch (e) { return v || ''; } }

  function modal(opts) {
    var backdrop = el('div', 'mia-modal-backdrop'), panel = el('div', 'mia-modal' + (opts.wide ? ' wide' : ''));
    backdrop.setAttribute('role', 'dialog'); backdrop.setAttribute('aria-modal', 'true'); backdrop.setAttribute('aria-label', opts.title || 'Ventana');
    var head = el('header', 'mia-modal-head');
    head.appendChild(el('div', 'mia-modal-avatar' + (opts.icon ? ' icon' : ''), opts.icon || initials(opts.avatar)));
    var titles = el('div', 'mia-modal-title'); titles.appendChild(el('h3', null, opts.title || '')); if (opts.subtitle) titles.appendChild(el('p', null, opts.subtitle));
    head.appendChild(titles);
    var x = el('button', 'mia-modal-x', '×'); x.type = 'button'; x.setAttribute('aria-label', 'Cerrar'); head.appendChild(x);
    var meta = el('div', 'mia-modal-meta'), body = el('div', 'mia-modal-body'), foot = el('footer', 'mia-modal-foot');
    panel.appendChild(head); panel.appendChild(meta); panel.appendChild(body); panel.appendChild(foot); backdrop.appendChild(panel);
    var api = { backdrop: backdrop, panel: panel, meta: meta, body: body, foot: foot, head: head, titles: titles };
    api.close = function () {
      if (!backdrop.parentNode) return;
      backdrop.classList.remove('in'); backdrop.classList.add('out');
      setTimeout(function () { if (backdrop.parentNode) backdrop.parentNode.removeChild(backdrop); }, 220);
      openModals = openModals.filter(function (m) { return m !== api; });
      if (!openModals.length) document.body.classList.remove('mia-modal-open');
      if (opts.onClose) opts.onClose();
    };
    x.addEventListener('click', api.close);
    backdrop.addEventListener('mousedown', function (e) { if (e.target === backdrop && !opts.sticky) api.close(); });
    document.body.appendChild(backdrop); document.body.classList.add('mia-modal-open'); openModals.push(api);
    requestAnimationFrame(function () { backdrop.classList.add('in'); });
    return api;
  }
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && openModals.length) openModals[openModals.length - 1].close(); });

  function chip(label, value, cls) { var c = el('span', 'mia-chip' + (cls ? ' ' + cls : '')); if (label) c.appendChild(el('b', null, label)); c.appendChild(document.createTextNode(value)); return c; }
  function safeLink(url, label) {
    var a = document.createElement('a'); a.className = 'mia-link'; a.textContent = label; a.target = '_blank'; a.rel = 'noopener noreferrer';
    a.href = /^https?:\/\//i.test(url) ? url : '#'; return a;
  }
  function hostOf(url) { try { return new URL(url).hostname.replace(/^www\./, ''); } catch (e) { return url; } }

  /* Tarjeta de un adjunto real: descarga directa cuando el backend trae url (ficheros), o un
   * aviso sin enlace cuando no (p. ej. un correo reenviado como adjunto). Nunca se muestra el
   * texto extraído del adjunto aquí: eso es solo para que el modelo lo lea, no para pantalla. */
  function attachmentCard(a) {
    var name = (a && a.nombre) || 'Adjunto';
    if (a && /^\/api\/mail\/attachment\//.test(a.url || '')) {
      var btn = document.createElement('button');
      btn.type = 'button'; btn.className = 'mia-attachment';
      var actionLabel = el('span', 'mia-attachment-action', 'Descargar ↓');
      btn.appendChild(el('span', 'mia-attachment-name', name));
      btn.appendChild(actionLabel);
      btn.addEventListener('click', function () {
        if (btn.disabled) return;
        btn.disabled = true; actionLabel.textContent = 'Descargando…';
        var getToken = typeof window.miaGetAccessToken === 'function' ? window.miaGetAccessToken : null;
        Promise.resolve(getToken ? getToken() : null).then(function (token) {
          return fetch(a.url, { headers: token ? { Authorization: 'Bearer ' + token } : {} });
        }).then(function (res) {
          if (!res.ok) throw new Error('HTTP ' + res.status);
          return res.blob();
        }).then(function (blob) {
          var blobUrl = URL.createObjectURL(blob);
          var tmp = document.createElement('a');
          tmp.href = blobUrl; tmp.download = name; tmp.rel = 'noopener noreferrer';
          document.body.appendChild(tmp); tmp.click(); document.body.removeChild(tmp);
          setTimeout(function () { URL.revokeObjectURL(blobUrl); }, 30000);
        }).catch(function (err) {
          console.warn('[mIA] No se pudo descargar el adjunto:', err);
          actionLabel.textContent = 'Error al descargar';
          return;
        }).finally(function () {
          btn.disabled = false;
          if (actionLabel.textContent === 'Descargando…') actionLabel.textContent = 'Descargar ↓';
        });
      });
      return btn;
    }
    var span = el('div', 'mia-attachment mia-attachment--unavailable');
    span.appendChild(el('span', 'mia-attachment-name', name));
    return span;
  }
  function attachmentList(attachments) {
    if (!attachments || !attachments.length) return null;
    var wrap = el('div', 'mia-attachments');
    attachments.forEach(function (a) { wrap.appendChild(attachmentCard(a)); });
    return wrap;
  }

  /* Texto del correo → párrafos, viñetas y enlaces (todo con nodos DOM, nunca innerHTML). */
  function linkify(text, into) {
    var re = /([^\n()]{1,80}?)\s+\((https?:\/\/[^\s)]+)\)|(https?:\/\/[^\s<)]+)/g, last = 0, m;
    while ((m = re.exec(text))) {
      if (m.index > last) into.appendChild(document.createTextNode(text.slice(last, m.index)));
      if (m[2]) into.appendChild(safeLink(m[2], m[1].trim())); else into.appendChild(safeLink(m[3], hostOf(m[3])));
      last = m.index + m[0].length;
    }
    if (last < text.length) into.appendChild(document.createTextNode(text.slice(last)));
  }
  function formatMailBody(text) {
    var box = el('div', 'mia-mail-text');
    String(text || '').split(/\n{2,}/).forEach(function (block) {
      var lines = block.split('\n').filter(function (l) { return l.trim(); }); if (!lines.length) return;
      if (lines.every(function (l) { return /^\s*-\s+/.test(l); })) {
        var ul = document.createElement('ul');
        lines.forEach(function (l) { var li = document.createElement('li'); linkify(l.replace(/^\s*-\s+/, ''), li); ul.appendChild(li); }); box.appendChild(ul);
      } else if (lines.length === 1 && lines[0].length < 90 && !/[.:,;]$/.test(lines[0]) && block === text.split(/\n{2,}/)[0]) {
        var h = el('h4'); linkify(lines[0], h); box.appendChild(h);
      } else {
        var p = document.createElement('p'); lines.forEach(function (l, i) { if (i) p.appendChild(document.createElement('br')); linkify(l, p); }); box.appendChild(p);
      }
    });
    if (!box.childNodes.length) box.appendChild(el('p', 'mia-muted', '(sin contenido)'));
    return box;
  }
  function shimmer(lines) { var s = el('div', 'mia-shimmer'); for (var i = 0; i < lines; i++) s.appendChild(el('i')); return s; }
  function banner(kind, text) { return el('div', 'mia-banner ' + kind, text); }

  /* ---- ventana: leer un correo */
  function openMail(ref, hint) {
    hint = hint || {};
    var m = modal({ title: hint.subject || 'Correo', subtitle: hint.sender_name || '', avatar: hint.sender_name });
    m.body.appendChild(shimmer(6));
    mailApi('open', { ref: ref }).then(function (res) {
      m.body.innerHTML = ''; m.foot.innerHTML = '';
      if (!res.ok) { m.body.appendChild(banner('error', res.error || 'No he podido abrir el correo.')); m.foot.appendChild(button('Cerrar', '', m.close)); return; }
      var msg = res.message;
      m.titles.firstChild.textContent = msg.subject || '(sin asunto)';
      m.titles.querySelector('p') ? (m.titles.querySelector('p').textContent = fmtDate(msg.received_at)) : m.titles.appendChild(el('p', null, fmtDate(msg.received_at)));
      m.head.querySelector('.mia-modal-avatar').textContent = initials(msg.from_name);
      m.meta.appendChild(chip('De', (msg.from_name || '') + (msg.from_address ? ' <' + msg.from_address + '>' : '')));
      if (msg.to && msg.to.length) m.meta.appendChild(chip('Para', msg.to.join(', ')));
      if (msg.no_reply) m.meta.appendChild(chip('', 'Correo automático · no admite respuesta', 'warn'));
      m.body.appendChild(formatMailBody(msg.text));
      var attachments = attachmentList(msg.attachments);
      if (attachments) m.body.appendChild(attachments);
      var reply = button('Proponer respuesta', 'primary', function () { openCompose(ref, msg); });
      if (msg.no_reply) { reply.disabled = true; reply.title = 'Es un correo automático (no-reply): no admite respuesta'; }
      m.foot.appendChild(reply); m.foot.appendChild(button('Cerrar', '', m.close));
    });
    return m;
  }

  /* ---- ventana: proponer, editar, guardar y enviar una respuesta */
  function openCompose(ref, msg, existing) {
    var state = { borrador: existing ? existing.borrador : null, sent: false, confirming: false, enabled: existing ? existing.envio_habilitado : null, firma: existing ? existing.firma_preview : null, mailbox: existing ? existing.buzon_envio_nombre : null };
    var subject = (msg && msg.subject) || 'Respuesta';
    var m = modal({ title: 'Respuesta', subtitle: 'Re: ' + subject, icon: '✎', wide: true, sticky: true });
    if (msg && msg.from_address) m.meta.appendChild(chip('Para', (msg.from_name || '') + ' <' + msg.from_address + '>'));
    var area = document.createElement('textarea'); area.className = 'mia-compose'; area.rows = 9; area.spellcheck = true;
    var status = el('div', 'mia-status'), hintRow = el('div', 'mia-regen'), instr = document.createElement('input');
    instr.type = 'text'; instr.placeholder = 'Indicaciones (opcional): «más formal», «dile que lo vemos el lunes»…'; instr.className = 'mia-input';
    var regen = button('Regenerar', '', function () { generate(); }); hintRow.appendChild(instr); hintRow.appendChild(regen);
    var confirmSlot = el('div', 'mia-confirm-slot');
    var signaturePreview = el('details', 'mia-signature-preview');
    var signatureSummary = el('summary', null, 'Vista previa de la firma corporativa');
    signaturePreview.appendChild(signatureSummary);
    var signatureContent = el('div', 'mia-signature-preview-content');
    signaturePreview.appendChild(signatureContent);
    if (state.firma) renderSignature(state.firma);
    function renderSignature(text) {
      state.firma = text;
      signatureContent.innerHTML = '';
      var banner = document.createElement('img'); banner.src = '/mia-assets/signature-banner.png';
      banner.alt = 'Sunset Beach Club · Amazing Holidays all year round';
      banner.style.cssText = 'display:block;width:100%;max-width:600px;height:auto;margin:8px 0';
      signatureContent.appendChild(banner);
      var preview = document.createElement('pre'); preview.textContent = text;
      preview.style.cssText = 'white-space:pre-wrap;font:12px/1.45 Arial,Helvetica,sans-serif;color:#526579;margin:8px 0';
      signatureContent.appendChild(preview);
      signaturePreview.open = true;
    }
    m.body.appendChild(status); m.body.appendChild(area); m.body.appendChild(signaturePreview); m.body.appendChild(hintRow);
    var save = button('Guardar borrador', 'primary', doSave), send = button('Enviar respuesta', 'primary', askConfirm), discard = button('Descartar', 'danger', doDiscard), cancel = button('Cerrar', '', m.close);
    function setStatus(kind, text) { status.innerHTML = ''; if (text) status.appendChild(banner(kind, text)); }
    function busy(on) { [save, send, discard, regen].forEach(function (b) { b.disabled = on || (b === send && !state.borrador) ; }); area.disabled = on; }
    function render() {
      m.foot.innerHTML = ''; m.foot.classList.toggle('confirming', state.confirming);
      if (state.sent) { m.foot.appendChild(button('Cerrar', 'primary', m.close)); return; }
      if (state.confirming) { m.foot.appendChild(confirmSlot); return; }
      if (!state.borrador) { m.foot.appendChild(save); m.foot.appendChild(cancel); return; }
      send.disabled = state.enabled === false; if (state.enabled === false) send.title = 'El envío de correos está desactivado en este entorno';
      m.foot.appendChild(send); m.foot.appendChild(save); m.foot.appendChild(discard); m.foot.appendChild(cancel);
      save.textContent = 'Guardar cambios';
    }
    function generate() {
      setStatus('info', 'mIA está redactando una propuesta…'); area.classList.add('loading'); busy(true);
      mailApi('propose', { ref: ref, instrucciones: instr.value }).then(function (res) {
        area.classList.remove('loading'); busy(false);
        if (!res.ok) { setStatus('error', res.error || 'No he podido redactar la propuesta.'); return; }
        area.value = res.texto; setStatus('', ''); area.focus(); render();
      });
    }
    function doSave() {
      var text = area.value.trim(); if (!text) { setStatus('error', 'El texto no puede estar vacío.'); return; }
      busy(true); setStatus('info', state.borrador ? 'Guardando cambios…' : 'Guardando el borrador en el buzón…');
      var call = state.borrador ? mailApi('update', { borrador: state.borrador, texto: text }) : mailApi('draft', { ref: ref, texto: text });
      call.then(function (res) {
        busy(false);
        if (!res.ok) { setStatus('error', res.error || 'No he podido guardar el borrador.'); return; }
        if (res.draft) { state.borrador = res.draft.borrador || state.borrador; state.enabled = res.draft.envio_habilitado; state.mailbox = res.draft.buzon_envio_nombre || state.mailbox; if (res.draft.firma_preview) renderSignature(res.draft.firma_preview); }
        setStatus('ok', 'Borrador guardado en el buzón. Todavía no se ha enviado.'); render();
      });
    }
    function askConfirm() {
      confirmSlot.innerHTML = ''; var box = el('div', 'mia-confirm');
      box.appendChild(el('strong', null, '¿Enviar esta respuesta?'));
      var from = state.mailbox || 'tu buzón';
      var to = (msg && msg.from_address) || 'el remitente del correo';
      box.appendChild(el('span', null, 'De ' + from + ' · Para ' + to + '. El envío no se puede deshacer.'));
      var row = el('div', 'mia-actions');
      row.appendChild(button('Sí, enviar', 'primary', function () {
        var confirmButton = row.querySelector('button'); if (confirmButton) confirmButton.disabled = true;
        busy(true); setStatus('info', 'Enviando…');
        mailApi('send', { borrador: state.borrador }).then(function (res) {
          busy(false);
          if (!res.ok) { state.confirming = false; confirmSlot.innerHTML = ''; setStatus('error', res.error || 'No se ha podido enviar.'); render(); return; }
          state.confirming = false; confirmSlot.innerHTML = '';
          state.sent = true; area.disabled = true; hintRow.style.display = 'none'; setStatus('ok', '✓ Respuesta enviada.'); render();
        });
      }));
      row.appendChild(button('Cancelar', '', function () { state.confirming = false; confirmSlot.innerHTML = ''; render(); })); box.appendChild(row); confirmSlot.appendChild(box);
      state.confirming = true; render();
    }
    function doDiscard() {
      busy(true); mailApi('discard', { borrador: state.borrador }).then(function (res) {
        busy(false); if (!res.ok) { setStatus('error', res.error || 'No he podido descartar el borrador.'); return; }
        state.borrador = null; setStatus('info', 'Borrador descartado.'); render();
      });
    }
    if (existing) { area.value = existing.texto || ''; setStatus('ok', 'Borrador guardado en el buzón. Todavía no se ha enviado.'); render(); if (state.enabled === false) status.appendChild(el('div', 'mia-note', 'El envío de correos está desactivado en este entorno.')); }
    else { render(); generate(); }
    return m;
  }

  /* ---- en el listado de correos: botones que abren las ventanas */
  function decorateMailList(wrap, rows) {
    wrap.querySelectorAll('.mail-item').forEach(function (item, i) {
      var row = rows[i]; if (!row || !row.ref) return;
      var bar = el('div', 'mia-actions');
      bar.appendChild(button('Abrir correo', '', function () { openMail(row.ref, row); }));
      var reply = button('Proponer respuesta', 'primary', function () { openCompose(row.ref, { subject: row.subject, from_name: row.sender_name, from_address: row.sender_address }); });
      if (row.no_reply) { reply.disabled = true; reply.title = 'Correo automático: no admite respuesta'; }
      bar.appendChild(reply); item.appendChild(bar);
    });
    var chip2 = wrap.querySelector('.mail-readonly'); if (chip2) chip2.textContent = 'Envío con confirmación';
  }

  /* ---- correo abierto o borrador dentro de la conversación: tarjeta breve + botón para abrir la ventana */
  function mailMessageCard(m) {
    var card = el('section', 'mia-mail-card');
    card.appendChild(el('h4', null, m.subject || '(sin asunto)'));
    var meta = el('div', 'mia-mail-meta'); meta.appendChild(el('span', null, 'De: ' + (m.from_name || '') + (m.from_address ? ' <' + m.from_address + '>' : '')));
    if (m.received_at) meta.appendChild(el('span', null, fmtDate(m.received_at))); card.appendChild(meta);
    var preview = el('div', 'mia-mail-body'); preview.appendChild(formatMailBody(String(m.text || '').slice(0, 700))); card.appendChild(preview);
    var attachments = attachmentList(m.attachments); if (attachments) card.appendChild(attachments);
    var bar = el('div', 'mia-actions');
    bar.appendChild(button('Abrir correo', 'primary', function () { openMail(m.ref, { subject: m.subject, sender_name: m.from_name }); }));
    card.appendChild(bar); return card;
  }
  /* ---- hilo completo: cabecera breve; la lista de mensajes la pinta decorateMailList() sobre mail_rows */
  function mailThreadCard(t) {
    var card = el('section', 'mia-mail-card mia-mail-thread-card');
    card.appendChild(el('h4', null, t.title || 'Hilo de correo'));
    card.appendChild(el('div', 'mia-mail-meta', (t.count || 0) + ' mensaje' + (t.count === 1 ? '' : 's') + ' en esta conversación'));
    return card;
  }
  function draftCard(d) {
    var card = el('section', 'mia-mail-card mia-draft');
    card.appendChild(el('span', 'mia-draft-state', 'Borrador · no enviado'));
    card.appendChild(el('h4', null, 'Borrador de respuesta'));
    card.appendChild(el('div', 'mia-mail-body', d.texto || ''));
    var bar = el('div', 'mia-actions');
    bar.appendChild(button('Abrir borrador', 'primary', function () { openCompose(d.responde_a, { subject: 'Respuesta' }, d); }));
    card.appendChild(bar);
    if (!d.envio_habilitado) card.appendChild(el('div', 'mia-note', 'El envío de correos está desactivado en este entorno: el borrador queda guardado en el buzón.'));
    return card;
  }

  /* ---- noticias corporativas y de grupo: tarjetas clicables que abren una ventana premium
   * (mismo modal() que el correo) con el enlace real a la fuente original. */
  function safeExternalUrl(value) {
    try { var u = new URL(String(value || '')); return (u.protocol === 'http:' || u.protocol === 'https:') ? u.href : ''; }
    catch (e) { return ''; }
  }
  /* Imágenes propias de mIA (p. ej. /api/community/newsletter/5/imagen, que descarga de
   * SharePoint con las credenciales del backend) necesitan el mismo Bearer que mailApi() —
   * un <img src> normal NUNCA puede mandar esa cabecera, así que se piden con fetch() y se
   * convierten a blob: así siguen pasando por el mismo gate de autenticación que el resto de
   * la API en vez de quedar abiertas a cualquiera que adivine la URL. */
  async function authenticatedImageSrc(path) {
    try {
      var token = typeof window.miaGetAccessToken === 'function' ? await window.miaGetAccessToken() : null;
      var headers = {};
      if (token) headers.Authorization = 'Bearer ' + token;
      var r = await fetch(path, { headers: headers });
      if (!r.ok) return '';
      var blob = await r.blob();
      return URL.createObjectURL(blob);
    } catch (e) { return ''; }
  }
  function loadImageSrc(value) {
    var text = String(value || '').trim();
    if (!text) return Promise.resolve('');
    if (/^\/api\/[\w/?=&%.-]+$/.test(text)) return authenticatedImageSrc(text);
    return Promise.resolve(safeExternalUrl(text));
  }
  function openNewsItem(item) {
    var subtitle = [item.fuente, item.fecha].filter(Boolean).join(' · ');
    var objectUrl = null;
    var m = modal({
      title: item.titulo || 'Noticia', subtitle: subtitle, icon: '📰',
      onClose: function () { if (objectUrl) URL.revokeObjectURL(objectUrl); }
    });
    if (item.empresa) m.meta.appendChild(chip('', item.empresa, 'news-empresa'));
    if (item.categoria) m.meta.appendChild(chip('', item.categoria, 'news-categoria'));
    var detailText = item.cuerpo || item.resumen;
    m.body.appendChild(detailText
      ? formatMailBody(detailText)
      : el('p', 'mia-muted', 'Sin contenido disponible: abre la noticia original para leerla completa.'));
    var href = safeExternalUrl(item.url);
    if (href) {
      var open = document.createElement('a');
      open.className = 'mia-btn primary'; open.href = href; open.target = '_blank'; open.rel = 'noopener noreferrer';
      open.textContent = 'Abrir noticia original ↗';
      m.foot.appendChild(open);
    }
    m.foot.appendChild(button('Cerrar', '', m.close));
    loadImageSrc(item.imagen).then(function (src) {
      if (!src || !m.body.isConnected) return;
      objectUrl = src.indexOf('blob:') === 0 ? src : null;
      var img = document.createElement('img');
      img.className = 'mia-news-popup-image'; img.src = src; img.alt = item.titulo || 'Noticia';
      img.addEventListener('error', function () { img.remove(); });
      m.body.insertBefore(img, m.body.firstChild);
    });
    return m;
  }
  function newsCard(item) {
    var card = el('article', 'mia-news-card');
    var badges = el('div', 'mia-news-badges');
    if (item.empresa) badges.appendChild(el('span', 'mia-news-badge mia-news-badge--empresa', item.empresa));
    if (item.categoria) badges.appendChild(el('span', 'mia-news-badge mia-news-badge--categoria', item.categoria));
    if (badges.childNodes.length) card.appendChild(badges);
    var title = document.createElement('button');
    title.type = 'button'; title.className = 'mia-news-title';
    title.textContent = item.titulo || 'Noticia';
    title.addEventListener('click', function () { openNewsItem(item); });
    card.appendChild(title);
    if (item.resumen) card.appendChild(el('p', 'mia-news-summary', item.resumen));
    var meta = [item.fuente, item.fecha].filter(Boolean).join(' · ');
    if (meta) card.appendChild(el('div', 'mia-news-meta', meta));
    return card;
  }
  function newsListCard(rows) {
    var card = el('section', 'mia-news-panel');
    rows.forEach(function (row) { card.appendChild(newsCard(row)); });
    return card;
  }

  /* ------------------------------------------------------------------ texto de la respuesta */
  function escapeHtml(v) { return String(v == null ? '' : v).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }
  function inline(html) {
    return html
      .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, function (_m, label, url) { return '<a class="mia-link" href="' + url + '" target="_blank" rel="noopener noreferrer">' + label + '</a>'; })
      .replace(/(^|[\s(])(https?:\/\/[^\s<)]+)/g, function (_m, pre, url) {
        var host = ''; try { host = new URL(url.replace(/&amp;/g, '&')).hostname.replace(/^www\./, ''); } catch (e) { return _m; }
        return pre + '<a class="mia-link" href="' + url + '" target="_blank" rel="noopener noreferrer">' + host + '</a>'; });
  }
  function tableHtml(lines) {
    var rows = lines.map(function (l) { return l.trim().replace(/^\||\|$/g, '').split('|').map(function (c) { return c.trim(); }); })
      .filter(function (cells) { return !cells.every(function (c) { return /^:?-{2,}:?$/.test(c); }); });
    if (rows.length < 2) return '';
    var head = rows[0], body = rows.slice(1);
    return '<div class="mia-answer-table"><table><thead><tr>' + head.map(function (c) { return '<th>' + inline(escapeHtml(c)) + '</th>'; }).join('') +
      '</tr></thead><tbody>' + body.map(function (r) { return '<tr>' + r.map(function (c) { return '<td>' + inline(escapeHtml(c).replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')) + '</td>'; }).join('') + '</tr>'; }).join('') + '</tbody></table></div>';
  }
  var baseRich = typeof miaRichText === 'function' ? miaRichText : null;
  if (baseRich) {
    miaRichText = function (value) {
      var lines = String(value == null ? '' : value).split(/\r?\n/), out = [], buffer = [], table = [];
      function flush() { if (buffer.length) { out.push(numbered(baseRich(buffer.join('\n')))); buffer = []; } }
      function numbered(html) {
        html = html.replace(/<div class="mia-answer-line">(\d{1,2})[.)]\s+(.*?)<\/div>/g, '<div class="mia-answer-bullet mia-num"><span><b>$1.</b> $2</span></div>');
        return inline(html);
      }
      lines.forEach(function (line) {
        if (/^\s*\|.*\|\s*$/.test(line)) { flush(); table.push(line); return; }
        if (table.length) { out.push(tableHtml(table) || ''); table = []; }
        buffer.push(line);
      });
      if (table.length) { flush(); out.push(tableHtml(table) || ''); }
      flush();
      return out.join('');
    };
  }

  /* ------------------------------------------------------------------ enganche */
  var original = renderData;
  renderData = function (r, msg) {
    var before = msg.querySelectorAll('.results').length;
    original(r, msg);
    try {
      var data = (r && r.data) || {}, extras = [];
      if (data.mail_message) extras.push(mailMessageCard(data.mail_message));
      if (data.mail_thread) extras.push(mailThreadCard(data.mail_thread));
      if (data.mail_draft) extras.push(draftCard(data.mail_draft));
      if (Array.isArray(data.news_rows) && data.news_rows.length) extras.push(newsListCard(data.news_rows));
      // Solo para correo: ese es el único kind cuyo renderData base NO llega a pintar data.charts
      // (vuelve antes, ver el "return" tras renderMailWorkspace en mia-2d.js) -- para cualquier
      // otro kind (p. ej. "analytics", que es lo que toca para la vista previa de un informe),
      // el renderCharts() base ya los pinta una vez; repetirlo aquí sin condición los duplicaba
      // (incidencia real en preprod 2026-10-26, nunca visible antes porque data.charts casi nunca
      // tenía contenido fuera del correo).
      if (typeof detectResultKind === 'function' && detectResultKind(r, data) === 'mail') {
        (Array.isArray(data.charts) ? data.charts : []).forEach(function (spec) {
          if (spec && spec.series && spec.series[0] && spec.labels) extras.push(chartCard(spec));
        });
      }
      var all = msg.querySelectorAll('.results'), wrap = all.length > before ? all[all.length - 1] : null;
      if (wrap && Array.isArray(data.mail_rows) && data.mail_rows.length) decorateMailList(wrap, data.mail_rows);
      if (window.miaAutoOpenNextMail) {
        window.miaAutoOpenNextMail = false;
        if (data.mail_message && data.mail_message.ref) {
          var openedMessage = data.mail_message;
          window.setTimeout(function () { openMail(openedMessage.ref, { subject: openedMessage.subject, sender_name: openedMessage.from_name }); }, 0);
        }
      }
      if (!extras.length) return;
      if (!wrap) {  // el 2D original no crea contenedor para un correo abierto o un borrador: lo creamos
        wrap = el('div', 'results results--mail'); msg.appendChild(wrap);
        extras.forEach(function (node) { wrap.appendChild(node); });
      } else {
        var anchor = wrap.firstElementChild;
        extras.forEach(function (node) { wrap.insertBefore(node, anchor && anchor.nextSibling); anchor = node; });
      }
      var c = document.getElementById('conversation'); if (c) c.scrollTop = c.scrollHeight;
    } catch (error) { console.error('[mIA mejoras 2D]', error); }
  };
})();
