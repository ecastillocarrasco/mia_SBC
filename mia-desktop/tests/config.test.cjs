'use strict';
const assert = require('node:assert/strict');
const test = require('node:test');
const { DEFAULTS, normalizeConfig, placeNear, clamp } = require('../src/config.cjs');
test('normaliza ausencia de configuracion', () => {
  assert.deepEqual(normalizeConfig(), { ...DEFAULTS });
});
test('rechaza atajo invalido y valores excesivos, permite consentimiento de voz explicito', () => {
  const x = normalizeConfig({ shortcut: 'bad; rm -rf', avatarWidth: 999, avatarHeight: -1, wakePhraseEnabled: true });
  assert.equal(x.shortcut, DEFAULTS.shortcut);
  assert.equal(x.avatarWidth, DEFAULTS.avatarWidth);
  assert.equal(x.avatarHeight, DEFAULTS.avatarHeight);
  assert.equal(x.wakePhraseEnabled, true);
  assert.equal(normalizeConfig().wakePhraseEnabled, false);
});
test('acepta personalizacion valida', () => {
  const x = normalizeConfig({ shortcut: 'Control+Shift+F8', avatarWidth: 330, avatarHeight: 455, alwaysOnTop: false, launchAtLogin: true });
  assert.equal(x.shortcut, 'Control+Shift+F8');
  assert.equal(x.avatarWidth, 330);
  assert.equal(x.launchAtLogin, true);
});
test('situa ventana secundaria dentro del area de trabajo, incluso en monitor con origen negativo', () => {
  const screen = { x: -1920, y: -100, width: 1920, height: 1040 };
  const anchor = { x: -1700, y: 400, width: 250, height: 345 };
  const pos = placeNear(anchor, {width:400,height:345}, screen);
  assert(pos.x >= screen.x && pos.x <= screen.x + screen.width - 400);
  assert(pos.y >= screen.y && pos.y <= screen.y + screen.height - 345);
});
test('clamp conserva limites', () => {
  assert.equal(clamp(-10, 0, 20), 0);
  assert.equal(clamp(30, 0, 20), 20);
});
