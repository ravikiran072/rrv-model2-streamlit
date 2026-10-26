/* Optional: node test_map_style.js */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const style=require('./map_style.js');
const result=JSON.parse(fs.readFileSync(path.join(__dirname,'provenance/accepted_scenario_reference.json')));
assert.deepEqual(style.colors,['#a6b2bb','#438bb5','#e7a13e','#cf704b']);
assert.deepEqual(style.count(result,20),[1090,877,815,314]);
assert.deepEqual(style.count(result,0),[2219,877,0,0]);
for(let c=0;c<4;c++){
 assert.equal(style.shade(c,0),'#ffffff');
 assert.equal(style.shade(c,1),style.colors[c]);
 const rgb=style.colors[c].slice(1).match(/../g).map(v=>Math.round((255+parseInt(v,16))/2));
 assert.equal(style.shade(c,.5),'#'+rgb.map(v=>v.toString(16).padStart(2,'0')).join(''));
}
assert.equal(style.source(result,149,8),0);
assert.equal(style.source(result,149,9),3);
console.log('Approved palette, probability shading, annual attribution and map totals verified.');
