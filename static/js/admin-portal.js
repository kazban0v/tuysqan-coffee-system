'use strict';
(() => {
 const sidebar=document.getElementById('ap-sidebar');if(!sidebar)return;
 const toggle=document.getElementById('ap-nav-toggle'),close=document.getElementById('ap-nav-close'),backdrop=document.getElementById('ap-nav-backdrop'),mobile=matchMedia('(max-width:900px)');
 let opened=false;
 function setOpen(value,focus=true){
  opened=Boolean(value&&mobile.matches);
  document.body.classList.toggle('ap-nav-is-open',opened);
  toggle.setAttribute('aria-expanded',String(opened));
  backdrop.hidden=!opened;sidebar.inert=mobile.matches&&!opened;
  document.getElementById('main').inert=opened;
  document.querySelector('.ap-topbar').inert=opened;
  if(focus){if(opened)(sidebar.querySelector('[aria-current="page"]')||close).focus();else if(mobile.matches)toggle.focus();}
 }
 toggle.addEventListener('click',()=>setOpen(!opened));
 close.addEventListener('click',()=>setOpen(false));
 backdrop.addEventListener('click',()=>setOpen(false));
 mobile.addEventListener('change',()=>setOpen(false,false));
 document.addEventListener('keydown',event=>{
  if(!opened)return;
  if(event.key==='Escape'){event.preventDefault();setOpen(false);return;}
  if(event.key!=='Tab')return;
  const items=[...sidebar.querySelectorAll('a[href],button:not([disabled])')].filter(el=>el.getClientRects().length);
  if(!items.length)return;
  const first=items[0],last=items[items.length-1];
  if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}
  else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}
 });
 setOpen(false,false);
 document.querySelectorAll('[data-ap-confirm]').forEach(form=>form.addEventListener('submit',event=>{
  const message=document.documentElement.lang==='kk'?form.dataset.apConfirmKz||form.dataset.apConfirm:form.dataset.apConfirm;
  if(message&&!window.confirm(message))event.preventDefault();
 }));
})();
