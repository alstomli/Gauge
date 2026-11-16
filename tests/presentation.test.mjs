import test from 'node:test';
import assert from 'node:assert/strict';
import {createSidePanel} from '../ui/presentation.js';

test('opening an inline dashboard automatically requests the expanded panel', async () => {
  let state;const calls=[];
  const panel=createSidePanel({requestDisplayMode:async params=>{calls.push(params.mode);return {mode:'fullscreen'};}},value=>{state=value;});
  await panel.update({displayMode:'inline',availableDisplayModes:['inline','fullscreen']});
  assert.deepEqual(calls,['fullscreen']);
  assert.equal(state.mode,'fullscreen');assert.equal(state.pending,false);assert.equal(state.message,'');
});

test('a host that already opened the panel needs no extra request or reopening after dismissal', async () => {
  let calls=0;
  const panel=createSidePanel({requestDisplayMode:async()=>{calls++;}},()=>{});
  await panel.update({displayMode:'fullscreen',availableDisplayModes:['fullscreen']});
  await panel.update({displayMode:'inline'});
  assert.equal(calls,0);
});

test('unsupported hosts retain a usable dashboard without sending invalid placement requests', async () => {
  let state,calls=0;
  const panel=createSidePanel({requestDisplayMode:async()=>{calls++;}},value=>{state=value;});
  await panel.update({displayMode:'inline',availableDisplayModes:['inline']});
  assert.equal(calls,0);assert.equal(state.mode,'inline');assert.match(state.message,/does not offer/);
});

test('late capability discovery opens the panel, preserving partial context updates', async () => {
  let state,calls=0;
  const panel=createSidePanel({requestDisplayMode:async()=>{calls++;return {mode:'fullscreen'};}},value=>{state=value;});
  await panel.update({displayMode:'inline'});
  assert.equal(calls,0);
  await panel.update({availableDisplayModes:['inline','fullscreen']});
  await panel.update({theme:'dark'});
  assert.equal(calls,1);assert.equal(state.mode,'fullscreen');
});

test('context updates do not overlap requests or reopen a dismissed panel', async () => {
  let state,complete,calls=0;
  const panel=createSidePanel({requestDisplayMode:()=>{calls++;return new Promise(resolve=>{complete=resolve;});}},value=>{state=value;});
  const opening=panel.update({displayMode:'inline',availableDisplayModes:['inline','fullscreen']});
  assert.equal(state.pending,true);
  await panel.update({theme:'dark'});
  assert.equal(calls,1);
  complete({mode:'fullscreen'});await opening;
  await panel.update({displayMode:'inline'});
  assert.equal(calls,1);assert.equal(state.pending,false);
});

test('a denial or error never claims that the panel opened and never loops', async () => {
  for (const fail of [false,true]) {
    let state,calls=0;
    const panel=createSidePanel({requestDisplayMode:async()=>{calls++;if(fail)throw Error('Host denied');return {mode:'inline'};}},value=>{state=value;});
    await panel.update({displayMode:'inline',availableDisplayModes:['inline','fullscreen']});
    await panel.update({theme:'light'});
    assert.equal(calls,1);assert.equal(state.mode,'inline');assert.equal(state.pending,false);
    assert.match(state.message,fail?/could not open/:/kept the monitor/);
  }
});
