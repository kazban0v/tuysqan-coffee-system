'use strict';
// Image placeholders attach to actual image lifecycles, never to an artificial delay.
(() => {
 const observed=new WeakSet();
 function prepare(image){
  if(observed.has(image))return;observed.add(image);
  if(image.complete){if(image.naturalWidth===0&&image.getAttribute('src'))image.classList.add('ui-image-error');return}
  image.classList.add('ui-image-pending');
  function finish(){image.classList.remove('ui-image-pending');image.classList.toggle('ui-image-error',image.naturalWidth===0);image.removeEventListener('load',finish);image.removeEventListener('error',finish)}
  image.addEventListener('load',finish);image.addEventListener('error',finish);
 }
 function scan(root){if(root.nodeType!==1)return;if(root.matches('img'))prepare(root);root.querySelectorAll('img').forEach(prepare)}
 scan(document.documentElement);
 new MutationObserver(records=>records.forEach(record=>{
  record.addedNodes.forEach(scan);
  if(record.target.nodeType===1&&record.target.hasAttribute('data-initial-loading')&&!record.target.querySelector('.ui-skeleton')){
   record.target.removeAttribute('aria-busy');record.target.removeAttribute('data-initial-loading');
  }
 })).observe(document.body,{childList:true,subtree:true});
})();
