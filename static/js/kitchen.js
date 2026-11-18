'use strict';
(() => {
 const board=document.getElementById('kitchen-board');if(!board)return;
 const el=id=>document.getElementById(id),t=(ru,kz)=>document.documentElement.lang==='kk'?kz:ru;
 const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const food=o=>(o.items||[]).filter(i=>i.kind==='food');
 const stage=o=>food(o).length&&food(o).every(i=>i.status==='ready')?'ready':food(o).some(i=>i.status==='preparing')?'preparing':'waiting';
 const label=s=>s==='ready'?t('Готовы','Дайын'):s==='preparing'?t('Готовятся','Дайындалуда'):t('Ожидают','Күтуде');
 const seenKey='tuysqan-kitchen-seen-v1:'+board.dataset.actor;
 let orders=JSON.parse(el('kitchen-initial-orders')?.textContent||'[]'),filter='all',seen;
 try{seen=new Set(JSON.parse(sessionStorage.getItem(seenKey)||'[]'))}catch{seen=new Set()}
 orders.forEach(o=>seen.add(o.public_id));
 const persistSeen=()=>{try{sessionStorage.setItem(seenKey,JSON.stringify([...seen].slice(-2000)))}catch{}};
 persistSeen();
 let busy=false,changing=false,timer,updated=null,connected=true,lastArrivalCount=0;
 const fresh=new Set(),pending=new Set(),audio=new Audio(board.dataset.soundUrl);
 audio.preload='auto';
 let sound=false,playing=false,audioQueue=[],audioDone=null;
 function soundUI(message){
  el('kitchen-sound-toggle').setAttribute('aria-pressed',String(sound));
  el('kitchen-sound-toggle').textContent=sound?t('Звук включён','Дыбыс қосулы'):t('Включить звук','Дыбысты қосу');
  el('kitchen-sound-status').textContent=message||(sound?t('Голос для новых заказов','Жаңа тапсырыстарға дауыс'):t('Нажмите, чтобы слышать новые заказы','Жаңа тапсырыстарды есту үшін басыңыз'));
 }
 function stopAudio(){audioQueue=[];audio.pause();if(audioDone)audioDone();playing=false;}
 async function playPhrase(){
  playing=true;audio.currentTime=0;
  let end;
  const ended=new Promise((resolve,reject)=>{
   let watchdog;const failed=()=>end(new Error('Audio unavailable'));
   end=error=>{clearTimeout(watchdog);audio.removeEventListener('ended',end);audio.removeEventListener('error',failed);audioDone=null;if(error instanceof Error)reject(error);else resolve()};
   audioDone=end;audio.addEventListener('ended',end,{once:true});audio.addEventListener('error',failed,{once:true});watchdog=setTimeout(()=>{audio.pause();failed()},15000);
  });
  try{await Promise.all([audio.play(),ended])}catch{end();sound=false;audioQueue=[];soundUI(t('Звук недоступен. Нажмите ещё раз или проверьте громкость.','Дыбыс қолжетімсіз. Қайта басыңыз немесе дыбыс деңгейін тексеріңіз.'))}
  finally{playing=false;if(sound&&audioQueue.length){audioQueue.shift();void playPhrase()}}
 }
 function announce(incoming){
  if(!incoming.length)return;
  incoming.forEach(o=>fresh.add(o.public_id));
  lastArrivalCount=incoming.length;
  el('kitchen-announcement').textContent=t('Новых заказов: ','Жаңа тапсырыстар: ')+lastArrivalCount;
  if(sound){audioQueue.push(...incoming.map(o=>o.public_id));if(!playing){audioQueue.shift();void playPhrase()}}
 }
 function remember(next){const incoming=next.filter(o=>!seen.has(o.public_id));next.forEach(o=>seen.add(o.public_id));persistSeen();announce(incoming)}
 function eta(o){
  if(stage(o)==='ready')return t('Блюда готовы','Тағамдар дайын');
  if(!o.eta_at)return t('Без времени','Уақыты көрсетілмеген');
  const minutes=Math.ceil((new Date(o.eta_at)-Date.now())/60000);
  return minutes>0?t('Осталось ','Қалды ')+minutes+t(' мин',' мин'):minutes===0?t('Плановое время готовности наступило','Жоспарлы дайындық уақыты келді'):t('Задержка ','Кешігу ')+Math.abs(minutes)+t(' мин',' мин');
 }
 function chooseFoodTime(order){
  return new Promise(resolve=>{
   const dialog=document.createElement('dialog');dialog.className='kds-time-dialog';
   dialog.setAttribute('aria-label',t('Время приготовления блюд','Тағамдарды дайындау уақыты'));
   dialog.innerHTML=`<h2>${t('Плановая готовность блюд','Тағамдардың жоспарлы дайындығы')}</h2><p>${escape(order.number)} · ${escape(order.table)}</p><p>${t('Сколько минут осталось для каждого блюда?','Әр тағамға қанша минут қалды?')}</p><form class="kds-food-plan">${food(order).filter(i=>i.status!=='ready').map(i=>{const minutes=i.eta_at?Math.max(1,Math.ceil((new Date(i.eta_at)-Date.now())/60000)):'';return `<label><span>${i.quantity} × ${escape(i[document.documentElement.lang==='kk'?'name_kz':'name_ru']||i.name_ru)}</span><input type="number" min="1" max="180" step="1" data-food-id="${i.id}" data-original="${minutes}" value="${minutes}" placeholder="${t('Не назначено','Белгіленбеген')}"></label>`}).join('')}<p class="kds-plan-error" role="alert"></p><button type="submit" class="kds-action">${t('Сохранить план и готовить','Жоспарды сақтап дайындау')}</button></form><div class="kds-time-options">${[5,10,15,20,25,30].map(n=>`<button type="button" data-kds-fill="${n}">${n} ${t('мин всем','мин бәріне')}</button>`).join('')}</div><button type="button" class="kds-time-cancel" data-kds-no-time>${stage(order)==='waiting'?t('Начать без времени','Уақытсыз бастау'):t('Продолжить без изменения времени','Уақытты өзгертпей жалғастыру')}</button><button type="button" class="kds-time-cancel" data-kds-minutes="0">${t('Отмена','Бас тарту')}</button>`;
   let finished=false;
   const finish=value=>{if(finished)return;finished=true;dialog.close();dialog.remove();resolve(value)};
   dialog.addEventListener('click',event=>{const fill=event.target.closest('[data-kds-fill]');if(fill){dialog.querySelectorAll('[data-food-id]').forEach(input=>input.value=fill.dataset.kdsFill);return}if(event.target.closest('[data-kds-no-time]')){finish([]);return}if(event.target.closest('[data-kds-minutes]'))finish(null)});
   dialog.querySelector('form').addEventListener('submit',event=>{event.preventDefault();const rows=[...dialog.querySelectorAll('[data-food-id]')].filter(input=>input.value&&(stage(order)==='waiting'||input.value!==input.dataset.original)).map(input=>({item_id:Number(input.dataset.foodId),eta:Number(input.value)}));if(!rows.length){dialog.querySelector('.kds-plan-error').textContent=t('Измените время хотя бы одного блюда.','Кемінде бір тағамның уақытын өзгертіңіз.');return}finish(rows)});
   dialog.addEventListener('cancel',event=>{event.preventDefault();finish(null)});
   document.body.append(dialog);dialog.showModal();
  });
 }
 function connectionUI(){
  el('kitchen-connection').textContent=connected?t('На связи','Байланыс бар'):t('Нет связи · повторяем','Байланыс жоқ · қайталау');
  el('kitchen-connection').classList.toggle('is-offline',!connected);
  el('kitchen-updated').textContent=updated?t('Обновлено в ','Жаңартылды ')+updated.toLocaleTimeString(document.documentElement.lang,{hour:'2-digit',minute:'2-digit'}):t('Обновляем очередь…','Кезек жаңартылуда…');
 }
 function render(){
  ['all','waiting','preparing','ready'].forEach(key=>{el('kitchen-count-'+key).textContent=key==='all'?orders.length:orders.filter(o=>stage(o)===key).length});
  document.querySelectorAll('[data-kitchen-filter]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.kitchenFilter===filter)));
  const visible=orders.filter(o=>filter==='all'||stage(o)===filter);
  if(lastArrivalCount)el('kitchen-announcement').textContent=t('Новых заказов: ','Жаңа тапсырыстар: ')+lastArrivalCount;
  board.innerHTML=visible.map(o=>{
   const state=stage(o),late=state!=='ready'&&(o.is_delayed||(o.eta_at&&new Date(o.eta_at)<Date.now()));
   const table=o.table==='С собой'?t('С собой','Өзіңізбен'):document.documentElement.lang==='kk'?o.table.replace(/^Стол /,'Үстел '):o.table;
   const at=o.created_at?new Date(o.created_at).toLocaleTimeString(document.documentElement.lang,{hour:'2-digit',minute:'2-digit'}):'';
   return `<article class="kds-card is-${state}${late?' is-delayed':''}${fresh.has(o.public_id)?' is-new':''}" data-order-id="${escape(o.public_id)}"><div class="kds-card-head"><h2 class="kds-number">${escape(o.number)}</h2><span class="kds-status">${label(state)}</span></div><div class="kds-card-meta"><strong>${escape(table)}</strong><time datetime="${escape(o.created_at||'')}">${at}</time></div><ul class="kds-items">${food(o).map(i=>`<li><span class="kds-qty">${i.quantity}×</span><div><span class="kds-item-name">${escape(i[document.documentElement.lang==='kk'?'name_kz':'name_ru']||i.name_ru)}</span>${i.comment?`<p class="kds-item-note">${escape(i.comment)}</p>`:''}<span class="kds-item-status">${i.status==='ready'?t('Готово','Дайын'):i.status==='preparing'?t('Готовится','Дайындалуда'):t('В очереди','Кезекте')}</span>${i.eta_at&&i.status!=='ready'?`<small class="kds-item-eta">${t('Плановая готовность: ','Жоспарлы дайындық: ')}${new Date(i.eta_at).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'})}</small>`:''}${i.status!=='ready'?`<button type="button" class="kds-item-ready" data-kitchen-action="item_ready" data-kitchen-id="${escape(o.public_id)}" data-item-id="${i.id}">${t('Это блюдо готово','Бұл тағам дайын')}</button>`:''}</div></li>`).join('')}</ul>${o.comment?`<p class="kds-comment">${escape(o.comment)}</p>`:''}<div class="kds-card-foot"><span class="kds-eta">${escape(eta(o))}</span>${state!=='ready'?`${state==='preparing'?`<button type="button" class="kds-time-edit" data-kitchen-action="eta" data-kitchen-id="${escape(o.public_id)}">${t('Изменить время блюд','Тағам уақытын өзгерту')}</button>`:''}<button type="button" class="kds-action${state==='waiting'?'':' secondary'}" data-kitchen-action="${state==='waiting'?'preparing':'ready'}" data-kitchen-id="${escape(o.public_id)}" ${pending.has(o.public_id)?'disabled':''}>${pending.has(o.public_id)?t('Сохраняем…','Сақталуда…'):state==='waiting'?t('Указать время и готовить','Уақытты белгілеп дайындау'):t('Блюда готовы','Тағамдар дайын')}</button>`:`<span class="kds-done">✓ ${t('Блюда готовы · кассир уведомлён','Тағамдар дайын · кассирге хабарланды')}</span>`}</div></article>`;
  }).join('')||`<div class="kds-empty"><h2>${orders.length?t('В этом разделе заказов нет','Бұл бөлімде тапсырыс жоқ'):t('Очередь пуста','Кезек бос')}</h2><p>${orders.length?t('Выберите другой статус.','Басқа күйді таңдаңыз.'):t('Новые заказы появятся здесь автоматически.','Жаңа тапсырыстар осында автоматты түрде пайда болады.')}</p></div>`;
  connectionUI();
 }
 async function request(url,payload){
  const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),12000);
  try{const response=await fetch(url,{method:payload?'POST':'GET',signal:controller.signal,cache:'no-store',headers:{'Content-Type':'application/json','X-CSRFToken':el('csrf-form').querySelector('input').value},body:payload?JSON.stringify(payload):undefined});let result;try{result=await response.json()}catch{throw Error(t('Не удалось получить ответ сервера.','Сервер жауабын алу мүмкін болмады.'))}if(!response.ok)throw Error(result.error||t('Не удалось обновить заказ.','Тапсырысты жаңарту мүмкін болмады.'));return result}
  finally{clearTimeout(timeout)}
 }
 function schedule(){clearTimeout(timer);timer=setTimeout(refresh,10000)}
 async function refresh(){
  if(busy||changing)return;clearTimeout(timer);busy=true;el('kitchen-refresh').disabled=true;
  try{const response=await request('/api/kitchen/');if(!Array.isArray(response.orders))throw Error(t('Некорректный ответ сервера','Сервер жауабы қате'));remember(response.orders);orders=response.orders;updated=new Date();connected=true;el('kitchen-error').textContent='';render()}
  catch(error){connected=false;el('kitchen-error').textContent=t('Не удалось обновить очередь. Показаны последние полученные заказы.','Кезек жаңартылмады. Соңғы алынған тапсырыстар көрсетілген.');connectionUI()}
  finally{busy=false;el('kitchen-refresh').disabled=false;schedule()}
 }
 board.addEventListener('click',async event=>{
  const button=event.target.closest('[data-kitchen-action]');if(!button||changing||busy)return;
  const order=orders.find(o=>o.public_id===button.dataset.kitchenId);if(!order)return;
  const action=button.dataset.kitchenAction;
  if(!['preparing','ready','eta','item_ready'].includes(action))return;
  let minutes=null;
  if(action==='preparing'||action==='eta'){
   changing=true;clearTimeout(timer);minutes=await chooseFoodTime(order);
   if(minutes===null){changing=false;schedule();return}
  }
  changing=true;clearTimeout(timer);pending.add(order.public_id);fresh.delete(order.public_id);button.disabled=true;el('kitchen-error').textContent='';let actionError='';
  try{
   // Explicit food IDs preserve the bar's drinks even when a manager uses this screen.
   if(action==='preparing'||action==='eta')await request('/api/staff/orders/'+order.public_id+'/action/',minutes.length?{action:'food_eta',items:minutes}:{action:'preparing'});
   else for(const item of food(order).filter(i=>i.status!=='ready'&&(action!=='item_ready'||i.id===Number(button.dataset.itemId))))await request('/api/staff/orders/'+order.public_id+'/action/',{action:'item_ready',item_id:item.id});
  }catch(error){actionError=error.name==='AbortError'?t('Ответ задерживается. Проверьте статус перед повтором.','Жауап кешігуде. Қайталаудан бұрын тапсырыс күйін тексеріңіз.'):error.message}
  finally{changing=false;pending.delete(order.public_id);await refresh();if(actionError)el('kitchen-error').textContent=actionError}
 });
 document.querySelectorAll('[data-kitchen-filter]').forEach(button=>button.addEventListener('click',()=>{filter=button.dataset.kitchenFilter;render()}));
 el('kitchen-refresh').addEventListener('click',refresh);
 el('kitchen-sound-toggle').addEventListener('click',()=>{if(sound){sound=false;stopAudio();soundUI()}else{sound=true;soundUI();void playPhrase()}});
 el('kitchen-sound-test').addEventListener('click',()=>{if(playing)return;sound=true;soundUI();void playPhrase()});
 document.querySelectorAll('[data-set-language]').forEach(button=>button.addEventListener('click',()=>{render();soundUI()}));
 window.addEventListener('online',refresh);window.addEventListener('offline',()=>{connected=false;connectionUI()});
 document.addEventListener('visibilitychange',()=>{if(!document.hidden)void refresh()});
 window.addEventListener('pagehide',()=>{clearTimeout(timer);stopAudio()});
 window.addEventListener('pageshow',event=>{if(event.persisted)void refresh()});
 render();soundUI();void refresh();
})();
