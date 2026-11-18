'use strict';
(() => {
 if(document.body.dataset.page!=='admin-portal')return;
 // Date helpers: local noon avoids UTC shifts and DST-midnight edge cases.
 const pad=n=>String(n).padStart(2,'0');
 const leap=year=>year%4===0&&(year%100!==0||year%400===0);
 const monthDays=(year,month)=>[31,leap(year)?29:28,31,30,31,30,31,31,30,31,30,31][month];
 function dateValue(year,month,day){const value=new Date(0);value.setFullYear(year,month,day);value.setHours(12,0,0,0);return value}
 function parseISO(value){const match=/^(\d{4})-(\d{2})-(\d{2})$/.exec(value||'');if(!match)return null;const year=Number(match[1]),month=Number(match[2])-1,day=Number(match[3]);return year>=1&&year<=9999&&month>=0&&month<=11&&day>=1&&day<=monthDays(year,month)?dateValue(year,month,day):null}
 const iso=date=>String(date.getFullYear()).padStart(4,'0')+'-'+pad(date.getMonth()+1)+'-'+pad(date.getDate());
 const formatted=value=>{const date=parseISO(value);return date?pad(date.getDate())+'.'+pad(date.getMonth()+1)+'.'+String(date.getFullYear()).padStart(4,'0'):''};
 function parseDisplay(value){const text=value.trim();if(/^\d{8}$/.test(text))return parseISO(text.slice(4)+'-'+text.slice(2,4)+'-'+text.slice(0,2));const match=/^(\d{2})\.(\d{2})\.(\d{4})$/.exec(text);return match?parseISO(match[3]+'-'+match[2]+'-'+match[1]):parseISO(text)}
 function moved(date,months=0,days=0){const base=dateValue(date.getFullYear(),date.getMonth()+months,1);base.setDate(Math.min(date.getDate(),monthDays(base.getFullYear(),base.getMonth()))+days);return base}
 function monthGrid(year,month){const first=dateValue(year,month,1),offset=(first.getDay()+6)%7;return Array.from({length:42},(_,index)=>dateValue(year,month,index-offset+1))}
 const inRange=(value,min,max)=>(!min||value>=min)&&(!max||value<=max);
 // DOM binding.
 const inputs=[...document.querySelectorAll('input[type="date"]')];if(!inputs.length)return;
 const controls=[],t=(ru,kz)=>document.documentElement.lang==='kk'?kz:ru,locale=()=>document.documentElement.lang==='kk'?'kk-KZ':'ru-RU';
 const panel=document.createElement('div');panel.className='ap-datepicker';panel.id='ap-datepicker-panel';panel.hidden=true;panel.setAttribute('role','dialog');panel.setAttribute('aria-modal','false');panel.style.position='fixed';panel.style.zIndex='1100';document.body.append(panel);
 let active=null,view=null,cursor=null;
 const bounds=state=>({min:parseISO(state.input.min)?state.input.min:'',max:parseISO(state.input.max)?state.input.max:''});
 const allowed=(date,state=active)=>{const value=iso(date),range=bounds(state);return date.getFullYear()>=1&&date.getFullYear()<=9999&&inRange(value,range.min,range.max)};
 function validate(state){
  const raw=state.proxy.value.trim(),date=parseDisplay(raw),range=bounds(state);let message='';
  if(raw&&!date)message=t('Введите дату в формате ДД.ММ.ГГГГ','Күнді КК.АА.ЖЖЖЖ форматында енгізіңіз');
  else if(date&&!inRange(iso(date),range.min,range.max))message=t('Дата вне допустимого диапазона','Күн рұқсат етілген аралықтан тыс');
  state.input.value=date&&!message?iso(date):'';state.proxy.setCustomValidity(message);return !message;
 }
 function validateAll(){
  controls.forEach(validate);
  const forms=new Set(controls.map(state=>state.input.form).filter(Boolean));
  forms.forEach(form=>{const first=controls.find(state=>state.input.form===form&&state.input.name==='start'),last=controls.find(state=>state.input.form===form&&state.input.name==='end');if(first&&last&&first.input.value&&last.input.value&&first.input.value>last.input.value)last.proxy.setCustomValidity(t('Дата окончания раньше даты начала','Аяқталу күні басталу күнінен бұрын'));});
 }
 function fieldLabel(state){const label=state.proxy.closest('label')||document.querySelector(`label[for="${state.proxy.id}"]`);return label?.querySelector('span')?.textContent?.trim()||t('Дата','Күн')}
 function close(returnFocus=true){if(!active)return;const previous=active;previous.trigger.setAttribute('aria-expanded','false');panel.hidden=true;active=null;if(returnFocus)previous.trigger.focus()}
 function commit(value){if(!active)return;const state=active;state.input.value=value;state.proxy.value=formatted(value);validateAll();state.input.dispatchEvent(new Event('input',{bubbles:true}));state.input.dispatchEvent(new Event('change',{bubbles:true}));close()}
 function position(){
  if(!active)return;
  const rect=active.wrapper.getBoundingClientRect(),width=Math.min(360,Math.max(240,innerWidth-24));panel.style.width=width+'px';panel.style.maxWidth='calc(100vw - 24px)';panel.style.maxHeight='calc(100dvh - 24px)';panel.style.overflowY='auto';
  const below=innerHeight-rect.bottom-20,above=rect.top-20;
  panel.classList.toggle('is-compact',innerHeight<800);
  let height=panel.getBoundingClientRect().height;
  if(height>Math.max(below,above)){panel.classList.add('is-compact');height=panel.getBoundingClientRect().height}
  const left=Math.max(12,Math.min(rect.left,innerWidth-width-12));
  let top=below>=height?rect.bottom+8:above>=height?rect.top-height-8:Math.max(12,innerHeight-height-12);
  panel.style.left=left+'px';panel.style.top=Math.min(Math.max(12,top),Math.max(12,innerHeight-height-12))+'px';
 }
 const escaped=value=>String(value).replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
 function render(focusDay=false){
  if(!active)return;
  panel.setAttribute('aria-label',t('Выбор даты: ','Күнді таңдау: ')+fieldLabel(active));
  const year=view.getFullYear(),month=view.getMonth(),today=iso(new Date()),selected=active.input.value;
  const monthNames=Array.from({length:12},(_,index)=>new Intl.DateTimeFormat(locale(),{month:'long'}).format(dateValue(year,index,1)));
  const todayYear=new Date().getFullYear(),range=bounds(active),firstYear=parseISO(range.min)?.getFullYear()||Math.max(1,Math.min(year,todayYear)-100),lastYear=parseISO(range.max)?.getFullYear()||Math.min(9999,Math.max(year,todayYear)+30);
  const days=monthGrid(year,month);
  if(!allowed(cursor))cursor=days.find(day=>day.getMonth()===month&&allowed(day))||days.find(day=>allowed(day))||cursor;
  const weekdays=Array.from({length:7},(_,index)=>new Intl.DateTimeFormat(locale(),{weekday:'short'}).format(dateValue(2026,10,2+index)));
  const previous=moved(view,-1),next=moved(view,1),previousEnd=iso(dateValue(previous.getFullYear(),previous.getMonth(),monthDays(previous.getFullYear(),previous.getMonth()))),nextStart=iso(dateValue(next.getFullYear(),next.getMonth(),1));
  panel.innerHTML=`<div class="ap-datepicker-head"><button type="button" class="ap-calendar-nav" data-calendar-move="-1" aria-label="${t('Предыдущий месяц','Алдыңғы ай')}" ${year===1&&month===0||range.min&&previousEnd<range.min?'disabled':''}>‹</button><div class="ap-calendar-selects"><select data-calendar-month aria-label="${t('Месяц','Ай')}">${monthNames.map((name,index)=>`<option value="${index}" ${index===month?'selected':''}>${escaped(name)}</option>`).join('')}</select><select data-calendar-year aria-label="${t('Год','Жыл')}">${Array.from({length:Math.max(0,lastYear-firstYear+1)},(_,index)=>firstYear+index).map(value=>`<option value="${value}" ${value===year?'selected':''}>${value}</option>`).join('')}</select></div><button type="button" class="ap-calendar-nav" data-calendar-move="1" aria-label="${t('Следующий месяц','Келесі ай')}" ${year===9999&&month===11||range.max&&nextStart>range.max?'disabled':''}>›</button></div><div class="ap-calendar-weekdays" aria-hidden="true">${weekdays.map(day=>`<span>${escaped(day)}</span>`).join('')}</div><div class="ap-calendar-grid" role="grid" aria-label="${escaped(monthNames[month])} ${year}">${days.map((day,index)=>{const value=iso(day),valid=allowed(day);return `${index%7===0?'<div class="ap-calendar-week" role="row">':''}<button type="button" role="gridcell" class="ap-calendar-day${day.getMonth()!==month?' is-outside':''}${value===selected?' is-selected':''}${value===today?' is-today':''}" data-calendar-date="${value}" aria-label="${escaped(new Intl.DateTimeFormat(locale(),{dateStyle:'full'}).format(day))}" aria-selected="${value===selected}" ${value===today?'aria-current="date"':''} tabindex="${valid&&value===iso(cursor)?'0':'-1'}" ${valid?'':'disabled'}>${day.getDate()}</button>${index%7===6?'</div>':''}`}).join('')}</div><div class="ap-calendar-footer"><button type="button" class="ap-calendar-today" data-calendar-today ${allowed(new Date())?'':'disabled'}>${t('Сегодня','Бүгін')}</button><button type="button" class="ap-calendar-clear" data-calendar-clear>${t('Очистить','Тазалау')}</button></div>`;
  position();if(focusDay)(panel.querySelector(`[data-calendar-date="${iso(cursor)}"]:not([disabled])`)||panel.querySelector('select')).focus();
 }
 function show(state){
  if(state.trigger.disabled)return;if(active===state){close();return}if(active)close(false);
  active=state;let date=parseISO(state.input.value)||dateValue(new Date().getFullYear(),new Date().getMonth(),new Date().getDate());const range=bounds(state);
  if(range.min&&iso(date)<range.min)date=parseISO(range.min);if(range.max&&iso(date)>range.max)date=parseISO(range.max);
  view=dateValue(date.getFullYear(),date.getMonth(),1);cursor=date;panel.hidden=false;state.trigger.setAttribute('aria-expanded','true');render(true);
 }
 inputs.forEach((input,index)=>{
  const wrapper=document.createElement('div');wrapper.className='ap-date-control';const proxy=document.createElement('input'),trigger=document.createElement('button');
  proxy.type='text';proxy.className='ap-date-display';proxy.inputMode='numeric';proxy.autocomplete='off';proxy.placeholder='ДД.ММ.ГГГГ';proxy.maxLength=10;proxy.value=formatted(input.value);proxy.required=input.required;proxy.disabled=input.disabled;proxy.readOnly=input.readOnly;
  const originalId=input.id;proxy.id=originalId||'ap-date-'+index;if(originalId)input.id=originalId+'-iso';
  trigger.type='button';trigger.className='ap-date-trigger';trigger.disabled=input.disabled||input.readOnly;trigger.setAttribute('aria-haspopup','dialog');trigger.setAttribute('aria-controls',panel.id);trigger.setAttribute('aria-expanded','false');trigger.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M16 3v4M8 3v4M3 11h18M8 15h2M14 15h2"/></svg>';
  const state={input,proxy,trigger,wrapper,initial:input.value};input.before(wrapper);wrapper.append(proxy,trigger);input.type='hidden';input.required=false;input.hidden=true;controls.push(state);
  trigger.addEventListener('click',()=>show(state));
  proxy.addEventListener('input',validateAll);proxy.addEventListener('change',validateAll);proxy.addEventListener('blur',()=>{if(validate(state)&&input.value)proxy.value=formatted(input.value);validateAll()});
  proxy.addEventListener('keydown',event=>{if(event.key==='ArrowDown'&&(event.altKey||!event.ctrlKey&&!event.metaKey)){event.preventDefault();show(state)}else if(event.key==='Escape'&&active===state){event.preventDefault();close()}});
  input.addEventListener('change',()=>{proxy.value=formatted(input.value);validateAll()});
 });
 new Set(controls.map(state=>state.input.form).filter(Boolean)).forEach(form=>form.addEventListener('reset',()=>setTimeout(()=>{controls.filter(state=>state.input.form===form).forEach(state=>{state.input.value=state.initial;state.proxy.value=formatted(state.initial)});validateAll();close(false)},0)));
 panel.addEventListener('click',event=>{
  const button=event.target.closest('button');if(!button||button.disabled||!active)return;
  if(button.dataset.calendarDate){commit(button.dataset.calendarDate);return}
  if(button.hasAttribute('data-calendar-today')){commit(iso(new Date()));return}
  if(button.hasAttribute('data-calendar-clear')){commit('');return}
  if(button.dataset.calendarMove){view=moved(view,Number(button.dataset.calendarMove));cursor=dateValue(view.getFullYear(),view.getMonth(),Math.min(cursor.getDate(),monthDays(view.getFullYear(),view.getMonth())));render();(panel.querySelector(`[data-calendar-move="${button.dataset.calendarMove}"]:not([disabled])`)||panel.querySelector('select')).focus();}
 });
 panel.addEventListener('change',event=>{
  if(!active)return;const month=panel.querySelector('[data-calendar-month]'),year=panel.querySelector('[data-calendar-year]');
  if(event.target===month||event.target===year){view=dateValue(Number(year.value),Number(month.value),1);cursor=dateValue(view.getFullYear(),view.getMonth(),1);render();panel.querySelector(event.target===month?'[data-calendar-month]':'[data-calendar-year]').focus()}
 });
 panel.addEventListener('keydown',event=>{
  if(!active)return;
  if(event.key==='Escape'){event.preventDefault();event.stopPropagation();close();return}
  if(event.key==='Tab'){
   const targets=[...panel.querySelectorAll('button:not([disabled]),select:not([disabled])')].filter(node=>node.tabIndex>=0),first=targets[0],last=targets[targets.length-1];
   if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus()}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus()}return;
  }
  const day=event.target.closest('[data-calendar-date]');if(!day)return;let next=parseISO(day.dataset.calendarDate);const weekday=(next.getDay()+6)%7;
  if(event.key==='ArrowLeft')next=moved(next,0,-1);else if(event.key==='ArrowRight')next=moved(next,0,1);else if(event.key==='ArrowUp')next=moved(next,0,-7);else if(event.key==='ArrowDown')next=moved(next,0,7);else if(event.key==='Home')next=moved(next,0,-weekday);else if(event.key==='End')next=moved(next,0,6-weekday);else if(event.key==='PageUp')next=moved(next,event.shiftKey?-12:-1);else if(event.key==='PageDown')next=moved(next,event.shiftKey?12:1);else return;
  event.preventDefault();if(allowed(next)){cursor=next;view=dateValue(next.getFullYear(),next.getMonth(),1);render(true)}
 });
 document.addEventListener('pointerdown',event=>{if(active&&!panel.contains(event.target)&&!active.wrapper.contains(event.target))close(false)});
 document.addEventListener('focusin',event=>{if(active&&!panel.contains(event.target)&&!active.wrapper.contains(event.target))close(false)});
 window.addEventListener('resize',position);window.addEventListener('scroll',position,true);
 function labels(){controls.forEach(state=>{state.proxy.placeholder=t('ДД.ММ.ГГГГ','КК.АА.ЖЖЖЖ');state.proxy.setAttribute('aria-label',fieldLabel(state));state.trigger.setAttribute('aria-label',t('Выбрать дату: ','Күнді таңдау: ')+fieldLabel(state))});validateAll();if(active)render()}
 document.querySelectorAll('[data-set-language]').forEach(button=>button.addEventListener('click',labels));labels();
})();
