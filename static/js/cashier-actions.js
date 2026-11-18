'use strict';

// Staff actions use the existing authenticated API and its state checks.
async function cashierOpenAction(action, order) {
  const names = {
    accept: tr('Принять заказ', 'Тапсырысты қабылдау'),
    drinks_start: tr('Начать напитки сейчас','Сусындарды қазір бастау'),
    drink_eta: tr('Время напитков', 'Сусындар уақыты'),
    pay: tr('Подтвердить оплату', 'Төлемді растау'),
    discount: tr('Проверить скидку', 'Жеңілдікті тексеру'),
    reject: tr('Отклонить заказ', 'Тапсырысты қабылдамау'),
    cancel: tr('Отменить заказ', 'Тапсырыстан бас тарту'),
    refund: tr('Отменить оплату', 'Төлемді қайтару'),
    correct: tr('Изменить состав', 'Құрамын өзгерту'),
    ready: tr('Заказ готов', 'Тапсырыс дайын'),
    drinks_ready: tr('Напитки готовы', 'Сусындар дайын'),
    serve: tr('Выдать заказ', 'Тапсырысты беру'),
    preparing: tr('Начать приготовление', 'Дайындауды бастау')
  };
  if (!order || !names[action] || document.querySelector('.cash-dialog[open]')) return;

  const dialog = document.createElement('dialog');
  dialog.className = 'cash-dialog';
  const token = 'cash-action-' + crypto.randomUUID();
  dialog.setAttribute('aria-labelledby', token + '-title');
  const needsReason = ['reject', 'cancel', 'refund', 'correct', 'discount'].includes(action);
  const destructive = ['reject', 'cancel', 'refund'].includes(action);
  const field = (label, input) => `<label class="cash-field"><span>${label}</span>${input}</label>`;
  const reasonField = (required = true) => field(
    required ? tr('Причина', 'Себебі') : tr('Причина отличия суммы', 'Сома айырмасының себебі'),
    `<textarea name="reason" rows="3" maxlength="1000" ${required ? 'required' : ''}></textarea>`
  );
  const canCombine=action==='accept' && order.source==='web' && order.status==='new' && order.payment_status!=='paid';
  const paymentFields=()=>field(tr('Фактический способ оплаты','Нақты төлем тәсілі'),`<select name="payment_method">${[['cash',tr('Наличные','Қолма-қол')],['kaspi','Kaspi QR'],['halyk','Halyk']].map(([value,label])=>`<option value="${value}" ${order.payment_method===value?'selected':''}>${label}</option>`).join('')}</select>`) +
    field(tr('Сумма оплаты, ₸','Төлем сомасы, ₸'),`<input name="amount" type="number" inputmode="decimal" step="0.01" min="0.01" value="${esc(order.total)}" required>`) +
    `<div class="cash-tender-fields">${field(tr('Получено от гостя, ₸','Қонақтан алынды, ₸'),`<input name="cash_received" type="number" inputmode="decimal" step="0.01" min="0.01" value="${esc(order.total)}">`)}<p class="cash-change" role="status" aria-live="polite"></p></div>` + reasonField(false);
  let fields = '';
  const hasDrinks=(order.items||[]).some(item=>item.kind==='drink');
  if (['drink_eta','drinks_start'].includes(action) || (action === 'accept' && hasDrinks)) {
    fields = field(tr('Длительность всей группы напитков, мин','Барлық сусындарды дайындау ұзақтығы, мин'), `<input name="drink_eta" type="number" inputmode="numeric" min="1" max="180" step="1" value="${order.drink_eta_minutes||''}" ${action==='accept'?'':'required'}>`)+`<p>${tr('Учитывайте все напитки и их количество. Оценка времени сама не запускает приготовление.','Барлық сусындар мен олардың санын ескеріңіз. Уақытты бағалау дайындауды автоматты бастамайды.')}</p>`;

  } else if (action === 'pay') {
    fields = `<p>${tr('К оплате','Төлеуге')}: <strong>${money(order.total)}</strong></p>` + paymentFields();
  } else if (action === 'discount') {
    const review=order.discount_review||{},selected=Number(order.discount_percent||review.suggested_percent||0);
    fields=`<p>${review.program_active?tr('Учтено в программе','Бағдарламада есептелді'):tr('Оплаченные покупки по номеру','Нөмір бойынша төленген сатып алулар')}: <strong>${money(review.accumulated||0)}</strong></p><p>${tr('Рекомендуемая скидка','Ұсынылған жеңілдік')}: <strong>${Number(review.suggested_percent)||0}%</strong></p>`+
      field(tr('Подтверждённая скидка','Расталған жеңілдік'),`<select name="discount_percent">${[0,5,7,10,12,15].map(n=>`<option value="${n}" ${selected===n?'selected':''}>${n}%</option>`).join('')}</select>`)+
      '<p class="cash-discount-preview" role="status"></p>'+
      `<label class="cash-payment-toggle"><input type="checkbox" name="identity_confirmed" required><span>${tr('Проверил номер и право на скидку с гостем','Қонақтың нөмірін және жеңілдік құқығын тексердім')}</span></label>`+reasonField();
  } else if (action === 'correct') {
    fields = `<div class="cash-correction-items"></div><div class="cash-modal-grid">${field(tr('Добавить позицию', 'Тағам қосу'), `<select class="cash-add-product"><option value="">${tr('Выберите из меню', 'Мәзірден таңдаңыз')}</option>${catalog.filter(p => p.available !== false).map(p => `<option value="${p.id}">${esc(p['name_' + lang] || p.name_ru)} · ${money(p.price)}</option>`).join('')}</select>`)}<button type="button" class="cash-btn cash-add-item">${tr('Добавить', 'Қосу')}</button></div><fieldset class="cash-correction-drinks" hidden><legend>${tr('Как подать напитки?', 'Сусындарды қашан ұсыну керек?')}</legend><label class="cash-field"><span>${tr('Сразу', 'Бірден')}</span><input type="radio" name="drink_preference" value="immediately" ${order.drink_preference === 'immediately' ? 'checked' : ''}></label><label class="cash-field"><span>${tr('Вместе с блюдами', 'Тағамдармен бірге')}</span><input type="radio" name="drink_preference" value="with_food" ${order.drink_preference === 'with_food' ? 'checked' : ''}></label></fieldset>` + reasonField();
  } else if (needsReason) {
    fields = reasonField();
  } else {
    fields = `<p>${tr('Подтвердите действие для выбранного заказа.', 'Таңдалған тапсырыс үшін әрекетті растаңыз.')}</p>`;
  }

  if(canCombine){
    dialog.classList.add('cash-dialog-accept');
    fields+=`<section class="cash-accept-payment"><label class="cash-payment-toggle"><input type="checkbox" name="received_payment"><span>${tr('Оплата уже получена','Төлем алынды')}</span><strong>${money(order.total)}</strong></label><div class="cash-accept-payment-fields" hidden>${paymentFields()}</div></section>`;
  }
  dialog.innerHTML = `<form class="cash-action-form"><h2 id="${token}-title">${names[action]}</h2><p>${esc(order.number)} · ${esc(order.table || tr('Касса', 'Касса'))}</p>${fields}<p class="cash-modal-error" role="alert" aria-live="polite" hidden></p><div class="cash-modal-actions"><button type="button" class="cash-btn cash-close-action">${tr('Назад', 'Артқа')}</button><button type="submit" class="cash-btn ${destructive ? 'danger' : 'primary'}">${action==='accept'?tr('Принять заказ','Тапсырысты қабылдау'):tr('Подтвердить', 'Растау')}</button></div></form>`;
  const form = dialog.querySelector('form');
  const errorBox = dialog.querySelector('.cash-modal-error');
  const submit = form.querySelector('[type="submit"]');
  const paymentKey = crypto.randomUUID();
  let busy = false;
  const rows = (order.items || []).map(i => ({
    id: Number(i.menu_item_id), quantity: Number(i.quantity), comment: i.comment || '',
    name_ru: i.name_ru, name_kz: i.name_kz, kind: i.kind
  }));
  const showError = message => {
    errorBox.textContent = message;
    errorBox.hidden = false;
  };

  function renderRows() {
    if (action !== 'correct') return;
    dialog.querySelector('.cash-correction-items').innerHTML = rows.map((row, index) => `<div class="cash-modal-item"><span>${esc(row['name_' + lang] || row.name_ru)}</span>${field(tr('Количество', 'Саны'), `<input class="cash-item-quantity" data-index="${index}" type="number" inputmode="numeric" min="1" max="99" step="1" value="${row.quantity}" required>`)}<button class="cash-btn" type="button" data-cash-remove="${index}" aria-label="${tr('Убрать', 'Алу')} ${esc(row['name_' + lang] || row.name_ru)}">${tr('Убрать', 'Алу')}</button></div>`).join('');
    const mixed = order.fulfillment !== 'takeaway' && new Set(rows.map(row => row.kind)).size > 1;
    const drinks = dialog.querySelector('.cash-correction-drinks');
    drinks.hidden = !mixed;
    drinks.querySelectorAll('input').forEach(input => { input.required = mixed; });
  }

  const syncPaymentControls=()=>{
    if(action!=='pay'&&!canCombine)return;
    const enabled=action==='pay'||form.elements.received_payment.checked;
    const cash=form.elements.payment_method.value==='cash';
    if(canCombine){
      form.querySelector('.cash-accept-payment-fields').hidden=!enabled;
      submit.textContent=enabled?tr('Принять и подтвердить оплату','Қабылдау және төлемді растау'):tr('Принять заказ','Тапсырысты қабылдау');
    }
    form.elements.payment_method.disabled=!enabled;
    form.elements.amount.disabled=!enabled;form.elements.amount.required=enabled;
    const tender=form.querySelector('.cash-tender-fields');tender.hidden=!enabled||!cash;
    form.elements.cash_received.disabled=!enabled||!cash;form.elements.cash_received.required=enabled&&cash;
    const amount=Math.round(Number(form.elements.amount.value)*100);
    const received=Math.round(Number(form.elements.cash_received.value)*100);
    const differs=amount!==Math.round(Number(order.total)*100);
    const reason=form.elements.reason;reason.closest('label').hidden=!enabled||!differs;
    reason.disabled=!enabled||!differs;reason.required=enabled&&differs;
    const shortage=enabled&&cash&&Number.isFinite(amount)&&Number.isFinite(received)&&received<amount;
    const change=form.querySelector('.cash-change');
    change.textContent=Number.isFinite(amount)&&Number.isFinite(received)?(shortage?tr('Не хватает: ','Жетпейді: ')+money((amount-received)/100):tr('Сдача: ','Қайтарым: ')+money(Math.max(0,received-amount)/100)):'';
    change.style.color=shortage?'#a0442d':'';
    submit.disabled=busy||shortage;
  };
  if(action==='discount'){const preview=()=>{const cents=Math.round(Number(order.subtotal)*100),rate=Number(form.elements.discount_percent.value),discount=Math.round(cents*rate/100);form.querySelector('.cash-discount-preview').textContent=tr('Скидка: ','Жеңілдік: ')+money(discount/100)+' · '+tr('К оплате: ','Төлеуге: ')+money((cents-discount)/100)};form.elements.discount_percent.addEventListener('change',preview);preview()}
  if(action==='pay'||canCombine){form.addEventListener('input',syncPaymentControls);form.addEventListener('change',syncPaymentControls);syncPaymentControls()}

  if (action === 'correct') {
    renderRows();
    dialog.addEventListener('input', event => {
      if (event.target.matches('.cash-item-quantity')) {
        rows[Number(event.target.dataset.index)].quantity = Number(event.target.value);
      }
    });
    dialog.addEventListener('click', event => {
      const remove = event.target.closest('[data-cash-remove]');
      if (remove && !busy) {
        rows.splice(Number(remove.dataset.cashRemove), 1);
        renderRows();
      }
    });
    dialog.querySelector('.cash-add-item').addEventListener('click', () => {
      if (busy) return;
      const selected = Number(dialog.querySelector('.cash-add-product').value);
      const product = catalog.find(p => Number(p.id) === selected);
      if (!product) return;
      const existing = rows.find(row => row.id === selected);
      if (existing) {
        existing.quantity = Math.min(99, existing.quantity + 1);
      } else {
        rows.push({id: selected, quantity: 1, comment: '', name_ru: product.name_ru, name_kz: product.name_kz, kind: product.kind});
      }
      dialog.querySelector('.cash-add-product').value = '';
      renderRows();
    });
  }

  dialog.querySelector('.cash-close-action').addEventListener('click', () => {
    if (!busy) dialog.close();
  });
  dialog.addEventListener('cancel', event => { if (busy) event.preventDefault(); });
  dialog.addEventListener('close', () => dialog.remove(), {once: true});
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (busy || !form.reportValidity()) return;
    errorBox.hidden = true;
    const values = new FormData(form);
    const payload = {action};
    const wantsPayment=action==='pay'||(canCombine&&form.elements.received_payment.checked);
    if(canCombine&&wantsPayment)payload.action='accept_and_pay';
    const reason = String(values.get('reason') || '').trim();
    if (needsReason && !reason) {
      showError(tr('Укажите причину.', 'Себебін көрсетіңіз.'));
      return;
    }
    if (needsReason || wantsPayment) payload.reason = reason;
    if (['accept', 'drink_eta','drinks_start'].includes(action) && values.get('drink_eta')) payload[action==='accept'?'drink_eta':'eta'] = Number(values.get('drink_eta'));
    if (wantsPayment) {
      payload.amount = values.get('amount');
      payload.payment_method = values.get('payment_method');
      payload.idempotency_key = paymentKey;
      if (payload.payment_method === 'cash') {
        payload.cash_received = values.get('cash_received');
        if (Number(payload.cash_received) < Number(payload.amount)) {
          showError(tr('Полученная сумма меньше суммы оплаты.', 'Алынған сома төлем сомасынан аз.'));
          return;
        }
      }
      if (Math.round(Number(payload.amount) * 100) !== Math.round(Number(order.total) * 100) && !reason) {
        showError(tr('Укажите причину отличия фактической суммы.', 'Нақты сома айырмасының себебін көрсетіңіз.'));
        return;
      }
    }
    if(action==='discount'){payload.discount_percent=Number(values.get('discount_percent'));payload.identity_confirmed=values.get('identity_confirmed')==='on';payload.version=order.version;}
    if (action === 'correct') {
      if (!rows.length || rows.some(row => !Number.isInteger(row.quantity) || row.quantity < 1 || row.quantity > 99)) {
        showError(tr('Добавьте позиции и укажите целое количество от 1 до 99.', 'Тағам қосып, 1 мен 99 аралығындағы бүтін санды көрсетіңіз.'));
        return;
      }
      payload.items = rows.map(row => ({id: row.id, quantity: row.quantity, comment: row.comment}));
      payload.drink_preference = dialog.querySelector('.cash-correction-drinks').hidden ? '' : values.get('drink_preference');
    }
    busy = true;
    form.querySelectorAll('button,input,select,textarea').forEach(control => { control.disabled = true; });
    const priorText = submit.textContent;
    submit.textContent = tr('Сохраняем…', 'Сақталуда…');
    let saved = false;
    try {
      await api('/api/staff/orders/' + order.public_id + '/action/', payload);
      saved = true;
      dialog.close();
    } catch (error) {
      showError(error.message || String(error));
    } finally {
      busy = false;
      if (!saved) {
        form.querySelectorAll('button,input,select,textarea').forEach(control => { control.disabled = false; });
        submit.textContent = priorText;
        syncPaymentControls();
      }
    }
    if (saved) await refreshCashier();
  });
  document.body.append(dialog);
  dialog.showModal();
}
