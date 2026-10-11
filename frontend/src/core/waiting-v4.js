import { friendlyProgress } from "./progress-language-v42.js";

/** Meaningful wait feedback. Never invent percentages, tools, or completed steps. */
export const WAIT_MILESTONES = Object.freeze([
  { seconds: 7, text: 'Sigo con tu consulta. Te aviso en cuanto tenga la información.' },
  { seconds: 18, text: 'La solicitud continúa en curso. Gracias por esperar.' },
  { seconds: 35, text: 'Está tardando un poquito más de lo habitual. Sigo pendiente del resultado.' },
  { seconds: 65, text: 'Todavía estoy esperando la respuesta. No necesitas repetir tu pregunta.' },
  { seconds: 120, text: 'Sigo aquí contigo. La consulta todavía no ha terminado.' },
  { seconds: 210, text: 'Continuamos esperando el resultado. Te informaré cuando esté disponible.' },
]);

export function waitMessage(seconds, milestones = WAIT_MILESTONES) {
  let message = 'Estoy tramitando tu solicitud.';
  for (const milestone of milestones) {
    if (seconds >= milestone.seconds) message = milestone.text;
    else break;
  }
  return message;
}

export class MiaWaitingV4 {
  constructor({ onUpdate, onClear, clock = () => Date.now(), interval = 1000 } = {}) {
    this.onUpdate = onUpdate;
    this.onClear = onClear;
    this.clock = clock;
    this.interval = interval;
    this.timer = null;
    this.startedAt = 0;
    this.lastDisplayed = '';
    this.latestBackend = '';
    this.latestBackendAt = 0;
    this.active = false;
  }
  start() {
    this.stop();
    this.active = true;
    this.startedAt = this.clock();
    this._show('Estoy tramitando tu solicitud.', 0);
    this.timer = setInterval(() => this.tick(), this.interval);
  }
  progress(message) {
    if (!this.active) return;
    const value = friendlyProgress(message).slice(0, 220);
    if (!value) return;
    this.latestBackend = value;
    this.latestBackendAt = this.clock();
    this._show(value, (this.clock() - this.startedAt) / 1000);
  }
  _show(message, seconds) {
    if (this.lastDisplayed === message) return;
    this.lastDisplayed = message;
    this.onUpdate?.(message, seconds);
  }
  tick() {
    if (!this.active) return;
    const seconds = Math.max(0, (this.clock() - this.startedAt) / 1000);
    // Backend progress is grounded; allow its message time to be read.
    if (this.latestBackend && this.clock() - this.latestBackendAt < 12000) return;
    this._show(waitMessage(seconds), seconds);
  }
  stop() {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
    this.active = false;
    this.lastDisplayed = '';
    this.latestBackend = '';
    this.onClear?.();
  }
}
