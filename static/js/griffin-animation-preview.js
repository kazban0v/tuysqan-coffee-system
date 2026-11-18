'use strict';
(() => {
 const rig=window.TuysqanGriffinRig;if(!rig)return;
 document.querySelectorAll('[data-griffin-motion]').forEach(el=>rig.mount(el,el.dataset.griffinMotion));
 document.querySelectorAll('[data-griffin-layer]').forEach(el=>rig.mount(el,'preparing',el.dataset.griffinLayer,false));
 const modal=document.querySelector('#griffin-preview-modal');
 document.addEventListener('click',event=>{
  const replay=event.target.closest('[data-griffin-replay]');
  if(replay)rig.mount(document.querySelector(`[data-griffin-motion="${replay.dataset.griffinReplay}"]`),replay.dataset.griffinReplay);
  const show=event.target.closest('[data-griffin-modal]');
  if(show){rig.mount(modal.querySelector('.griffin-preview-hero'),show.dataset.griffinModal);modal.querySelector('h2').textContent=show.closest('.griffin-motion-card').querySelector('h2').textContent;modal.showModal()}
  if(event.target.closest('[data-griffin-preview-close]'))modal.close();
 });
})();
