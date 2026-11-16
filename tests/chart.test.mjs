import test from 'node:test';
import assert from 'node:assert/strict';
import {reuseScale, axisPercent} from '../ui/chart.js';

test('clustered percentages get a readable range instead of a full-height axis', () => {
  const scale = reuseScale([.994, .996, .998]);
  assert.ok(scale.min > .98);
  assert.ok(scale.min <= .994 && scale.max >= .998);
  assert.ok(scale.max - scale.min < .03);
  assert.ok(scale.ticks.length >= 3 && scale.ticks.length <= 7);
  assert.equal(axisPercent(.9925), '99.25%');
});

test('edge values, flat series and missing usage retain a finite bounded range', () => {
  for (const values of [[0], [1], [.995, .995], [0, 1], [], [NaN, null]]) {
    const scale = reuseScale(values);
    assert.ok(scale.min >= 0 && scale.max <= 1 && scale.max > scale.min);
    assert.equal(scale.ticks[0], scale.min);
    assert.equal(scale.ticks.at(-1), scale.max);
    for (const value of values.filter(Number.isFinite)) {
      assert.ok(value >= scale.min && value <= scale.max);
    }
  }
});

test('the axis follows a newly visible low call and never clips recorded reuse', () => {
  const tight = reuseScale([.994, .998]);
  const wide = reuseScale([.46, .994, .998]);
  assert.ok(wide.min <= .46 && wide.min < tight.min);
  for (let i = 0; i <= 1000; i++) {
    const values = [i / 1000, Math.min(1, i / 1000 + .023)];
    const scale = reuseScale(values);
    assert.ok(values.every(value => value >= scale.min && value <= scale.max));
    assert.ok(scale.ticks.every(Number.isFinite));
  }
});
