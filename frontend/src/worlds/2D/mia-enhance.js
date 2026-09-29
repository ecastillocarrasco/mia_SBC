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

  /* ------------------------------------------------------------------ correo */
  function button(label, cls, handler) { var b = el('button', 'mia-btn' + (cls ? ' ' + cls : ''), label); b.type = 'button'; b.addEventListener('click', handler); return b; }
  function say(text) { ask(text); }

  function decorateMailList(wrap, rows) {
    var items = wrap.querySelectorAll('.mail-item');
    items.forEach(function (item, i) {
      var row = rows[i]; if (!row || !row.ref) return;
      var bar = el('div', 'mia-actions');
      bar.appendChild(button('Abrir correo', '', function () { say('Abre el correo ' + row.ref); }));
      bar.appendChild(button('Proponer respuesta', 'primary', function () { say('Propón una respuesta al correo ' + row.ref); }));
      item.appendChild(bar);
    });
    var chip = wrap.querySelector('.mail-readonly'); if (chip) chip.textContent = 'Envío con confirmación';
  }

  function mailMessageCard(m) {
    var card = el('section', 'mia-mail-card');
    card.appendChild(el('h4', null, m.subject || '(sin asunto)'));
    var meta = el('div', 'mia-mail-meta');
    meta.appendChild(el('span', null, 'De: ' + (m.from_name || '') + (m.from_address ? ' <' + m.from_address + '>' : '')));
    if (m.to && m.to.length) meta.appendChild(el('span', null, 'Para: ' + m.to.join(', ')));
    if (m.received_at) meta.appendChild(el('span', null, 'Recibido: ' + new Date(m.received_at).toLocaleString('es-ES')));
    if (m.attachments && m.attachments.length) meta.appendChild(el('span', null, 'Adjuntos: ' + m.attachments.join(', ')));
    card.appendChild(meta); card.appendChild(el('div', 'mia-mail-body', m.text || '(sin contenido)'));
    var bar = el('div', 'mia-actions');
    bar.appendChild(button('Proponer respuesta', 'primary', function () { say('Propón una respuesta al correo ' + m.ref); }));
    card.appendChild(bar); return card;
  }

  function draftCard(d) {
    var card = el('section', 'mia-mail-card mia-draft');
    card.appendChild(el('span', 'mia-draft-state', 'Borrador ' + d.borrador + ' · no enviado'));
    card.appendChild(el('h4', null, d.responde_a ? 'Respuesta al correo ' + d.responde_a : 'Borrador de respuesta'));
    var body = el('div', 'mia-mail-body', d.texto || ''); card.appendChild(body);
    var slot = el('div'); card.appendChild(slot);
    var bar = el('div', 'mia-actions'); card.appendChild(bar);
    var confirmBtn = button('Confirmar y enviar', 'primary', function () {
      slot.innerHTML = ''; var box = el('div', 'mia-confirm'); box.appendChild(el('div', null, '¿Enviar ahora este borrador? Se enviará desde el buzón de RRHH y no se puede deshacer.'));
      var actions = el('div', 'mia-actions');
      actions.appendChild(button('Sí, enviar', 'primary', function () { slot.innerHTML = ''; say('Sí, confirmo: envía el borrador ' + d.borrador); }));
      actions.appendChild(button('Cancelar', '', function () { slot.innerHTML = ''; }));
      box.appendChild(actions); slot.appendChild(box);
    });
    if (!d.envio_habilitado) { confirmBtn.disabled = true; confirmBtn.title = 'El envío está desactivado en este entorno'; }
    bar.appendChild(confirmBtn);
    bar.appendChild(button('Modificar', '', function () {
      slot.innerHTML = ''; var area = document.createElement('textarea'); area.value = d.texto || ''; slot.appendChild(area);
      var actions = el('div', 'mia-actions');
      actions.appendChild(button('Guardar cambios', 'primary', function () { var t = area.value.trim(); if (t) say('Modifica el borrador ' + d.borrador + ' con este texto: ' + t); }));
      actions.appendChild(button('Cancelar', '', function () { slot.innerHTML = ''; })); slot.appendChild(actions);
    }));
    bar.appendChild(button('Descartar', 'danger', function () { say('Descarta el borrador ' + d.borrador); }));
    if (!d.envio_habilitado) card.appendChild(el('div', 'mia-note', 'El envío de correos está desactivado en este entorno: el borrador queda guardado en el buzón.'));
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
      if (data.mail_draft) extras.push(draftCard(data.mail_draft));
      (Array.isArray(data.charts) ? data.charts : []).forEach(function (spec) {
        if (spec && spec.series && spec.series[0] && spec.labels) extras.push(chartCard(spec));
      });
      var all = msg.querySelectorAll('.results'), wrap = all.length > before ? all[all.length - 1] : null;
      if (wrap && Array.isArray(data.mail_rows) && data.mail_rows.length) decorateMailList(wrap, data.mail_rows);
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
