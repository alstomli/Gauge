import test from 'node:test';
import assert from 'node:assert/strict';
import {estimateCredits, groupModelUsage, wholeChatModelUsage} from '../ui/credits.js';

const group = (model = 'gpt-6.1-sol', input = 1_000_000, cached = 990_000, output = 10_000, calls = 1) =>
  ({model, input_tokens: input, cached_input_tokens: cached, output_tokens: output, calls});

test('cached input is subtracted from fresh input, with output priced separately', () => {
  const result = estimateCredits([group()]);
  assert.equal(result.input, .5);
  assert.equal(result.cached, 2.475);
  assert.equal(result.output, 2.5);
  assert.ok(Math.abs(result.total - 5.475) < 1e-12);
  assert.equal(result.complete, true);
});

test('each recorded model uses its own rates, with no per-call rounding', () => {
  const result = estimateCredits([group('gpt-6.1-sol', 1_000_000, 0, 0), group('gpt-6.1-terra', 1_000_000, 0, 0)]);
  assert.equal(result.total, 75);
  assert.equal(result.pricedCalls, 2);
  const rows = Array.from({length: 100}, () => group('gpt-6.1-sol', 1, 0, 0));
  assert.ok(Math.abs(estimateCredits(rows).total - .005) < 1e-12);
});

test('missing and unknown model rates remain explicitly unpriced', () => {
  const result = estimateCredits([group(), group('future-model'), group(null)]);
  assert.equal(result.complete, false);
  assert.equal(result.pricedCalls, 1);
  assert.equal(result.unpricedCalls, 2);
  assert.deepEqual(result.unpricedModels, ['future-model', 'Model unavailable']);
  assert.ok(Math.abs(result.total - 5.475) < 1e-12);
  assert.equal(estimateCredits([group(null)]).pricedCalls, 0);
  assert.equal(estimateCredits([group('gpt-6.1-sol', 10, 20)]).complete, false);
});

test('whole-chat model totals stay complete when chart history is truncated', () => {
  const total = group('gpt-6.1-sol', 1000, 900, 20, 50);
  const detail = {summary: total, usage_by_model: [total], history_truncated: true, history: []};
  assert.deepEqual(wholeChatModelUsage(detail), [total]);
  assert.equal(wholeChatModelUsage({...detail, usage_by_model: undefined}), null);
  assert.equal(wholeChatModelUsage({...detail, usage_by_model: [group()]}), null);
});

test('complete older payloads can be grouped, but recent slices cannot be priced as a chat', () => {
  const rows = [group('gpt-6.1-sol',100,80,10), group('gpt-6.1-terra',200,100,20)];
  const summary = {calls:2, input_tokens:300,cached_input_tokens:180,output_tokens:30};
  assert.equal(groupModelUsage(rows).length, 2);
  assert.deepEqual(wholeChatModelUsage({summary,history:rows,history_truncated:false}), groupModelUsage(rows));
  assert.equal(wholeChatModelUsage({summary,history:rows.slice(-1),history_truncated:true}), null);
  const empty = estimateCredits([]);
  assert.equal(empty.total, 0);
  assert.equal(empty.complete, true);
});
