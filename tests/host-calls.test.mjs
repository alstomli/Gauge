import test from 'node:test';
import assert from 'node:assert/strict';
import {isHostCallUnavailable} from '../ui/host-calls.js';

test('a host without app tool-call routing is recognised', () => {
  assert.equal(isHostCallUnavailable(new Error('MCP error -32603: IPC not available for MCP tool call')), true);
  assert.equal(isHostCallUnavailable(Object.assign(new Error('Method not found'), {code: -32601})), true);
});

test('ordinary refresh failures still retry', () => {
  assert.equal(isHostCallUnavailable(new Error('MCP error -32603: Internal error')), false);
  assert.equal(isHostCallUnavailable(new Error('Gauge returned an unsupported result.')), false);
  assert.equal(isHostCallUnavailable(null), false);
});
