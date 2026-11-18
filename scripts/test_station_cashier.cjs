'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const cashier=fs.readFileSync('static/js/cashier.js','utf8');
const detail=cashier.slice(cashier.indexOf('function cashStationTimes('),cashier.indexOf('async function refreshCashier('));
const output={innerHTML:''};
const ctx={lang:'ru',document:{body:{dataset:{role:'cashier'}}},$:()=>output,tr:(r,k)=>r,esc:String,money:String,cashTime:v=>v||'—',cashTable:o=>o.table,cashMethod:()=>'',cashOrderLoyalty:()=>'',state:x=>x,cashierKitchenRelease:'acceptance',cashButton:(action,label)=>`<button data-action="${action}">${label}</button>`};
vm.createContext(ctx);vm.runInContext(fs.readFileSync('static/js/drink-planning.js','utf8'),ctx);vm.runInContext(detail,ctx);
const item=(kind,status)=>({kind,status,name_ru:kind,quantity:1,line_total:100});
function render(items,extra={}){ctx.renderCashierDetail({public_id:'qa',table:'Стол 8',number:'T1',status:'preparing',payment_status:'unpaid',items,drink_plan:{code:'preparing',started:items.some(i=>i.kind==='drink'&&i.status==='preparing')},...extra});return output.innerHTML}
let html=render([item('food','pending')]);assert(!html.includes('data-action="drink_eta"'));assert(!html.includes('data-action="ready"'));assert(html.includes('Время назначит кухня'));
html=render([item('food','ready')]);assert(html.includes('data-action="ready"'));assert(!html.includes('data-action="drink_eta"'));
html=render([item('food','ready'),item('drink','pending')],{food_eta_at:'12:20',drink_eta_at:'12:05'});assert(!html.includes('data-action="ready"'));assert(html.includes('data-action="drink_eta"'));assert(html.includes('Начать напитки сейчас'));assert(!html.includes('12:05'));assert(html.includes('Ожидают начала'));assert(!html.includes('data-action="eta"'));
html=render([item('food','preparing'),item('drink','preparing')],{food_eta_at:'12:20',drink_eta_at:'12:05'});assert(html.includes('12:20'));assert(html.includes('12:05'));assert(html.includes('Длительность группы напитков'));assert(!html.includes('data-action="ready"'));
html=render([item('food','ready'),item('drink','ready')]);assert(html.includes('data-action="ready"'));assert(!html.includes('data-action="drinks_ready"'));
html=render([item('food','ready')],{status:'ready'});assert(html.includes('data-action="serve"'));assert(!html.includes('data-action="ready"'));

const pos=fs.readFileSync('static/js/pos.js','utf8');
const basket=pos.slice(pos.indexOf('function renderPosBasket('),pos.indexOf('function posError('));
const elements={},radios=[{},{},{}];let products=[],mode='dine_in';
const selector=s=>{if(s==='#pos-table-token')return {value:'table'};return elements[s]||(elements[s]={textContent:'',innerHTML:'',hidden:false,disabled:false})};
const pc={posItems:()=>products,$:selector,$$:s=>s==='[name=drink_eta]'?radios:[],posForm:{querySelector:()=>({value:mode})},posImage:()=>'',posDiscountedTotal:()=>0,renderPosLoyalty:()=>{},posCount:()=>0,posBusy:false,tr:(r,k)=>r,esc:String,money:String,lang:'ru'};
vm.createContext(pc);vm.runInContext(basket,pc);
products=[{id:1,quantity:1,product:{kind:'food',name_ru:'QA',price:100}}];pc.renderPosBasket();assert.equal(elements['#pos-eta-section'].hidden,true);assert(radios.every(r=>!r.required&&r.disabled));
products=[{id:2,quantity:1,product:{kind:'drink',name_ru:'QA drink',price:100}}];mode='takeaway';pc.renderPosBasket();assert.equal(elements['#pos-eta-section'].hidden,false);assert(radios.every(r=>!r.required&&!r.disabled));assert.equal(elements['#pos-eta-label'].textContent,'Длительность всей группы напитков');
const payloadLine=pos.split('\n').find(line=>line.includes('const payload={items:posEntries.map'));
Object.assign(pc,{posEntries:[{id:2,quantity:1}],mode:'takeaway',values:{get:n=>({drink_eta:'10',payment_method:'cash',comment:''}[n]||'')},posKey:'qa-key'});vm.runInContext(payloadLine+';globalThis.savedPayload=payload;',pc);assert.equal(pc.savedPayload.drink_eta,10);assert(!Object.hasOwn(pc.savedPayload,'eta'));
console.log('Cashier/POS stations: food-only, mixed readiness, explicit overall ready, separate clocks, optional drink-only ETA and takeaway payload PASS');
