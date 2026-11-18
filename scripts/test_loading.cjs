'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
let callback;
function image(complete=false,width=0){const classes=new Set(),listeners={};return {nodeType:1,complete,naturalWidth:width,classList:{add:x=>classes.add(x),remove:x=>classes.delete(x),toggle:(x,on)=>on?classes.add(x):classes.delete(x)},matches:q=>q==='img',querySelectorAll:()=>[],getAttribute:()=>'/photo.webp',addEventListener:(name,fn)=>listeners[name]=fn,removeEventListener:name=>delete listeners[name],classes,listeners}}
const cached=image(true,100),pending=image(),broken=image(true,0);
const root={nodeType:1,matches:()=>false,querySelectorAll:()=>[cached,pending,broken]};
vm.runInNewContext(fs.readFileSync('static/js/loading.js','utf8'),{WeakSet,document:{documentElement:root,body:{}},MutationObserver:class{constructor(fn){callback=fn}observe(){}}});
assert(!cached.classes.has('ui-image-pending'),'cached pictures should not flash');
assert(pending.classes.has('ui-image-pending'));pending.naturalWidth=100;pending.listeners.load();assert(!pending.classes.has('ui-image-pending'));assert.equal(Object.keys(pending.listeners).length,0);
assert(broken.classes.has('ui-image-error'));
const dynamic=image();let busy=true,initial=true;
const container={nodeType:1,hasAttribute:()=>initial,querySelector:()=>null,removeAttribute:name=>{if(name==='aria-busy')busy=false;if(name==='data-initial-loading')initial=false}};
callback([{target:container,addedNodes:[dynamic]}]);assert(dynamic.classes.has('ui-image-pending'));assert(!busy);assert(!initial);
dynamic.listeners.error();assert(dynamic.classes.has('ui-image-error'));assert(!dynamic.classes.has('ui-image-pending'));
assert(!/fetch\(|setTimeout\(|setInterval\(/.test(fs.readFileSync('static/js/loading.js','utf8')),'skeletons must not create requests or artificial delays');
console.log('Loading lifecycle: cached/lazy/dynamic/error images, cleanup, aria-busy, no requests or artificial delays PASS');
