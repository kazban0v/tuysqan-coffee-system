'use strict';
(() => {
 const preview=data('mascot-preview-data');
 let order=preview||currentGuestOrder||data('order-data');
 if(!order)return;
 const wishState=state=>['waiting','preparing'].includes(state);
 const copy={
  waiting:{ru:'Пока ожидаете заказ, можете рассказать нам, что хотели бы улучшить.',kz:'Тапсырысыңызды күтіп отырғанда, нені жақсартуға болатыны туралы ұсыныс қалдыра аласыз.',buttonRu:'Оставить пожелание',buttonKz:'Ұсыныс қалдыру'},
  preparing:{ru:'Ваш заказ готовится! ☕ Пока ожидаете, можете рассказать нам, что хотели бы улучшить',kz:'Тапсырысыңыз дайындалып жатыр! ☕ Күтіп отырған кезде нені жақсартуға болатыны туралы пікіріңізді бөлісе аласыз',buttonRu:'Оставить пожелание',buttonKz:'Ұсыныс қалдыру'},
  served:{ru:'Приятного аппетита! ❤️ Будем рады узнать, как вам наш сервис',kz:'Ас дәмді болсын! ❤️ Қызмет көрсетуіміз туралы пікіріңізді білгіміз келеді',buttonRu:'Оценить обслуживание',buttonKz:'Қызметті бағалау'},
  feedback:{ru:'Ну как вам у нас? Что понравилось больше всего?',kz:'Бізде болғаныңыз ұнады ма? Сізге ең қатты не ұнады?',buttonRu:'Поделиться впечатлением',buttonKz:'Әсеріңізбен бөлісу'}
 };
 const storageKey='tuysqan-mascot-dismissed-'+order.public_id;
 const readDismissed=()=>{try{return !preview&&sessionStorage.getItem(storageKey)==='1'}catch{return false}};
 let dismissed=readDismissed(),currentState=null,formState=null,saving=false,thanks=null,dismissRequest=false,connectionOK=navigator.onLine;
 const widget=document.createElement('aside');widget.className='griffin-widget';widget.hidden=true;widget.setAttribute('aria-label',tr('Помощник Tuysqan','Tuysqan көмекшісі'));
 widget.innerHTML='<img class="griffin-character" src="/static/mascot/tuysqan-griffin.png" alt="" width="1254" height="1254"><div class="griffin-card"><div class="griffin-top"><span>TUYSQAN COFFEE</span><button type="button" class="griffin-close" aria-label="Закрыть приглашение / Ұсынысты жабу">×</button></div><p class="griffin-message" role="status" aria-live="polite"></p><p class="griffin-network" role="status" hidden></p><button type="button" class="griffin-action"></button></div>';
 if(preview&&window.TuysqanGriffinRig){const image=widget.querySelector('.griffin-character'),rig=document.createElement('div');rig.className='griffin-character griffin-rig-character';image.replaceWith(rig)}
 document.body.append(widget);
 const dialog=document.createElement('dialog');dialog.className='griffin-form-dialog';dialog.setAttribute('aria-labelledby','griffin-form-title');document.body.append(dialog);
 function showThanks(kind){thanks=kind;widget.hidden=false;widget.dataset.state='thanks';widget.querySelector('.griffin-message').textContent=kind==='wish'?tr('Спасибо! Ваше пожелание передано кофейне.','Рақмет! Ұсынысыңыз кофеханаға жіберілді.'):tr('Спасибо за отзыв! Нам важно ваше мнение.','Пікіріңізге рақмет! Сіздің ойыңыз біз үшін маңызды.');widget.querySelector('.griffin-action').hidden=true}
 async function persistDismissal(){
  if(preview||dismissRequest||order.mascot?.dismissed)return;
  dismissRequest=true;
  try{await api('/api/orders/'+order.public_id+'/mascot/',{action:'dismiss'});order.mascot.dismissed=true}catch{}finally{dismissRequest=false}
 }
 function mountWidget(){
  const status=$('#guest-status-window'),slot=$('#guest-status-mascot-slot');
  const inline=!!(status?.open&&slot);
  if(inline&&widget.parentElement!==slot)slot.append(widget);
  if(!inline&&widget.parentElement!==document.body)document.body.append(widget);
  widget.classList.toggle('is-in-status',inline);
 }
 function render(){
  mountWidget();
  const network=widget.querySelector('.griffin-network');network.hidden=connectionOK;network.textContent=tr('Нет связи. Обновим статус после подключения.','Байланыс жоқ. Қосылғаннан кейін күй жаңартылады.');
  widget.setAttribute('aria-label',tr('Помощник Tuysqan','Tuysqan көмекшісі'));
  if(dismissed||order.mascot?.dismissed){widget.hidden=true;return}
  if(thanks){showThanks(thanks);return}
  const state=order.mascot?.state;
  if(!copy[state]||order.mascot?.review_sent||wishState(state)&&order.mascot?.wish_sent){widget.hidden=true;currentState=null;return}
  if(currentState!==state){if(preview&&window.TuysqanGriffinRig)window.TuysqanGriffinRig.mount(widget.querySelector('.griffin-rig-character'),state);widget.dataset.state=state;widget.classList.remove('is-entering');requestAnimationFrame(()=>widget.classList.add('is-entering'))}
  currentState=state;widget.hidden=false;
  widget.querySelector('.griffin-message').textContent=copy[state][lang];
  const action=widget.querySelector('.griffin-action');action.hidden=false;action.textContent=tr(copy[state].buttonRu,copy[state].buttonKz);
 }
 function formTitle(){return wishState(formState)?tr('Ваше пожелание','Ұсынысыңыз'):formState==='served'?tr('Как вам обслуживание?','Қызмет көрсету ұнады ма?'):tr('Ваши впечатления','Әсеріңіз')}
 function renderForm(preserve=false){
  const previous=preserve?new FormData(dialog.querySelector('form')):null;
  const wish=wishState(formState);
  dialog.innerHTML=`<div class="griffin-form-top"><div><span>TUYSQAN COFFEE</span><h2 id="griffin-form-title">${formTitle()}</h2></div><button type="button" class="griffin-close" data-griffin-form-close aria-label="${tr('Закрыть','Жабу')}">×</button></div><form><fieldset class="griffin-rating" ${wish?'hidden':''}><legend>${tr('Ваша оценка','Бағаңыз')}</legend>${[1,2,3,4,5].map(n=>`<label><input type="radio" name="rating" value="${n}" ${wish?'':'required'}><span>${n}<small aria-hidden="true">★</small></span><span class="griffin-sr-only">${n} ${tr('из 5','/ 5')}</span></label>`).join('')}</fieldset><label class="griffin-comment"><span>${wish?tr('Что хотели бы улучшить?','Нені жақсартуға болады?'):tr('Комментарий — по желанию','Пікір — міндетті емес')}</span><textarea name="comment" rows="4" maxlength="${wish?1000:2000}" ${wish?'required':''}></textarea></label><p class="griffin-form-error" role="alert"></p><button type="submit" class="griffin-submit">${tr('Отправить','Жіберу')}</button></form>`;
  if(previous){dialog.querySelector('textarea').value=previous.get('comment')||'';const rating=previous.get('rating');if(rating)dialog.querySelector(`[name=rating][value="${rating}"]`).checked=true}
 }
 function closeForm(){if(!saving)dialog.close()}
 function openForm(){if(!currentState||saving)return;formState=currentState;renderForm();dialog.showModal()}
 widget.querySelector('.griffin-action').addEventListener('click',openForm);
 widget.querySelector('.griffin-close').addEventListener('click',()=>{dismissed=true;widget.hidden=true;try{if(!preview)sessionStorage.setItem(storageKey,'1')}catch{}persistDismissal()});
 dialog.addEventListener('click',event=>{if(event.target.closest('[data-griffin-form-close]'))closeForm()});
 dialog.addEventListener('cancel',event=>{if(saving)event.preventDefault()});
 dialog.addEventListener('close',()=>{if(!widget.hidden)widget.querySelector('.griffin-action').focus()});
 dialog.addEventListener('submit',async event=>{
  event.preventDefault();if(saving)return;
  const form=dialog.querySelector('form');if(!form.reportValidity())return;
  const values=new FormData(form),wish=wishState(formState),comment=String(values.get('comment')||'').trim();
  if(wish&&!comment){dialog.querySelector('.griffin-form-error').textContent=tr('Напишите ваше пожелание.','Ұсынысыңызды жазыңыз.');return}
  saving=true;form.querySelectorAll('button,input,textarea').forEach(el=>el.disabled=true);
  dialog.querySelector('.griffin-form-error').textContent='';
  try{
   if(!preview){if(wish)await api('/api/orders/'+order.public_id+'/mascot/',{action:'wish',comment});else await api('/api/orders/'+order.public_id+'/review/',{rating:Number(values.get('rating')),comment,kind:formState==='served'?'service':'experience'})}
   dialog.close();if(wish){order.mascot.wish_sent=true;showThanks('wish')}else{order.mascot.review_sent=true;showThanks('review')}
  }catch(error){dialog.querySelector('.griffin-form-error').textContent=error.message}
  finally{saving=false;form.querySelectorAll('button,input,textarea').forEach(el=>el.disabled=false)}
 });
 function update(next){
  // A suggestion thank-you should not suppress the invitation after serving.
  if(thanks==='wish'&&order.status!==next.status)thanks=null;
  order=next;
  if(dismissed&&!order.mascot?.dismissed)persistDismissal();
  if(dialog.open&&!saving&&(order.mascot?.review_sent||order.mascot?.dismissed||wishState(formState)&&!['new','accepted','preparing','ready'].includes(order.status)))dialog.close();
  render();
 }
 window.addEventListener('guest-order-updated',event=>update(event.detail));
 window.addEventListener('guest-status-visibility',()=>mountWidget());
 $$('[data-set-language]').forEach(button=>button.addEventListener('click',()=>{render();if(dialog.open&&!saving)renderForm(true)}));
 window.addEventListener('guest-order-connection',event=>{connectionOK=event.detail.online;render()});
 window.addEventListener('online',()=>{if(dismissed)persistDismissal()});
 if(dismissed)persistDismissal();render();
})();
