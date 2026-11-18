'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('static/js/pos.js','utf8');
const boot=source.slice(0,source.indexOf('const posForm='));
const functions=['function posSaveDraft(','async function posShowSaved(','async function posRecover(','async function refreshCashier('].map(prefix=>{
 const line=source.split('\n').find(line=>line.startsWith(prefix));assert(line,'Missing production function '+prefix);return line;
}).join('\n');
function setup(draft){
 let seq=0;const store=new Map(),nodes={},calls=[];
 if(draft!==undefined)store.set('tuysqan-pos-test-cashier',JSON.stringify(draft));
 const ctx={location:{search:'',pathname:'/admin/pos/'},URLSearchParams,history:{replaceState:()=>{}},catalog:[{id:1}],data:()=> 'test-cashier',crypto:{randomUUID:()=> 'fresh-'+(++seq)},
  sessionStorage:{getItem:k=>store.get(k)||null,setItem:(k,v)=>store.set(k,v),removeItem:k=>store.delete(k)},
  $:selector=>nodes[selector]||(nodes[selector]={value:'table-eight',hidden:false,textContent:''}),
  posForm:{querySelector:()=>({value:'fixture'})},renderPosResult:()=>calls.push('render-result'),posSetBusy:()=>{},posError:()=>{},posLoyaltyOffer:null,
  posRequest:async url=>{calls.push(url);throw Object.assign(Error('not found'),{status:404})}};
 vm.createContext(ctx);vm.runInContext(boot+'\n'+functions,ctx);
 return {ctx,store,calls,run:code=>vm.runInContext(code,ctx),value:code=>JSON.parse(vm.runInContext('JSON.stringify('+code+')',ctx))};
}
(async()=>{
 // Upgrade from old storage: a saved sale must not masquerade as a draft.
 const old=setup({key:'old-key',saved_id:'old-sale',pending:false,items:[{id:1,quantity:1}]});
 assert.equal(old.value('posEntries').length,0);assert(!old.store.size);await old.ctx.posRecover();assert.equal(old.calls.length,0);
 // Navigation/reload still restores unfinished baskets and their idempotency keys.
 const draft=setup({key:'draft-key',pending:false,items:[{id:1,quantity:2}],fulfillment:'takeaway'});
 assert.equal(draft.run('posKey'),'draft-key');assert.equal(draft.value('posEntries')[0].quantity,2);assert.equal(draft.value('posDraft').fulfillment,'takeaway');
 // Uncertain submission: use its key, not any legacy saved_id; a miss permits retry.
 const pending=setup({key:'pending-key',saved_id:'stale-sale',pending:true,items:[{id:1,quantity:1}],attempt:{idempotency_key:'pending-key',items:[{id:1,quantity:1}]}});
 await pending.ctx.posRecover();assert.deepEqual(pending.calls,['/api/staff/pos/status/?key=pending-key']);assert.equal(pending.run('posKey'),'pending-key');assert.equal(pending.run('posPending'),false);assert.equal(pending.value('posEntries').length,1);
 // Known success clears the draft, while retaining the on-screen result.
 const saved=setup({key:'submission-key',pending:true,items:[{id:1,quantity:1}]});
 await saved.ctx.posShowSaved({public_id:'saved-sale'});assert.equal(saved.run('posSavedOrder.public_id'),'saved-sale');assert.equal(saved.value('posEntries').length,0);assert.equal(saved.store.size,0);
 saved.ctx.posSaveDraft();assert.equal(saved.store.size,0,'Later saves must not resurrect a completed draft');
 const reload=setup();assert.equal(reload.value('posEntries').length,0);await reload.ctx.posRecover();assert.equal(reload.calls.length,0);
 // Known success recovered after a lost response is equally retired.
 const recovered=setup({key:'retry-key',pending:true,items:[{id:1,quantity:1}]});recovered.ctx.posRequest=async()=>({order:{public_id:'recovered-sale'}});
 await recovered.ctx.posRecover();assert.equal(recovered.run('posSavedOrder.public_id'),'recovered-sale');assert.equal(recovered.store.size,0);
 // A late status response must not resurrect a previous sale after New sale.
 const race=setup();race.run("posSavedOrder={public_id:'previous-sale'}");let finish;
 race.ctx.posRequest=()=>new Promise(resolve=>{finish=resolve});const request=race.ctx.refreshCashier();race.run('posSavedOrder=null');finish({order:{public_id:'previous-sale'}});await request;
 assert.equal(race.run('posSavedOrder'),null);assert.equal(race.calls.length,0);
 for(const malformed of [null,[],"invalid-shape"]){const state=setup(malformed);assert.equal(state.value('posEntries').length,0)}
 console.log('POS recovery: legacy sale, unfinished draft, uncertain submission, known/recovered success, reload and late-response regressions passed.');
})().catch(error=>{console.error(error);process.exitCode=1});
