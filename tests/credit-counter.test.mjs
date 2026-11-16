import test from 'node:test';
import assert from 'node:assert/strict';
import {createCreditCounter} from '../ui/credit-counter.js';

function fixture() {
  const elements = Object.fromEntries(['input','cached','output','total'].map(key => [key, {textContent:'—',dataset:{}}]));
  const queue = new Map();let time=0,id=0,reduced=false;
  const counter = createCreditCounter(elements, {format:value=>value.toFixed(2),duration:700,now:()=>time,
    requestFrame:callback=>{queue.set(++id,callback);return id;},cancelFrame:id=>queue.delete(id),reduceMotion:()=>reduced});
  return {counter,elements,queue,setReduced:value=>{reduced=value;},step:next=>{
    time=next;const callbacks=[...queue.values()];queue.clear();callbacks.forEach(callback=>callback(time));
  }};
}
const values = (input=10,cached=20,output=30) => ({input,cached,output,total:input+cached+output});

test('all credit amounts rise together and finish on the exact formatted totals', () => {
  const f=fixture();f.counter.update(values());
  assert.equal(f.elements.total.textContent,'0.00');
  f.step(350);
  assert.ok(Number(f.elements.total.textContent)>0 && Number(f.elements.total.textContent)<60);
  assert.equal(f.elements.cached.dataset.counting,'true');
  f.step(700);
  assert.equal(f.elements.input.textContent,'10.00');
  assert.equal(f.elements.cached.textContent,'20.00');
  assert.equal(f.elements.output.textContent,'30.00');
  assert.equal(f.elements.total.textContent,'60.00');
  assert.equal(f.queue.size,0);assert.equal(f.elements.cached.dataset.counting,undefined);
});

test('unchanged refreshes do not restart or extend an animation', () => {
  const f=fixture();f.counter.update(values());f.step(350);
  const queued=[...f.queue.keys()];f.counter.update(values());
  assert.deepEqual([...f.queue.keys()],queued);
  f.step(700);f.counter.update(values());
  assert.equal(f.queue.size,0);assert.equal(f.elements.total.textContent,'60.00');
});

test('new totals arriving mid-animation continue from the current displayed amount', () => {
  const f=fixture();f.counter.update(values());f.step(200);
  const displayed=f.elements.total.textContent;
  f.counter.update(values(20,30,40));
  assert.equal(f.elements.total.textContent,displayed);
  f.step(550);assert.ok(Number(f.elements.total.textContent)>Number(displayed));
  f.step(900);assert.equal(f.elements.total.textContent,'90.00');assert.equal(f.queue.size,0);
});

test('reduced motion and downward corrections settle immediately', () => {
  const f=fixture();f.setReduced(true);f.counter.update(values());
  assert.equal(f.elements.total.textContent,'60.00');assert.equal(f.queue.size,0);
  f.setReduced(false);f.counter.update(values(20,30,40));f.step(200);
  f.setReduced(true);f.step(220);
  assert.equal(f.elements.total.textContent,'90.00');assert.equal(f.queue.size,0);
  f.setReduced(false);f.counter.update(values());
  assert.equal(f.elements.total.textContent,'60.00');assert.equal(f.queue.size,0);
});

test('unavailable estimates cancel animation, and temporary loading can preserve the last reading', () => {
  const f=fixture();f.counter.update(values());f.step(700);
  f.counter.clear({preserveValue:true});assert.equal(f.elements.total.textContent,'—');
  f.counter.update(values(20,30,40),{partial:true});
  assert.equal(f.elements.total.textContent,'≥ 60.00');
  f.counter.update(values(),{available:false});
  assert.equal(f.elements.total.textContent,'—');assert.equal(f.queue.size,0);
  f.counter.update(values());f.counter.destroy();assert.equal(f.queue.size,0);
});
