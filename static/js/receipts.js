'use strict';
let receiptModal=null,receiptCurrentOrder=null;
const receiptMethod=value=>value==='cash'?tr('Наличные','Қолма-қол'):value==='kaspi'?'Kaspi QR':'Halyk';
const receiptDate=value=>value?new Date(value).toLocaleString('ru-RU',{day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit'}):'—';
function localizeReceipts(){const notice=$('#receipts-filter-status');if(notice?.dataset.found)notice.textContent=tr('Найдено: ','Табылды: ')+notice.dataset.found;document.querySelectorAll('[data-amount]').forEach(el=>el.textContent=money(el.dataset.amount));document.querySelectorAll('[data-label-ru]').forEach(el=>el.dataset.label=el.dataset[lang==='kz'?'labelKz':'labelRu']);$('#receipts-search').setAttribute('aria-label',tr('Поиск продаж','Сатуларды іздеу'));document.querySelectorAll('[data-sale-number]').forEach(el=>el.setAttribute('aria-label',tr(el.hasAttribute('data-receipt-open')?'Открыть продажу ':'Печать продажи ',el.hasAttribute('data-receipt-open')?'Сатуды ашу ':'Сатуды басып шығару ')+el.dataset.saleNumber));if(receiptCurrentOrder&&receiptModal?.open)renderReceiptDetail(receiptCurrentOrder)}
function renderReceiptDetail(o){if(!receiptModal)return;const history=o.payment_history||[];receiptModal.innerHTML=`<h2 id="receipt-detail-title">${tr('Продажа','Сату')} ${esc(o.number)}</h2><p class="receipt-meta">${receiptDate(o.created_at)} · ${o.source==='web'?'QR':tr('Касса','Касса')} · ${o.fulfillment==='takeaway'?tr('С собой','Өзімен алып кету'):esc(lang==='kz'?o.table.replace(/^Стол /,'Үстел '):o.table)}</p><div class="receipt-detail-summary">${Number(o.discount_amount)>0?`<div class="receipt-detail-before"><span>${tr('До скидки','Жеңілдікке дейін')}</span><strong>${money(o.subtotal)}</strong></div><div class="receipt-detail-discount"><span>${tr('Скидка','Жеңілдік')} ${esc(o.discount_percent)}%</span><strong>−${money(o.discount_amount)}</strong></div>`:''}<div class="receipt-detail-grand"><span>${tr('Итого по заказу','Тапсырыс сомасы')}</span><strong>${money(o.total)}</strong></div><div><span>${tr('Подтверждено сейчас','Қазір расталған')}</span><strong>${money(o.actual_paid)}</strong></div><div><span>${tr('Статус оплаты','Төлем күйі')}</span><span class="receipt-status status-${esc(o.payment_status)}">${state(o.payment_status)}</span></div></div><ul class="receipt-detail-items">${o.items.map(i=>`<li><span>${i.quantity} × ${esc(i['name_'+lang])}<small>${money(i.unit_price)} ${tr('за шт.','бір данаға')}</small></span><strong>${money(i.line_total)}</strong></li>`).join('')}</ul><h3 class="receipt-history-title">${tr('История оплат','Төлемдер тарихы')}</h3><div class="receipt-payment-history">${history.length?history.map(p=>`<section class="receipt-payment-entry ${p.reversed_at?'receipt-refunded':''}"><div><strong>${money(p.amount)} · ${receiptMethod(p.method)}</strong><span>${receiptDate(p.created_at)}</span></div>${p.method==='cash'?`<div><span>${tr('Получено от гостя','Қонақтан алынды')}</span><strong>${p.cash_received==null?'—':money(p.cash_received)}</strong></div><div><span>${tr('Сдача','Қайтарым')}</span><strong>${p.change==null?'—':money(p.change)}</strong></div>`:''}${p.reason?`<p>${tr('Причина расхождения: ','Айырмашылық себебі: ')}${esc(p.reason)}</p>`:''}${p.reversed_at?`<p><strong>${tr('Оплата отменена','Төлем қайтарылды')}</strong> · ${receiptDate(p.reversed_at)}</p><p>${esc(p.reversal_reason)}</p>`:`<p class="receipt-payment-active">${tr('Оплата подтверждена','Төлем расталды')}</p>`}</section>`).join(''):`<p class="receipt-meta">${tr('Подтверждённых оплат пока нет','Расталған төлемдер әзірге жоқ')}</p>`}</div><div class="cash-modal-actions"><button type="button" class="cash-btn" data-receipt-close>${tr('Закрыть','Жабу')}</button><a class="cash-btn ghost" href="/admin/cashier/?order=${o.public_id}">${tr('Открыть в кассе','Кассада ашу')}</a><a class="cash-btn primary" href="/admin/orders/${o.public_id}/print/" target="_blank" rel="noopener">${tr('Печать','Басып шығару')}</a></div>`;}
document.addEventListener('click',async event=>{if(event.target.closest('[data-receipt-close]')){receiptModal?.close();return}const button=event.target.closest('[data-receipt-open]');if(!button||receiptModal?.open)return;const dialog=document.createElement('dialog');dialog.className='cash-dialog receipt-detail-dialog';dialog.setAttribute('aria-labelledby','receipt-detail-title');dialog.innerHTML=`<h2 id="receipt-detail-title">${tr('Продажа','Сату')}</h2><p role="status">${tr('Загружаем…','Жүктелуде…')}</p><div class="ui-skeleton" aria-hidden="true">${[1,2,3].map(()=>'<div class="ui-skeleton-row"><div class="ui-skeleton-copy"><span class="ui-skeleton-block ui-skeleton-line heading"></span><span class="ui-skeleton-block ui-skeleton-line short"></span></div></div>').join('')}</div><button type="button" class="cash-btn" data-receipt-close>${tr('Закрыть','Жабу')}</button>`;receiptModal=dialog;receiptCurrentOrder=null;dialog.addEventListener('close',()=>{dialog.remove();if(receiptModal===dialog){receiptModal=null;receiptCurrentOrder=null}},{once:true});document.body.append(dialog);dialog.showModal();try{const response=await api('/api/staff/orders/'+encodeURIComponent(button.dataset.receiptOpen)+'/');if(!dialog.isConnected)return;receiptCurrentOrder=response.order;renderReceiptDetail(response.order)}catch(error){if(dialog.isConnected)dialog.innerHTML=`<h2 id="receipt-detail-title">${tr('Не удалось открыть продажу','Сатуды ашу мүмкін болмады')}</h2><p role="alert">${esc(error.message)}</p><button type="button" class="cash-btn" data-receipt-close>${tr('Закрыть','Жабу')}</button>`;}});
$$('[data-set-language]').forEach(button=>button.addEventListener('click',localizeReceipts));
localizeReceipts();

const receiptsForm=$('#receipts-filter-form'),receiptsSearch=$('#receipts-search');
let receiptsSearchTimer,receiptsRequest;
async function updateReceipts(){
 clearTimeout(receiptsSearchTimer);
 receiptsRequest?.abort();
 if(!receiptsForm.reportValidity())return;
 const start=receiptsForm.elements.start.value,end=receiptsForm.elements.end.value;
 const message=$('#receipts-filter-status');delete message.dataset.found;
 if(start&&end&&start>end){message.textContent=tr('Дата начала должна быть не позже даты окончания.','Басталу күні аяқталу күнінен кеш болмауы керек.');return}
 const controller=new AbortController();receiptsRequest=controller;
 const url=new URL(receiptsForm.action);url.search=new URLSearchParams(new FormData(receiptsForm)).toString();
 $('#receipts-results').setAttribute('aria-busy','true');
 message.textContent=tr('Ищем…','Ізделуде…');
 try{
  const response=await fetch(url,{signal:controller.signal,credentials:'same-origin',cache:'no-store'});
  if(!response.ok)throw new Error();
  const page=new DOMParser().parseFromString(await response.text(),'text/html');
  if(!page.querySelector('#receipts-results'))throw new Error();
  if(controller.signal.aborted)return;
  for(const selector of ['.receipts-metrics','#receipts-results','.receipts-periods'])document.querySelector(selector).replaceWith(page.querySelector(selector));
  history.replaceState(null,'',url);localize();localizeReceipts();
  const found=$('#receipts-results .receipts-results-heading>span');message.textContent=found?.textContent||'';message.dataset.found=found?.textContent.match(/\d+/)?.[0]||'0';
 }catch(error){if(error.name!=='AbortError')message.textContent=tr('Не удалось обновить продажи. Повторите поиск.','Сатуларды жаңарту мүмкін болмады. Қайта іздеңіз.')}finally{if(receiptsRequest===controller)$('#receipts-results').setAttribute('aria-busy','false')}
}
receiptsForm.addEventListener('submit',event=>{event.preventDefault();updateReceipts()});
receiptsSearch.addEventListener('input',event=>{
 clearTimeout(receiptsSearchTimer);receiptsRequest?.abort();$('#receipts-results').setAttribute('aria-busy','false');
 $('#receipts-filter-status').textContent='';delete $('#receipts-filter-status').dataset.found;
 if(event.isComposing)return;
 const query=receiptsSearch.value.trim();
 if(query.length===1)$('#receipts-filter-status').textContent=tr('Введите минимум 2 символа для поиска.','Іздеу үшін кемінде 2 таңба енгізіңіз.');
 if(query.length===0||query.length>=2)receiptsSearchTimer=setTimeout(updateReceipts,350);
});
receiptsSearch.addEventListener('compositionend',()=>receiptsSearch.dispatchEvent(new Event('input')));
receiptsForm.querySelectorAll('input[type=date],select').forEach(control=>control.addEventListener('change',()=>{
 if(control.type==='date')receiptsForm.elements.period.value='all';
 updateReceipts();
}));

// A shared calendar keeps both date controls consistent across browsers.
let receiptCalendar=null,receiptCalendarInput=null,receiptCalendarTrigger=null,receiptCalendarMonth=null;
const calendarISO=date=>date.getFullYear()+'-'+String(date.getMonth()+1).padStart(2,'0')+'-'+String(date.getDate()).padStart(2,'0');
const calendarParse=value=>{const [y,m,d]=value.split('-').map(Number);return new Date(y,m-1,d)};
function localizeReceiptDates(){
 document.querySelectorAll('[data-receipt-calendar]').forEach(button=>{
  const input=receiptsForm.elements[button.dataset.receiptCalendar];
  button.querySelector('span').textContent=input.value?input.value.split('-').reverse().join('.') : tr('Выбрать дату','Күнді таңдау');
  button.classList.toggle('has-value',!!input.value);
  button.setAttribute('aria-label',tr(button.dataset.receiptCalendar==='start'?'Дата начала: ':'Дата окончания: ',button.dataset.receiptCalendar==='start'?'Басталу күні: ':'Аяқталу күні: ')+button.querySelector('span').textContent);
 });
 if(receiptCalendar)renderReceiptCalendar();
}
function closeReceiptCalendar(focus=false){
 receiptCalendar?.remove();receiptCalendar=null;
 receiptCalendarTrigger?.setAttribute('aria-expanded','false');
 if(focus)receiptCalendarTrigger?.focus();
}
function renderReceiptCalendar(){
 const month=receiptCalendarMonth,year=month.getFullYear(),index=month.getMonth();
 const offset=(new Date(year,index,1).getDay()+6)%7,days=new Date(year,index+1,0).getDate();
 const selected=receiptCalendarInput.value,today=calendarISO(new Date());
 const weekdays=tr(['Пн','Вт','Ср','Чт','Пт','Сб','Вс'],['Дс','Сс','Ср','Бс','Жм','Сб','Жс']);
 receiptCalendar.setAttribute('aria-label',tr('Выбор даты','Күнді таңдау'));
 receiptCalendar.innerHTML=`<div class="receipt-calendar-head"><button type="button" data-calendar-month="-1" aria-label="${tr('Предыдущий месяц','Алдыңғы ай')}">‹</button><strong aria-live="polite">${esc(month.toLocaleDateString(lang==='kz'?'kk-KZ':'ru-RU',{month:'long',year:'numeric'}))}</strong><button type="button" data-calendar-month="1" aria-label="${tr('Следующий месяц','Келесі ай')}">›</button></div><div class="receipt-calendar-weekdays" aria-hidden="true">${weekdays.map(day=>`<span>${day}</span>`).join('')}</div><div class="receipt-calendar-days">${'<span></span>'.repeat(offset)}${Array.from({length:days},(_,i)=>{const date=calendarISO(new Date(year,index,i+1));return `<button type="button" data-calendar-date="${date}" ${date===selected?'aria-pressed="true"':''} ${date===today?'aria-current="date"':''} aria-label="${esc(new Date(year,index,i+1).toLocaleDateString(lang==='kz'?'kk-KZ':'ru-RU',{day:'numeric',month:'long',year:'numeric'}))}">${i+1}</button>`}).join('')}</div><div class="receipt-calendar-footer"><button type="button" data-calendar-today>${tr('Сегодня','Бүгін')}</button><button type="button" data-calendar-clear>${tr('Очистить','Тазарту')}</button><button type="button" data-calendar-close>${tr('Закрыть','Жабу')}</button></div>`;
}
function chooseReceiptDate(value){
 receiptCalendarInput.value=value;
 closeReceiptCalendar(true);localizeReceiptDates();
 receiptCalendarInput.dispatchEvent(new Event('change',{bubbles:true}));
}
document.querySelectorAll('[data-receipt-calendar]').forEach(button=>{
 button.hidden=false;receiptsForm.elements[button.dataset.receiptCalendar].hidden=true;
 button.addEventListener('click',()=>{
  const same=receiptCalendar&&receiptCalendarTrigger===button;
  closeReceiptCalendar();if(same)return;
  receiptCalendarInput=receiptsForm.elements[button.dataset.receiptCalendar];receiptCalendarTrigger=button;
  const date=receiptCalendarInput.value?calendarParse(receiptCalendarInput.value):new Date();
  receiptCalendarMonth=new Date(date.getFullYear(),date.getMonth(),1);
  receiptCalendar=document.createElement('div');receiptCalendar.className='receipt-calendar';receiptCalendar.setAttribute('role','dialog');
  button.closest('.receipt-date-field').append(receiptCalendar);button.setAttribute('aria-expanded','true');renderReceiptCalendar();
  (receiptCalendar.querySelector('[aria-pressed=true]')||receiptCalendar.querySelector('[aria-current=date]')||receiptCalendar.querySelector('[data-calendar-date]')).focus();
  receiptCalendar.addEventListener('click',event=>{
   const day=event.target.closest('[data-calendar-date]'),nav=event.target.closest('[data-calendar-month]');
   if(day)chooseReceiptDate(day.dataset.calendarDate);
   else if(nav){const delta=Number(nav.dataset.calendarMonth);receiptCalendarMonth.setMonth(receiptCalendarMonth.getMonth()+delta);renderReceiptCalendar();receiptCalendar.querySelector(`[data-calendar-month="${delta}"]`).focus()}
   else if(event.target.closest('[data-calendar-today]'))chooseReceiptDate(calendarISO(new Date()));
   else if(event.target.closest('[data-calendar-clear]'))chooseReceiptDate('');
   else if(event.target.closest('[data-calendar-close]'))closeReceiptCalendar(true);
  });
  receiptCalendar.addEventListener('keydown',event=>{
   if(event.key==='Escape'){event.preventDefault();event.stopPropagation();closeReceiptCalendar(true);return}
   const day=event.target.closest('[data-calendar-date]');
   const delta={ArrowLeft:-1,ArrowRight:1,ArrowUp:-7,ArrowDown:7}[event.key];
   if(day&&delta){event.preventDefault();const target=calendarParse(day.dataset.calendarDate);target.setDate(target.getDate()+delta);receiptCalendarMonth=new Date(target.getFullYear(),target.getMonth(),1);renderReceiptCalendar();receiptCalendar.querySelector(`[data-calendar-date="${calendarISO(target)}"]`).focus()}
  });
 });
});
document.addEventListener('pointerdown',event=>{if(receiptCalendar&&!event.target.closest('.receipt-date-field'))closeReceiptCalendar()});
document.addEventListener('focusin',event=>{if(receiptCalendar&&!event.target.closest('.receipt-date-field'))closeReceiptCalendar()});
$$('[data-set-language]').forEach(button=>button.addEventListener('click',localizeReceiptDates));
localizeReceiptDates();
