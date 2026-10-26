/* The accepted scientific-map palette and white-to-hue probability shading. */
(function(root){
 'use strict';
 const colors=['#a6b2bb','#438bb5','#e7a13e','#cf704b'];
 const labels=['Not reached','Endemic at year 0','Spread from main enzootic area','Spread from translocation nidi'];
 function source(result,i,year){
  const a=result.arrival[i],b=result.baseline_arrival[i];
  if(b===0)return 1;
  if(a<0||a>year)return 0;
  return b<0||a<b-1e-6?3:2;
 }
 function shade(code,value){
  const p=Math.max(0,Math.min(1,Number(value))),hex=colors[code].slice(1);
  const rgb=[0,2,4].map(k=>Math.round(255*(1-p*(1-parseInt(hex.slice(k,k+2),16)/255))));
  return '#'+rgb.map(v=>v.toString(16).padStart(2,'0')).join('');
 }
 function count(result,year){const n=[0,0,0,0];for(let i=0;i<result.arrival.length;i++)n[source(result,i,year)]++;return n;}
 const api={colors,labels,source,shade,count};root.RRVMapStyle=api;
 if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(globalThis);
