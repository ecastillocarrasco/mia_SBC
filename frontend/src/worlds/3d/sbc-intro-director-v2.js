/** Decorative parallax only. Does not touch audio, GLB, rig, or other worlds. */
export class SbcIntroDirectorV2 {
  constructor(node, { reducedMotion = false } = {}) {
    this.node = node;
    this.stage = node?.querySelector('[data-sbc-scene]') ?? null;
    this.reducedMotion = reducedMotion;
    this.raf = 0;
    this.currentX = 0;
    this.currentY = 0;
    this.targetX = 0;
    this.targetY = 0;
    this.active = Boolean(this.stage) && !reducedMotion;
    this.pointer = (event) => {
      if (!this.active || !this.node?.isConnected) return;
      const x = (event.clientX / window.innerWidth - .5) * 2;
      const y = (event.clientY / window.innerHeight - .5) * 2;
      this.targetY = Math.max(-1, Math.min(1, x)) * 2.0;
      this.targetX = Math.max(-1, Math.min(1, -y)) * 1.3;
      if (!this.raf) this.raf = requestAnimationFrame(() => this.tick());
    };
    this.reset = () => { this.targetX = this.targetY = 0; if (!this.raf && this.active) this.raf = requestAnimationFrame(() => this.tick()); };
    this.visibility = () => { if (document.hidden) this.reset(); };
    if (this.active) {
      window.addEventListener('pointermove', this.pointer, { passive: true });
      window.addEventListener('blur', this.reset);
      document.addEventListener('visibilitychange', this.visibility);
    }
  }
  tick() {
    this.raf = 0;
    if (!this.active || !this.node?.isConnected) return;
    this.currentX += (this.targetX - this.currentX) * .17;
    this.currentY += (this.targetY - this.currentY) * .17;
    this.stage.style.setProperty('--look-x', `${this.currentX.toFixed(2)}deg`);
    this.stage.style.setProperty('--look-y', `${this.currentY.toFixed(2)}deg`);
    if (Math.abs(this.targetX-this.currentX) > .08 || Math.abs(this.targetY-this.currentY) > .08)
      this.raf = requestAnimationFrame(() => this.tick());
  }
  dispose() {
    this.active = false;
    if (this.raf) cancelAnimationFrame(this.raf);
    window.removeEventListener('pointermove',this.pointer);
    window.removeEventListener('blur',this.reset);
    document.removeEventListener('visibilitychange',this.visibility);
    this.raf = 0;
  }
}
