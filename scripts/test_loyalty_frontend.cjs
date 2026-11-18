// Test the real QR submission controller without any browser or working-order calls.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('static/js/app.js','utf8');
const state=source.slice(source.indexOf('let checkoutOffer='),source.indexOf('function renderCart()'));
const handlers=source.slice(source.indexOf("$('#checkout-loyalty-change')?.addEventListener"),source.indexOf('const states='));
function setup({percent=7,choice=true,failFirst=false,valid=true,expiredFirst=false}={}){
 const storage=new Map(),calls=[],listeners={},button={disabled:false},error={textContent:''},form={reportValidity:()=>valid,addEventListener:(name,fn)=>listeners[name]=fn};
 let submissions=0,choices=0;
 const context={console,document:{},sessionStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,String(value)),removeItem:key=>storage.delete(key)},localStorage:{removeItem:()=>{}},location:{href:''},cart:[{id:1,quantity:1}],catalog:[{id:1,price:1860}],crypto:{randomUUID:()=>`key-${calls.length}`},tr:a=>a,money:x=>String(x),data:()=> 'table-qa',renderCart:()=>{},error:(_,e)=>error.textContent=e.message,FormData:class{get(name){return {payment_method:'cash',drink_preference:null,comment:''}[name]}},$:(selector)=>selector==='#checkout-form'?form:selector==='#submit-order'?button:selector==='#checkout-error'?error:selector==='#drink-preference-panel'?{hidden:true}:null,$$:()=>[],requestLoyaltyChoice:async(offer,total)=>{choices++;assert.equal(total,1860);return choice},api:async(path,payload)=>{calls.push({path,payload});if(path.includes('discount-offer'))return {percent,token:'quote-'+calls.length};submissions++;if(failFirst&&submissions===1)throw Error('network');if(expiredFirst&&submissions===1)throw Object.assign(Error('refresh'),{status:400,code:'offer_expired'});return {redirect:'/orders/synthetic/'}}};
 vm.createContext(context);vm.runInContext(state+handlers,context);
 return {context,storage,calls,error,submit:()=>listeners.submit({preventDefault:()=>{},target:form}),choices:()=>choices};
}
(async()=>{
 const retry=setup({failFirst:true});await retry.submit();assert(retry.storage.has('tuysqan-checkout-attempt'));const first=JSON.stringify(retry.calls.at(-1).payload);await retry.submit();assert.equal(JSON.stringify(retry.calls.at(-1).payload),first);assert.equal(retry.calls.filter(c=>c.path.includes('discount-offer')).length,1);assert.equal(retry.choices(),1);assert.equal(retry.context.location.href,'/orders/synthetic/');assert(!retry.storage.has('tuysqan-checkout-attempt'));
 const declined=setup({choice:false});await declined.submit();assert.equal(declined.calls.at(-1).payload.discount_choice,false);assert(declined.calls.at(-1).payload.discount_offer_token);
 const none=setup({percent:0});await none.submit();assert.equal(none.choices(),0);assert.equal(none.calls.at(-1).payload.discount_choice,false);
 const cancelled=setup({choice:null});await cancelled.submit();assert.equal(cancelled.calls.length,1);assert(!cancelled.storage.has('tuysqan-checkout-attempt'));
 const invalid=setup({valid:false});await invalid.submit();assert.equal(invalid.calls.length,0);
 const expired=setup({expiredFirst:true});await expired.submit();assert(!expired.storage.has('tuysqan-checkout-attempt'));await expired.submit();assert.equal(expired.choices(),2);
 console.log('QR loyalty frontend: exact network retry, explicit decline, zero offer, cancellation, validation and quote refresh PASS');
})().catch(error=>{console.error(error);process.exitCode=1});
