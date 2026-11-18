'use strict';
const guestStatusWindow=$('#guest-status-window'),guestStatusContent=$('#guest-status-content'),guestStatusReopen=$('#guest-status-reopen');
let guestStatusSnapshot='',guestStatusOrder=null,guestStatusAutoOpen=false;
const guestStatusSteps=[['new','Получен','Қабылданды'],['accepted','Принят','Расталды'],['preparing','Готовится','Дайындалуда'],['ready','Готов','Дайын'],['served','Подан','Ұсынылды']];
const guestStatusCopy={
 new:['Заказ получен','Тапсырыс қабылданды','Ожидаем подтверждения от кофейни.','Кофехананың растауын күтеміз.'],
 accepted:['Заказ принят','Тапсырыс расталды','Мы приняли ваш заказ в работу.','Тапсырысыңыз жұмысқа қабылданды.'],
 preparing:['Готовим ваш заказ','Тапсырысыңыз дайындалуда','Кухня и бар готовят выбранные позиции.','Асүй мен бар таңдаған тағамдар мен сусындарды дайындауда.'],
 ready:['Заказ готов','Тапсырыс дайын','Ваш заказ готов к подаче.','Тапсырысыңыз ұсынуға дайын.'],
 served:['Заказ подан','Тапсырыс ұсынылды','Приятного аппетита!','Ас болсын!'],
 rejected:['Заказ не принят','Тапсырыс қабылданбады','Обратитесь к сотруднику кофейни.','Кофехана қызметкеріне хабарласыңыз.'],
 cancelled:['Заказ отменён','Тапсырыс тоқтатылды','Обратитесь к сотруднику, если нужна помощь.','Көмек қажет болса, қызметкерге хабарласыңыз.']
};
function openGuestStatus(){if(!guestStatusWindow.open)guestStatusWindow.showModal();document.body.classList.add('guest-status-is-open');window.dispatchEvent(new Event('guest-status-visibility'))}
function closeGuestStatus(){guestStatusWindow.close()}
function updateGuestStatus(order,initial=false){
 if(!order)return;guestStatusOrder=order;
 const snapshot=JSON.stringify([lang,order.status,order.payment_status,order.food_eta_at,order.drink_eta_at,order.food_eta_minutes,order.drink_eta_minutes,order.food_ready,order.drinks_ready,order.is_delayed,order.total,order.table]);
 if(snapshot!==guestStatusSnapshot){
  guestStatusSnapshot=snapshot;
  const copy=guestStatusCopy[order.status]||guestStatusCopy.new,index=guestStatusSteps.findIndex(step=>step[0]===order.status),stopped=index<0,finished=order.status==='served';
  const icon=stopped?'<path d="m9 9 6 6m0-6-6 6"/>':finished||order.status==='ready'?'<path d="m7 12 3 3 7-7"/>':'<circle cx="12" cy="12" r="7"/><path d="M12 8v4l3 2"/>';
  guestStatusContent.innerHTML=`<div class="guest-wait-symbol ${!stopped&&!finished&&order.status!=='ready'?'is-waiting':''} ${stopped?'is-stopped':''}" aria-hidden="true"><svg viewBox="0 0 24 24">${icon}</svg></div><p class="guest-wait-table">${guestTable(order)}</p><h2 id="guest-status-title">${tr(copy[0],copy[1])}</h2><p id="guest-status-description">${tr(copy[2],copy[3])}</p>${stopped?'':`<ol class="guest-wait-steps">${guestStatusSteps.map((step,n)=>`<li class="${n<index?'is-complete':n===index?'is-current':''}" ${n===index?'aria-current="step"':''}><span aria-hidden="true">${n<index?'✓':n+1}</span><small>${tr(step[1],step[2])}</small></li>`).join('')}</ol>`}${guestStationTimes(order)}<div class="guest-wait-summary"><strong>${money(order.total)}</strong><span class="guest-payment">${state(order.payment_status)}</span></div>`;
 }
 guestStatusReopen.hidden=false;
 if(initial&&(['new','accepted','preparing','ready'].includes(order.status)||order.status==='served'&&order.payment_status!=='paid')){guestStatusAutoOpen=true;openGuestStatus();}
}
$('#guest-status-close').addEventListener('click',closeGuestStatus);
$('#guest-status-details').addEventListener('click',closeGuestStatus);
guestStatusReopen.addEventListener('click',()=>{guestStatusAutoOpen=false;openGuestStatus()});
guestStatusWindow.addEventListener('close',()=>{document.body.classList.remove('guest-status-is-open');window.dispatchEvent(new Event('guest-status-visibility'));guestStatusReopen.focus()});
window.addEventListener('guest-order-updated',event=>updateGuestStatus(event.detail));
updateGuestStatus(currentGuestOrder||data('order-data'),true);
