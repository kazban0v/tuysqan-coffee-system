'use strict';
// Shared presentation only: the API owns eligibility and all saved amounts.
window.requestLoyaltyChoice=function(offer,subtotal,{cashier=false}={}){
 if(!(Number(offer?.percent)>0))return Promise.resolve(false);
 return new Promise(resolve=>{
  const dialog=document.createElement('dialog'),returnFocus=document.activeElement;
  const id='loyalty-choice-'+crypto.randomUUID();dialog.className='loyalty-choice-dialog';dialog.setAttribute('aria-labelledby',id);
  let answer=null;
  function paint(){
   const percent=Number(offer.percent),cents=Math.round(Number(subtotal)*100),discount=Math.round(cents*percent/100);
   dialog.innerHTML=`<div class="loyalty-choice-top"><span>TUYSQAN · COFFEE CLUB</span><div class="loyalty-choice-languages"><button type="button" data-loyalty-language="ru" aria-pressed="${lang==='ru'}">RU</button><button type="button" data-loyalty-language="kz" aria-pressed="${lang==='kz'}">KZ</button></div><button type="button" data-loyalty-close class="loyalty-choice-close" aria-label="${tr('Закрыть','Жабу')}">×</button></div><div class="loyalty-choice-mark" aria-hidden="true">${percent}<small>%</small></div><h2 id="${id}">${cashier?tr('У гостя есть скидка','Қонаққа жеңілдік бар'):tr('У вас есть скидка','Сізде жеңілдік бар')}</h2><p class="loyalty-choice-copy">${cashier?tr('Спросите гостя, применить ли выбранную скидку к этому заказу.','Қонақтан осы тапсырысқа таңдалған жеңілдікті қолдануды қалайтынын сұраңыз.'):tr('Применить накопительную скидку? Этот уровень можно использовать один раз.','Жинақтаушы жеңілдікті қолданасыз ба? Бұл деңгей бір рет пайдаланылады.')}</p><dl class="loyalty-choice-totals"><div><dt>${tr('Без скидки','Жеңілдіксіз')}</dt><dd>${money(cents/100)}</dd></div><div class="loyalty-choice-saving"><dt>${tr('Скидка','Жеңілдік')} ${percent}%</dt><dd>−${money(discount/100)}</dd></div><div class="loyalty-choice-final"><dt>${tr('Со скидкой','Жеңілдікпен')}</dt><dd>${money((cents-discount)/100)}</dd></div></dl><div class="loyalty-choice-actions"><button type="button" data-loyalty-answer="yes">${tr('Да, применить','Иә, қолдану')}</button><button type="button" data-loyalty-answer="no">${tr('Без скидки','Жеңілдіксіз')}</button></div>`;
  }
  paint();
  dialog.addEventListener('click',event=>{
   const choice=event.target.closest('[data-loyalty-answer]');
   if(choice){answer=choice.dataset.loyaltyAnswer==='yes';dialog.close();return}
   if(event.target.closest('[data-loyalty-close]')){dialog.close();return}
   const language=event.target.closest('[data-loyalty-language]');
   if(language){document.querySelector(`[data-set-language="${language.dataset.loyaltyLanguage}"]`)?.click();paint();dialog.querySelector(`[data-loyalty-language="${lang}"]`)?.focus()}
  });
  dialog.addEventListener('close',()=>{dialog.remove();if(returnFocus?.isConnected)returnFocus.focus();resolve(answer)},{once:true});
  document.body.append(dialog);dialog.showModal();dialog.querySelector('[data-loyalty-answer="yes"]').focus();
 });
};
