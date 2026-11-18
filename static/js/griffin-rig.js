/* Preview-only segmented rig. Neutral pose uses the original pixels. */
(function(root){
 let serial=0;
 const right='M824 482 C868 503 900 459 910 411 C922 362 906 300 922 271 L1030 175 L1080 0 H1300 V760 H895 C877 689 859 643 842 586 Z';
 const left='M0 250 H410 Q496 310 477 399 C470 505 447 590 419 665 C408 705 378 728 367 758 C320 818 261 868 234 921 C171 951 104 1010 0 1080 Z';
 const chest='M603 610 C640 554 728 550 810 589 C849 674 840 827 790 934 C758 1008 715 1074 644 1105 C608 1033 609 925 617 833 C629 733 601 688 603 610 Z';
 const eyes='M567 206 C586 179 619 165 648 179 C673 189 686 211 689 231 C639 229 591 240 567 218 Z M720 147 C734 122 771 117 791 139 C808 156 806 185 796 198 L736 195 Z';
 const base='/static/mascot/tuysqan-griffin.png',blink='/static/mascot/rig-v1/blink-reference.png';
 function markup(state='preparing',layer='assembled',animate=true){
  const id='griffin-rig-'+(++serial),image=(href=base)=>`<image href="${href}" width="1254" height="1254"/>`;
  const definitions=`<defs><clipPath id="${id}-right"><path d="${right}"/></clipPath><clipPath id="${id}-left"><path d="${left}"/></clipPath><clipPath id="${id}-chest"><path d="${chest}"/></clipPath><clipPath id="${id}-eyes"><path d="${eyes}"/></clipPath><clipPath id="${id}-joint-r"><ellipse cx="850" cy="510" rx="43" ry="57"/></clipPath><clipPath id="${id}-joint-l"><ellipse cx="453" cy="400" rx="34" ry="53"/></clipPath><mask id="${id}-body" maskUnits="userSpaceOnUse" x="0" y="0" width="1254" height="1254"><rect width="1254" height="1254" fill="white"/><path d="${right}" fill="black"/><path d="${left}" fill="black"/></mask></defs>`;
  const body=`<g class="griffin-rig-body" mask="url(#${id}-body)">${image()}</g>`;
  const wings=`<g class="griffin-rig-left"><g clip-path="url(#${id}-left)">${image()}</g></g><g class="griffin-rig-right"><g clip-path="url(#${id}-right)">${image()}</g></g>`;
  const breathing=`<g clip-path="url(#${id}-chest)"><g class="griffin-rig-breath">${image()}</g></g>`;
  const eyelids=`<g class="griffin-rig-eyelids" clip-path="url(#${id}-eyes)">${image(blink)}</g>`;
  const joints=`<g clip-path="url(#${id}-joint-r)">${image()}</g><g clip-path="url(#${id}-joint-l)">${image()}</g>`;
  const content=layer==='body'?body:layer==='right'?`<g clip-path="url(#${id}-right)">${image()}</g>`:layer==='left'?`<g clip-path="url(#${id}-left)">${image()}</g>`:layer==='eyelids'?`<g clip-path="url(#${id}-eyes)">${image(blink)}</g>`:layer==='chest'?`<g clip-path="url(#${id}-chest)">${image()}</g>`:body+wings+breathing+joints+eyelids;
  return `<svg class="griffin-rig ${animate&&layer==='assembled'?'is-animated':''} ${layer==='assembled'?'':'is-layer'}" data-motion="${state}" viewBox="-48 -48 1350 1350" xmlns="http://www.w3.org/2000/svg" aria-hidden="true" focusable="false">${definitions}${content}</svg>`;
 }
 function mount(element,state='preparing',layer='assembled',animate=true){element.innerHTML=markup(state,layer,animate)}
 root.TuysqanGriffinRig={markup,mount};
 if(typeof module!=='undefined')module.exports=root.TuysqanGriffinRig;
})(typeof window!=='undefined'?window:globalThis);
