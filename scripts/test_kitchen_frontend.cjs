'use strict';
// Exercise the real kitchen controller with deterministic DOM, network and audio adapters.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('static/js/kitchen.js','utf8');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const food=(id,status='pending')=>({id,name_ru:'Блюдо '+id,name_kz:'Тағам '+id,kind:'food',quantity:1,status,comment:''});
const order=(id,items=[food(id)])=>({public_id:String(id),number:'T'+id,table:'Стол 8',status:'preparing',items,eta_at:null});
function setup(initial=[]){
 class Element{
  constructor(){this.listeners={};this.dataset={};this.textContent='';this.innerHTML='';this.disabled=false;this.attributes={};this.classList={toggle(){}};}
  addEventListener(name,callback){this.listeners[name]=callback;}
  setAttribute(name,value){this.attributes[name]=String(value);}
  querySelector(selector){if(selector==='form')return this.form||(this.form=new Element());return {value:'csrf-fixture'};}
  querySelectorAll(){return this.inputs||[];}
  fire(name,event={}){return (this.listeners[name]||this['on'+name])?.(event);}
  showModal(){this.open=true;}
  close(){this.open=false;this.fire('close');}
  remove(){this.removed=true;}
  focus(){}
 }
 const ids=['kitchen-board','kitchen-initial-orders','kitchen-sound-toggle','kitchen-sound-test','kitchen-sound-status','kitchen-announcement','kitchen-connection','kitchen-updated','kitchen-refresh','kitchen-error','csrf-form',...['all','waiting','preparing','ready'].map(x=>'kitchen-count-'+x)];
 const elements=Object.fromEntries(ids.map(id=>[id,new Element()]));
 elements['kitchen-board'].dataset={actor:'manager-fixture',soundUrl:'/static/audio/new-order.mp3'};
 elements['kitchen-initial-orders'].textContent=JSON.stringify(initial);
 const filters=['all','waiting','preparing','ready'].map(key=>{const e=new Element();e.dataset.kitchenFilter=key;return e;});
 const document=new Element();document.documentElement={lang:'ru'};document.hidden=false;const dialogs=[];
 document.createElement=tag=>{const e=new Element();e.tagName=tag.toUpperCase();if(tag==='dialog')dialogs.push(e);return e;};document.body=new Element();document.body.append=()=>{};document.body.appendChild=()=>{};
 document.getElementById=id=>elements[id];document.querySelectorAll=selector=>selector==='[data-kitchen-filter]'?filters:[];
 const window=new Element(),storage=new Map(),calls=[],pending=[],timers=new Map();let timerId=0;
 class Audio{
  constructor(url){this.url=url;this.listeners={};this.plays=0;this.active=0;this.maxActive=0;this.rejectNext=false;Audio.instance=this;}
  addEventListener(name,fn){this.listeners[name]=fn;}
  removeEventListener(name,fn){if(this.listeners[name]===fn)delete this.listeners[name];}
  play(){this.plays++;if(this.rejectNext){this.rejectNext=false;return Promise.reject(Error('autoplay blocked'));}this.active++;this.maxActive=Math.max(this.maxActive,this.active);return Promise.resolve();}
  pause(){this.active=0;}
  end(){this.active=0;this.listeners.ended?.();}
 }
 const context={document,window,Audio,AbortController,Date,JSON,Set,console,sessionStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value)},setTimeout:(fn,ms)=>{const id=++timerId;timers.set(id,{fn,ms});return id;},clearTimeout:id=>timers.delete(id),fetch:(url,options)=>{calls.push({url,options,payload:options.body?JSON.parse(options.body):null});return new Promise((resolve,reject)=>pending.push({resolve,reject}));}};
 vm.runInNewContext(source,context);
 return {elements,filters,calls,pending,window,document,audio:Audio.instance,timers,dialogs,
  async reply(body,ok=true){assert(pending.length,'Expected pending request');pending.shift().resolve({ok,json:async()=>body});await tick();},
  async fail(){assert(pending.length);pending.shift().reject(Error('offline'));await tick();},
  refresh:()=>elements['kitchen-refresh'].fire('click'),
  chooseMinutes(minutes){const dialog=dialogs.at(-1);assert(dialog?.open,'Expected open food-time dialog');dialog.inputs=[...dialog.innerHTML.matchAll(/data-food-id="(\d+)"/g)].map(m=>({value:String(minutes),dataset:{foodId:m[1],original:''}}));dialog.querySelector('form').fire('submit',{preventDefault(){}});},
  cancelMinutes(){const dialog=dialogs.at(-1);assert(dialog?.open,'Expected open food-time dialog');dialog.fire('cancel',{preventDefault(){}});},
  action(id,action){return elements['kitchen-board'].fire('click',{target:{closest:()=>({dataset:{kitchenId:String(id),kitchenAction:action},disabled:false})}});},
 };
}
(async()=>{
 const a=order(1),s=setup([a]);
 assert.equal(s.audio.plays,0,'Initial rendered queue must be silent');
 assert.equal(s.calls.length,1);s.refresh();assert.equal(s.calls.length,1,'No overlapping poll');
 await s.reply({orders:[a]});assert.equal(s.audio.plays,0,'Initial unchanged response stays silent');
 s.elements['kitchen-sound-toggle'].fire('click');await tick();assert.equal(s.audio.plays,1,'Gesture unlock/test phrase');s.audio.end();await tick();
 s.refresh();await s.reply({orders:[a,order(2),order(3)]});
 assert.equal(s.audio.plays,2,'First new phrase starts immediately');assert.equal(s.audio.maxActive,1);
 s.audio.end();await tick();assert.equal(s.audio.plays,3,'Second new order waits its turn');s.audio.end();await tick();assert.equal(s.audio.maxActive,1,'Announcements never overlap');
 s.refresh();await s.reply({orders:[a,order(2),order(3)]});assert.equal(s.audio.plays,3,'Repeated polling does not announce IDs again');
 s.refresh();await s.fail();assert.match(s.elements['kitchen-error'].textContent,/последние полученные/);
 s.refresh();await s.reply({orders:[a,order(2),order(3),order(4)]});assert.equal(s.audio.plays,4,'Network recovery announces only unseen order');s.audio.end();await tick();
 s.filters[2].fire('click');s.filters[0].fire('click');assert.equal(s.audio.plays,4,'Filters never replay notifications');
 s.elements['kitchen-sound-toggle'].fire('click');s.refresh();await s.reply({orders:[a,order(5)]});assert.equal(s.audio.plays,4,'Muted arrivals remain visual only');
 s.audio.rejectNext=true;s.elements['kitchen-sound-toggle'].fire('click');await tick();assert.equal(s.elements['kitchen-sound-toggle'].attributes['aria-pressed'],'false');assert.match(s.elements['kitchen-sound-status'].textContent,/недоступен/);
 const media=setup([]);await media.reply({orders:[]});media.elements['kitchen-sound-toggle'].fire('click');await tick();media.audio.listeners.error();await tick();assert.equal(media.elements['kitchen-sound-toggle'].attributes['aria-pressed'],'false','Media decoding errors must switch sound off');
 const ready=setup([order(10,[food(10,'ready'),{id:99,kind:'drink',status:'pending'}])]);
 assert.equal(ready.elements['kitchen-count-ready'].textContent,1,'Food readiness ignores pending drinks and global preparing status');assert.match(ready.elements['kitchen-board'].innerHTML,/is-ready/);assert(!ready.elements['kitchen-board'].innerHTML.includes('data-kitchen-action='));await ready.reply({orders:[]});
 const mixed=order(20,[food(20,'pending'),food(21,'ready'),{id:99,kind:'drink',status:'pending'}]),m=setup([mixed]);await m.reply({orders:[mixed]});
 const action=m.action(20,'preparing');await tick();assert.equal(m.calls.filter(c=>c.payload).length,0,'No mutation before kitchen chooses food time');
 const waitingCount=m.calls.length;m.refresh();await m.action(20,'preparing');assert.equal(m.calls.length,waitingCount,'Polling is paused while choosing time');assert.equal(m.dialogs.length,1,'Rapid clicks must not create a second dialog');
 m.chooseMinutes(20);await tick();assert.deepEqual(m.calls.at(-1).payload,{action:'food_eta',items:[{item_id:20,eta:20}]},'Kitchen assigns only food ETA, even for manager');
 const count=m.calls.length;m.refresh();assert.equal(m.calls.length,count,'Poll is blocked during a state mutation');
 await m.reply({ok:true});assert.equal(m.calls.at(-1).url,'/api/kitchen/');await m.reply({orders:[order(20,[food(20,'preparing'),food(21,'ready'),{id:99,kind:'drink',status:'pending'}])]});await action;
 assert.equal(m.calls.filter(c=>c.payload).length,1,'Only the food station assignment is sent');
 const done=m.action(20,'ready');await tick();assert.deepEqual(m.calls.at(-1).payload,{action:'item_ready',item_id:20});await m.reply({ok:true});await m.reply({orders:[order(20,[food(20,'ready'),food(21,'ready'),{id:99,kind:'drink',status:'pending'}])]});await done;assert.equal(m.elements['kitchen-count-ready'].textContent,1);
 const cancelled=setup([order(25)]);await cancelled.reply({orders:[order(25)]});const cancelAction=cancelled.action(25,'preparing');await tick();cancelled.cancelMinutes();await cancelAction;assert.equal(cancelled.calls.filter(c=>c.payload).length,0,'Canceling the time dialog must not mutate an order');
 const editing=setup([order(26,[food(26,'preparing')])]);await editing.reply({orders:[order(26,[food(26,'preparing')])]});const editAction=editing.action(26,'eta');await tick();editing.chooseMinutes(15);await tick();assert.deepEqual(editing.calls.at(-1).payload,{action:'food_eta',items:[{item_id:26,eta:15}]});await editing.reply({ok:true});await editing.reply({orders:[order(26,[food(26,'preparing')])]});await editAction;
 const failed=setup([order(30)]);await failed.reply({orders:[order(30)]});const failedAction=failed.action(30,'preparing');await tick();failed.chooseMinutes(10);await tick();await failed.reply({error:'Action failed'},false);await failed.reply({orders:[order(30)]});await failedAction;assert.equal(failed.elements['kitchen-error'].textContent,'Action failed','Refreshing must not erase the mutation error');
 console.log('Kitchen controller: silent baseline, deduplication, sequential audio, mute/autoplay rejection, network recovery, food ETA selection/cancel/edit, food readiness and food-only actions PASS');
})().catch(error=>{console.error(error);process.exitCode=1;});
