import test from 'node:test';
import assert from 'node:assert/strict';
import { renderPresentation } from '../src/core/present.js';
import { buildStatisticalPresentation } from '../src/core/statistical-visuals.js';

test('mail: renders sender, body and a real download link for a file attachment', () => {
  const html = renderPresentation({
    type: 'mail',
    ref: 'c1',
    de: 'Ana <ana@sbc.test>',
    para: ['rrhh@sbc.test'],
    asunto: 'Contrato adjunto',
    recibido: '2026-10-19T10:00:00Z',
    texto: 'Hola,\n\nTe adjunto el contrato firmado.',
    adjuntos: [
      { nombre: 'contrato.pdf', contenido: 'Clausula...', url: '/api/mail/attachment/msg-1/att-1' },
    ],
  });
  assert.match(html, /Contrato adjunto/);
  assert.match(html, /Ana &lt;ana@sbc\.test&gt;/);
  assert.match(html, /rrhh@sbc\.test/);
  assert.match(html, /Te adjunto el contrato firmado/);
  // Nunca un <a href> directo: la ruta exige token y un enlace normal no lo manda (daría 401).
  assert.match(html, /data-attachment-url="\/api\/mail\/attachment\/msg-1\/att-1"/);
  assert.doesNotMatch(html, /<a[^>]*href="\/api\/mail\/attachment/);
  assert.match(html, /contrato\.pdf/);
  // El texto extraído del adjunto es para el LLM, nunca se vuelca en la tarjeta visible.
  assert.doesNotMatch(html, /Clausula/);
});

test('mail: an attachment without a download url (e.g. a forwarded email) never renders a dead link', () => {
  const html = renderPresentation({
    type: 'mail',
    de: 'Ana <ana@sbc.test>',
    asunto: 'Reenvío',
    texto: 'Mensaje reenviado',
    adjuntos: [{ nombre: 'correo reenviado', contenido: null, url: null }],
  });
  assert.doesNotMatch(html, /<a[^>]*href/);
  assert.match(html, /correo reenviado/);
});

test('mail_thread: lists every message with sender, subject and unread/attachment flags', () => {
  const html = renderPresentation({
    type: 'mail_thread',
    title: 'Hilo: Vacaciones de agosto',
    mensajes_en_el_hilo: 2,
    mail_rows: [
      { ref: 'c1', from: 'Ana <ana@sbc.test>', subject: 'Vacaciones de agosto', received_at: '2026-10-18T09:00:00Z',
        has_attachments: false, preview: 'Quería pedir...', is_read: true, no_reply: false },
      { ref: 'c2', from: 'RRHH <rrhh@sbc.test>', subject: 'Re: Vacaciones de agosto', received_at: '2026-10-19T09:00:00Z',
        has_attachments: true, preview: 'Confirmado, adjunto...', is_read: false, no_reply: false },
    ],
  });
  assert.match(html, /Hilo: Vacaciones de agosto/);
  assert.match(html, /2 mensajes en esta conversación/);
  assert.match(html, /Ana &lt;ana@sbc\.test&gt;/);
  assert.match(html, /RRHH &lt;rrhh@sbc\.test&gt;/);
  assert.match(html, /mia-mail-thread-item--unread/);
  assert.match(html, /Con adjuntos/);
});

test('table with mail_rows: renders a mail list with open/reply actions, not a generic table', () => {
  const html = renderPresentation({
    type: 'table',
    title: 'Correos recientes',
    columns: ['Ref', 'De', 'Asunto', 'Recibido'],
    rows: [['c1', 'Ana <ana@sbc.test>', 'Vacaciones de agosto', '2026-10-18T09:00:00Z']],
    mail_rows: [
      { ref: 'c1', from: 'Ana <ana@sbc.test>', subject: 'Vacaciones de agosto', received_at: '2026-10-18T09:00:00Z',
        has_attachments: false, preview: 'Quería pedir...', is_read: true, no_reply: false },
      { ref: 'c2', from: 'noreply@sbc.test', subject: 'Aviso automático', received_at: '2026-10-19T09:00:00Z',
        has_attachments: false, preview: '', is_read: false, no_reply: true },
    ],
  });
  assert.match(html, /mia-mail-list/);
  assert.match(html, /data-mail-action="open" data-mail-ref="c1"/);
  assert.match(html, /data-mail-action="reply" data-mail-ref="c1"/);
  // Correo automático (no-reply): el botón de responder debe quedar deshabilitado.
  assert.match(html, /data-mail-action="reply" data-mail-ref="c2"[^>]*disabled/);
  // Nunca la tabla genérica (sin esto, caía en el renderer de "comparativa"/estadísticas).
  assert.doesNotMatch(html, /<table/);
});

test('mail_draft: shows the drafted text and whether sending is enabled', () => {
  const html = renderPresentation({
    type: 'mail_draft',
    borrador: 'b1',
    texto: 'Gracias por tu mensaje, te confirmo la recepción.',
    envio_habilitado: true,
  });
  assert.match(html, /Gracias por tu mensaje/);
  assert.match(html, /Confírmalo para enviarlo/);
});

test('mail_draft: says sending is disabled when envio_habilitado is false', () => {
  const html = renderPresentation({ type: 'mail_draft', texto: 'Texto', envio_habilitado: false });
  assert.match(html, /envío de correos está desactivado/);
});

test('statistical-visuals: a mail_rows table is never picked up as metric/comparison data', () => {
  const presentation = {
    type: 'table',
    title: 'Correos recientes',
    columns: ['Ref', 'De', 'Asunto', 'Recibido'],
    rows: Array.from({ length: 5 }, (_, i) => [`c${i}`, 'Ana', `Asunto ${i}`, '2026-10-18']),
    mail_rows: Array.from({ length: 5 }, (_, i) => ({ ref: `c${i}`, from: 'Ana', subject: `Asunto ${i}` })),
  };
  const result = buildStatisticalPresentation([presentation], { query: 'mis correos' });
  assert.equal(result.html, '');
  assert.equal(result.dataFirst, false);
});
