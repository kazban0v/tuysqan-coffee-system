// Exercise the actual guest polling block with a controllable clock/network.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('static/js/app.js','utf8');
const start=source.indexOf("if($('#order-detail')){\n let guestPollTimer");
const end=source.indexOf("if($('#pos-form'))",start);
assert(start>=0&&end>start);
let timers=new Map(),next=0,requests=0,resolveRequest,rejectRequest,rendered=[],events=[];
const listeners={},windowListeners={};
const document={hidden:false,addEventListener:(name,fn)=>listeners[name]=fn};
const sandbox={document,window:{addEventListener:(name,fn)=>windowListeners[name]=fn,dispatchEvent:event=>events.push(event)},CustomEvent:class{constructor(name,{detail}){this.type=name;this.detail=detail}},$:()=>({}),data:()=>({public_id:'synthetic'}),setTimeout:(fn,ms)=>{timers.set(++next,{fn,ms});return next},clearTimeout:id=>timers.delete(id),renderOrder:o=>rendered.push(o),api:()=>{requests++;return new Promise((resolve,reject)=>{resolveRequest=resolve;rejectRequest=reject})}};
const tick=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
 vm.runInNewContext(source.slice(start,end),sandbox);
 assert.equal(timers.size,1);
 const first=[...timers.values()][0];first.fn();assert.equal(requests,1);
 windowListeners.online();assert.equal(requests,1,'no overlapping cycles');
 rejectRequest(new Error('offline'));await tick();
 assert.equal(events.at(-1).detail.online,false);assert.equal(timers.size,1);assert.equal([...timers.values()][0].ms,15000);
 document.hidden=true;listeners.visibilitychange();assert.equal(timers.size,0);
 windowListeners.online();assert.equal(requests,1,'hidden tab must not request');
 document.hidden=false;listeners.visibilitychange();assert.equal(requests,2);
 resolveRequest({order:{status:'served'}});await tick();
 assert.equal(rendered.at(-1).status,'served');assert.equal(events.at(-1).detail.online,true);assert.equal(timers.size,1);assert.equal([...timers.values()][0].ms,12000);
 document.hidden=true;listeners.visibilitychange();assert.equal(timers.size,0);
 console.log('Guest polling: single cycle, hidden pause, error backoff and recovery PASS');
})().catch(error=>{console.error(error);process.exitCode=1});
