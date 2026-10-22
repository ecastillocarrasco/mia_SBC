import test from 'node:test';
import assert from 'node:assert/strict';
import { adaptHologramResult } from '../src/worlds/hologram/hologram-results-v521.js';

test('hologram: an opened mail message shows sender, body and attachment download links', () => {
  const presentations = [{
    type: 'mail',
    de: 'Ana <ana@sbc.test>',
    asunto: 'Contrato adjunto',
    recibido: '2026-10-19T10:00:00Z',
    texto: 'Te adjunto el contrato firmado.',
    adjuntos: [{ nombre: 'contrato.pdf', contenido: 'texto extraído', url: '/api/mail/attachment/msg-1/att-1' }],
  }];
  const result = adaptHologramResult({ answer: 'Aquí tienes el correo.' }, presentations, { type: 'document', fan: false });
  assert.equal(result.hasPayload, true);
  assert.match(result.html, /Contrato adjunto/);
  assert.match(result.html, /Te adjunto el contrato firmado/);
  assert.match(result.html, /href="\/api\/mail\/attachment\/msg-1\/att-1"/);
  assert.match(result.html, /contrato\.pdf/);
  assert.doesNotMatch(result.html, /texto extra[ií]do/);
});

test('hologram: mail content never reaches the physical fan projection', () => {
  const presentations = [{ type: 'mail', de: 'Ana', asunto: 'Privado', texto: 'Datos personales sensibles' }];
  const result = adaptHologramResult({ answer: 'Listo.' }, presentations, { type: 'document', fan: true });
  assert.doesNotMatch(result.html, /Datos personales sensibles/);
});

test('hologram: a full thread lists every message with sender and subject', () => {
  const presentations = [{
    type: 'mail_thread',
    title: 'Hilo: Vacaciones',
    mail_rows: [
      { from: 'Ana <ana@sbc.test>', subject: 'Vacaciones', is_read: true },
      { from: 'RRHH <rrhh@sbc.test>', subject: 'Re: Vacaciones', is_read: false },
    ],
  }];
  const result = adaptHologramResult({ answer: 'Aquí tienes el hilo.' }, presentations, { type: 'document', fan: false });
  assert.match(result.html, /Hilo: Vacaciones/);
  assert.match(result.html, /Ana &lt;ana@sbc\.test&gt;/);
  assert.match(result.html, /RRHH &lt;rrhh@sbc\.test&gt;/);
  assert.match(result.html, /hg-mail-thread-item--unread/);
});
