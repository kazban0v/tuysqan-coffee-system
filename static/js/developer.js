'use strict';
(()=>{
 const initial=document.getElementById('developer-data');if(!initial)return;
 const el=id=>document.getElementById('dev-'+id),escape=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),bytes=v=>v==null?'—':(v/1024/1024/1024).toFixed(2)+' ГБ',amount=v=>v==null?'—':new Intl.NumberFormat('ru-RU',{maximumFractionDigits:2}).format(Number(v))+' ₸',date=v=>v?new Date(v).toLocaleString('ru-RU'):'—';
 const row=(label,value)=>`<div class="dev-row"><span>${escape(label)}</span><strong>${escape(value)}</strong></div>`;
 function render(data){
  const h=data.host,b=data.business,w=data.watchdog||{};
  el('health').textContent=h.database.ok?'Приложение и база отвечают':'База данных недоступна';el('updated').textContent='Проверено: '+date(h.checked_at);
  for(const period of ['today','week','month'])el('revenue-'+period).textContent=amount(b[period]?.net);
  el('active').textContent=b.active_orders??'—';el('unpaid').textContent=b.unpaid_orders??'—';el('unpaid-total').textContent=amount(b.unpaid_total);el('errors').textContent=h.http_5xx_24h;
  el('resources').innerHTML=[['CPU',h.cpu_percent],['RAM',h.memory_percent],['Диск',h.disk_used_percent]].map(([label,value])=>row(label,value+'%')+`<progress value="${Number(value)}" max="100" aria-label="${label}"></progress>`).join('')+row('RAM: занято / всего',bytes(h.memory_used_bytes)+' / '+bytes(h.memory_total_bytes))+row('Свободно на диске',bytes(h.disk_free_bytes));
  el('process').textContent='Текущий процесс Django: '+bytes(h.process_rss_bytes)+' RAM · работает '+Math.floor(h.process_uptime_seconds/60)+' мин. CPU: '+h.cpu_count+' логических ядер.';
  el('database').innerHTML=row('Состояние',h.database.ok?'Доступна':'Нет связи')+row('Движок',h.database.engine)+row('Время ответа',h.database.milliseconds==null?'—':h.database.milliseconds+' мс')+row('Размер базы',bytes(h.database.size_bytes));
  const fresh=w.last_check_at&&Date.now()-new Date(w.last_check_at).getTime()<60000;
  el('watchdog').innerHTML=row('Telegram',data.telegram.configured?'Адресат настроен':'Не настроен')+row('Наблюдатель',fresh?'Проверки выполняются':'Нет свежего сигнала')+row('Последняя проверка',date(w.last_check_at))+row('Последняя отправка',date(w.last_delivery_at))+(w.last_error?row('Доставка',w.last_error):'');
  el('events').innerHTML=h.events.length?h.events.map(e=>`<div class="dev-entry"><time>${date(e.at)}</time><strong>${e.kind==='http_5xx'?'HTTP '+e.status:'Медленный запрос'}</strong> · ${e.milliseconds} мс<br>${escape(e.route)}</div>`).join(''):'<p class="dev-empty">Ошибок 5xx и медленных запросов за последние 24 часа не зафиксировано.</p>';
  el('incidents').innerHTML=(w.history||[]).length?w.history.map(e=>`<div class="dev-entry"><time>${date(e.at)}</time>${escape(e.summary)} · ${e.kind==='recovery'?'Восстановление':'Проблема'}<br>${e.delivered?'Доставлено в Telegram':'Ожидает доставки'}</div>`).join(''):'<p class="dev-empty">Событий мониторинга пока нет.</p>';
 }
 let busy=false,timer;
 async function refresh(){if(busy||document.hidden)return;busy=true;el('refresh').disabled=true;const controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),8000);try{const response=await fetch('/developer/api/status/',{signal:controller.signal,headers:{Accept:'application/json'},cache:'no-store'});if(!response.ok)throw Error();render(await response.json());el('error').hidden=true}catch{el('error').textContent='Не удалось обновить состояние. Последние данные могут быть устаревшими.';el('error').hidden=false}finally{clearTimeout(timeout);busy=false;el('refresh').disabled=false}}
 render(JSON.parse(initial.textContent));el('refresh').addEventListener('click',refresh);timer=setInterval(refresh,30000);document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh()});window.addEventListener('pagehide',()=>clearInterval(timer));
})();
