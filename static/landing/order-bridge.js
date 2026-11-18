/* Additive local Django order integration. Presentation source is preserved. */
(()=>{
'use strict';
const db=JSON.parse(document.getElementById('django-order-catalog')?.textContent||'[]');
const items=window.TUYSQAN_MENU?.items||[];
const norm=s=>String(s).normalize('NFKC').toLowerCase().replace(/ё/g,'е').replace(/[^\p{L}\p{N}]/gu,'');
// Reviewed equivalent names from supplied menu, mapped to stable Django slugs.
// Split ramen/Caesar variants remain unavailable: source DB has grouped variants.
const aliases={
'Завтрак Tuysqan':'tuysqan-breakfast','Блины с нутеллой и ягодами':'nutella-crepes','Вафли с творожным кремом':'curd-waffles','Крем-суп из цукини':'zucchini-soup','Хрустящие баклажаны':'crispy-aubergine','Греческий салат':'greek-salad','Креветки «Динамит»':'popcorn-shrimp','Паста с соусом песто':'pesto-pasta','Пицца с курицей и грибами':'chicken-mushroom-pizza','Мексиканская пицца':'mexican-pizza','Пицца с казы':'kazy-pizza','Мексиканская тортилья':'mexican-tortilla','Курица яннём':'yangnyeom-chicken','Говядина по-тайски':'thai-beef','Куриный сувлаки':'chicken-souvlaki'
};
const mapping=items.map(i=>{
 const exact=db.filter(d=>norm(d.name_ru)===norm(i.name.ru));
 const d=i.slug?db.find(d=>d.slug===i.slug):(exact.length===1?exact[0]:db.find(d=>d.slug===aliases[i.name.ru]));
 if(d&&d.available){i.price=Number(d.price);return d}return null;
});
window.TUYSQAN_ORDER_MAPPING=mapping.map((d,n)=>({landing:items[n].name.ru,id:d?.id||null,slug:d?.slug||null}));
const read=()=>{try{const a=JSON.parse(localStorage.getItem('tuysqan-system-cart')||'[]');return Array.isArray(a)?a.filter(i=>db.some(d=>d.id===i.id&&d.available)&&Number.isInteger(i.quantity)&&i.quantity>0&&i.quantity<=20):[]}catch{return []}};
let cart=read();
const lang=()=>document.documentElement.lang==='ru'?'ru':'kz';
const t=(ru,kz)=>lang()==='ru'?ru:kz;
const qty=id=>cart.find(i=>i.id===id)?.quantity||0;
const save=()=>{localStorage.setItem('tuysqan-system-cart',JSON.stringify(cart));sync()};
function controls(index){const wrap=document.createElement('div');wrap.className='django-order-controls';wrap.dataset.bridgeIndex=index;const d=mapping[index];if(!d){wrap.innerHTML='<span class="django-order-unavailable"></span>';return wrap}wrap.innerHTML=`<button type="button" data-order-delta="-1" data-order-id="${d.id}">−</button><output data-order-quantity="${d.id}"></output><button type="button" data-order-delta="1" data-order-id="${d.id}">+</button>`;return wrap}
function decorate(){
 document.querySelectorAll('[data-item-card],.menu-list-item').forEach(card=>{if(card.querySelector('.django-order-controls'))return;const index=Number(card.dataset.itemCard??card.querySelector('[data-item-index]')?.dataset.itemIndex);if(Number.isInteger(index)&&items[index])card.append(controls(index))});
 const dialog=document.querySelector('#dialog-content .item-dialog-copy');if(dialog&&!dialog.querySelector('.django-order-controls')){const name=dialog.querySelector('h2')?.textContent;const index=items.findIndex(i=>i.name.ru===name||i.name.kk===name);if(index>=0)dialog.append(controls(index))}
 sync();
}
function setText(el,value){if(el.textContent!==String(value))el.textContent=value}
function sync(){
 document.querySelectorAll('[data-qr-nav-ru]').forEach(el=>setText(el,t(el.dataset.qrNavRu,el.dataset.qrNavKz)));
 document.querySelectorAll('[data-order-nav-label]').forEach(el=>setText(el,t('Заказы','Тапсырыстар')));
 localStorage.setItem('tuysqan-system-language',lang());
 document.querySelectorAll('[data-order-quantity]').forEach(el=>setText(el,qty(Number(el.dataset.orderQuantity))));
 document.querySelectorAll('[data-order-delta]').forEach(b=>{const n=qty(Number(b.dataset.orderId));const label=Number(b.dataset.orderDelta)>0?t('Добавить в заказ','Тапсырысқа қосу'):t('Уменьшить количество','Санын азайту');if(b.getAttribute('aria-label')!==label)b.setAttribute('aria-label',label);b.disabled=Number(b.dataset.orderDelta)<0?n===0:n>=20});
 document.querySelectorAll('.django-order-unavailable').forEach(el=>setText(el,t('Вариант и цена требуют подтверждения','Нұсқасы мен бағасын растау қажет')));
 const count=cart.reduce((s,i)=>s+i.quantity,0),total=cart.reduce((s,i)=>s+i.quantity*Number(db.find(d=>d.id===i.id)?.price||0),0);
 const bar=document.getElementById('django-order-cart');if(!bar)return;bar.hidden=count===0;setText(bar.querySelector('span'),t('К оформлению','Рәсімдеуге')+' · '+count);setText(bar.querySelector('strong'),new Intl.NumberFormat('ru-RU').format(total)+' ₸');
}
document.addEventListener('click',e=>{const b=e.target.closest('[data-order-delta]');if(!b)return;e.preventDefault();e.stopPropagation();const id=Number(b.dataset.orderId);let row=cart.find(i=>i.id===id);if(!row){row={id,quantity:0,comment:''};cart.push(row)}row.quantity=Math.max(0,Math.min(20,row.quantity+Number(b.dataset.orderDelta)));cart=cart.filter(i=>i.quantity>0);save()});
function ready(){const bar=document.createElement('a');bar.id='django-order-cart';bar.className='django-order-cart';bar.href='/checkout/';bar.hidden=true;bar.innerHTML='<span></span><strong></strong><b aria-hidden="true">↗</b>';document.body.append(bar);decorate();const observer=new MutationObserver(()=>decorate());observer.observe(document.getElementById('menu-grid'),{childList:true,subtree:true});const showcase=document.getElementById('showcase-grid');if(showcase)observer.observe(showcase,{childList:true,subtree:true});const dialog=document.getElementById('dialog-content');if(dialog)observer.observe(dialog,{childList:true,subtree:true});new MutationObserver(sync).observe(document.documentElement,{attributes:true,attributeFilter:['lang']});window.addEventListener('storage',()=>{cart=read();sync()});}
document.addEventListener('DOMContentLoaded',ready);
})();
