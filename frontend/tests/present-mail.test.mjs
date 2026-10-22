import test from 'node:test';
import assert from 'node:assert/strict';
import { renderPresentation } from '../src/core/present.js';

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
  assert.match(html, /href="\/api\/mail\/attachment\/msg-1\/att-1"/);
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
