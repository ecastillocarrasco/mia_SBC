'use strict';
// Desired visibility is independent of Electron show/hide and asynchronous load events.
class VisibilityGate {
  constructor(){ this.hidden=false;this.lastHidden=0; }
  hide(now=Date.now()){this.hidden=true;this.lastHidden=now;}
  show(){this.hidden=false;}
  canAutoShow(){return !this.hidden;}
  acceptVoiceShow(now=Date.now()){return now-this.lastHidden>=1300;}
}
module.exports={VisibilityGate};
