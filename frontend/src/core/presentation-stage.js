/**
 * PresentationStage coordinates only the visual staging of a presentation.
 * It never changes the response payload, presentation HTML, or business data.
 */
export class PresentationStage {
  constructor({ root = document.body, reducedMotion = false, mode = "3d" } = {}) {
    this.root = root;
    this.reducedMotion = reducedMotion;
    this.mode = mode;
    this.kind = "conversation";
    this.phase = "idle";
  }

  set(kind = "data", phase = "prepare") {
    this.kind = kind || "data";
    this.phase = phase || "prepare";
    this.root.dataset.stageKind = this.kind;
    this.root.dataset.stagePhase = this.phase;
    this.root.classList.toggle("presentation-stage-active", this.kind !== "conversation");
  }

  prepare(kind) {
    this.set(kind, "prepare");
  }

  reveal() {
    this.set(this.kind, "revealed");
  }

  speaking() {
    if (this.kind === "conversation") return;
    this.set(this.kind, "speaking");
  }

  settle() {
    if (this.kind === "conversation") return;
    this.set(this.kind, "settled");
  }

  reset() {
    this.kind = "conversation";
    this.phase = "idle";
    this.root.dataset.stageKind = "conversation";
    this.root.dataset.stagePhase = "idle";
    this.root.classList.remove("presentation-stage-active");
  }
}
