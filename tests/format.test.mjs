import test from 'node:test';
import assert from 'node:assert/strict';
import {formatReuse} from '../ui/format.js';

test('near-perfect reuse never masquerades as an exact cache hit',()=>{
  assert.equal(formatReuse(403840/404003),'99.96%');
  assert.equal(formatReuse(0.999999),'>99.99%');
  assert.equal(formatReuse(1),'100.00%');
});

test('zero usage and missing usage remain distinct',()=>{
  assert.equal(formatReuse(0),'0.00%');
  assert.equal(formatReuse(null),'Unavailable');
  assert.equal(formatReuse(NaN),'Unavailable');
  assert.equal(formatReuse(0.000001),'<0.01%');
});
