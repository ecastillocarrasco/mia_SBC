'use strict';
function refreshBrandLogo(){
  for(const im of document.querySelectorAll('[data-sbc-logo]')){
    const wrapper=im.closest('[data-sbc-wrap]');
    im.onload=()=>{im.style.visibility='visible';wrapper?.classList.add('has-brand');};
    im.onerror=()=>{im.style.visibility='hidden';wrapper?.classList.remove('has-brand');};
    im.src='mia://assets/sunset-logo.png?v='+Date.now();
  }
  for(const im of document.querySelectorAll('[data-mia-logo]')){
    const fallback='../../assets/branding/mia-wordmark.svg';
    im.onerror=()=>{im.onerror=null;im.src=fallback;};
    im.src='mia://assets/mia-logo.png?v='+Date.now();
  }
}
refreshBrandLogo();
window.miaDesktop.onBrandingReady(refreshBrandLogo);
