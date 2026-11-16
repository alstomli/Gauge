import asyncio
import json
import sys
import tempfile
import threading
import unittest
from datetime import timedelta
from pathlib import Path

from cache_monitor.collector import Collector
from cache_monitor.service import Monitor
from cache_monitor.store import Store


def event(kind, payload, second=0):
    return {"type": kind, "timestamp": f"2026-11-16T12:00:{second:02d}Z", "payload": payload}


def counts(inputs=1000, cached=900, output=20):
    return {"input_tokens": inputs, "cached_input_tokens": cached, "output_tokens": output}


def meta(sid="chat-1"):
    return event("session_meta", {"id": sid, "cwd": "D:/Project", "source": "vscode", "cli_version": "test"})


def response(rid="response-1", usage=None, total=None, second=1, sid="chat-1", turn="turn-1"):
    usage = usage if usage is not None else counts()
    return event("token_usage_record", {"thread_id": sid, "turn_id": turn, "response_id": rid,
                 "usage": usage, "thread_token_usage": total if total is not None else usage}, second)


def snapshot(total, second=1):
    return event("event_msg", {"type": "token_count", "info": {"total_token_usage": total,
                 "last_token_usage": counts()}}, second)


def append(path, records):
    with path.open("ab") as handle:
        for row in records:
            handle.write(json.dumps(row).encode() + b"\n")


class MonitorTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.logs = self.base / "logs"
        self.logs.mkdir()
        self.database = self.base / "usage.sqlite3"
        self.store = Store(self.database)
        self.collector = Collector(self.logs, self.store)
        self.log = self.logs / "rollout.jsonl"

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_primary_dedup_weighted_totals_and_prompt_grouping(self):
        a, b, total = counts(), counts(100, 0, 5), counts(1100, 900, 25)
        append(self.log, [meta(), event("turn_context", {"model": "test-model", "turn_id": "turn-1"}),
                          response(usage=a), snapshot(a), response("response-2", b, total, 2),
                          snapshot(total, 2), response("response-2", b, total, 2)])
        self.collector.scan(); self.collector.scan()
        history = self.store.history("chat-1")
        self.assertEqual(history["summary"]["calls"], 2)
        self.assertAlmostEqual(history["summary"]["cache_reuse"], 900/1100)
        self.assertEqual(history["quality"]["status"], "verified")
        self.assertEqual(history["turns"][0]["summary"]["calls"], 2)
        self.assertEqual(history["latest"]["model"], "test-model")

    def test_partial_line_restart_and_replay(self):
        append(self.log, [meta(), response()])
        tail = json.dumps(response("response-2", counts(100, 50, 5), counts(1100, 950, 25), 2)).encode()
        with self.log.open("ab") as f: f.write(tail[:50])
        self.collector.scan()
        self.assertEqual(self.store.history("chat-1")["summary"]["calls"], 1)
        self.store.close(); self.store = Store(self.database); self.collector = Collector(self.logs, self.store)
        with self.log.open("ab") as f: f.write(tail[50:] + b"\n")
        self.collector.scan()
        self.assertEqual(self.store.history("chat-1")["summary"]["calls"], 2)
        self.log.write_bytes(b"")
        append(self.log, [meta(), response(), response("response-2", counts(100, 50, 5), counts(1100, 950, 25), 2)])
        self.collector.scan()
        self.assertEqual(self.store.history("chat-1")["summary"]["calls"], 2)
        self.assertEqual(self.store.history("chat-1")["quality"]["status"], "verified")

    def test_snapshot_baseline_resets_and_primary_supersedes(self):
        append(self.log, [meta(), snapshot(counts()), snapshot(counts()), snapshot(counts(1500, 1300, 30), 2),
                          snapshot(counts(100, 0, 1), 3), snapshot(counts(200, 50, 2), 4)])
        self.collector.scan()
        history = self.store.history("chat-1")
        self.assertEqual(history["summary"]["input_tokens"], 600)
        self.assertEqual(history["summary"]["cached_input_tokens"], 450)
        self.assertEqual(history["quality"]["source"], "snapshot")
        self.assertEqual(history["quality"]["status"], "degraded")
        append(self.log, [response(second=5)])
        self.collector.scan()
        self.assertEqual(self.store.history("chat-1")["summary"]["input_tokens"], 1000)
        self.assertEqual(self.store.history("chat-1")["summary"]["calls"], 1)

    def test_zero_missing_invalid_mismatch_and_no_prompt_storage(self):
        append(self.log, [meta(), response(usage=counts(0,0,0), total=counts(0,0,0)),
                          response("invalid", counts(10,20,0)),
                          event("response_item", {"secret_conversation": "DO-NOT-STORE-THIS"})])
        self.collector.scan()
        self.assertIsNone(self.store.history("chat-1")["summary"]["cache_reuse"])
        self.assertEqual(self.store.history("chat-1")["summary"]["calls"], 1)
        self.assertNotIn("DO-NOT-STORE-THIS", "\n".join(self.store.db.iterdump()))
        append(self.log, [response("mismatch", counts(10,5,1), counts(999,5,1), 2)])
        self.collector.scan()
        self.assertFalse(self.store.history("chat-1")["quality"]["reconciled"])

    def test_independent_sessions_and_foreign_thread_exclusion(self):
        append(self.log, [meta(), response(), response("foreign", sid="chat-2")])
        append(self.logs/"other.jsonl", [meta("chat-2"), response(sid="chat-2", turn=None)])
        self.collector.scan()
        self.assertEqual(len(self.store.sessions()), 2)
        self.assertEqual(self.store.history("chat-1")["summary"]["calls"], 1)
        self.assertIn('A response record belongs to a different chat and was excluded.', self.store.history('chat-1')['quality']['issues'])
        self.assertFalse(self.store.history("chat-2")["turns"][0]["attributed"])
        with self.assertRaises(ValueError): self.store.history("chat-1", 0)

    def test_file_replacement_identity_and_unsupported_schema(self):
        append(self.log, [meta(), response()]); self.collector.scan()
        replacement = self.logs/"replacement.tmp"
        append(replacement, [meta(), response("new", second=2), event("future_schema", {})])
        replacement.replace(self.log)
        self.collector.scan()
        self.assertEqual(self.store.history("chat-1")["summary"]["calls"], 2)
        self.assertTrue(self.store.history("chat-1")["quality"]["issues"])

    def test_internal_reviews_hidden_by_default_but_regular_subagents_remain(self):
        append(self.log, [meta(), response()])
        for sid, source, thread_source in [
            ('review-explicit', 'vscode', 'guardian_review'),
            ('review-guardian', {'subagent': {'other': 'guardian'}}, None),
            ('worker', {'subagent': {'thread_spawn': {'parent_thread_id': 'chat-1'}}}, None),
        ]:
            metadata = meta(sid)
            metadata['payload'].update(source=source, thread_source=thread_source)
            append(self.logs / f'{sid}.jsonl', [metadata, response(sid=sid)])
        self.collector.scan()
        self.assertEqual({s['id'] for s in self.store.sessions()}, {'chat-1', 'worker'})
        all_sessions = self.store.sessions(include_internal=True)
        self.assertEqual(len(all_sessions), 4)
        self.assertEqual({s['id'] for s in all_sessions if s['session_kind']=='internal_review'},
                         {'review-explicit', 'review-guardian'})
        self.assertEqual(self.store.history('worker')['session']['session_kind'], 'subagent')
        self.assertEqual(self.store.history('review-explicit')['session']['session_kind'], 'internal_review')

    def test_existing_session_classification_backfill_does_not_replay_usage(self):
        metadata=meta();metadata['payload']['source']={'subagent': {'other': 'guardian'}}
        append(self.log, [metadata, response(), snapshot(counts()), snapshot(counts(1500,1300,30),2)])
        self.collector.scan()
        before = dict(self.store.db.execute('SELECT * FROM files').fetchone())
        usage_before = self.store.db.execute('SELECT COUNT(*) FROM usage').fetchone()[0]
        # Simulate an existing indexed row from before classification was available.
        self.store.db.execute('UPDATE sessions SET session_kind=NULL');self.store.db.commit()
        self.collector.scan()
        after = dict(self.store.db.execute('SELECT * FROM files').fetchone())
        self.assertEqual(before, after)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM usage').fetchone()[0], usage_before)
        self.assertEqual(self.store.sessions(), [])
        self.assertEqual(self.store.sessions(include_internal=True)[0]['session_kind'], 'internal_review')

    def test_dashboard_selection_review_visibility_and_live_append(self):
        append(self.log, [meta(), response()])
        review=meta('review-1');review['payload']['thread_source']='guardian_review'
        append(self.logs/'review.jsonl', [review, response(sid='review-1')])
        monitor = Monitor(self.logs, self.base / "dashboard.sqlite3")
        monitor.collector.scan()
        try:
            self.assertIsNone(monitor.dashboard()["selected_session_id"])
            self.assertEqual(len(monitor.dashboard()['sessions']), 1)
            self.assertFalse(monitor.dashboard()['include_internal'])
            self.assertEqual(len(monitor.dashboard(include_internal=True)['sessions']), 2)
            review_detail = monitor.dashboard('review-1')
            self.assertTrue(review_detail['include_internal'])
            self.assertEqual(review_detail['detail']['session']['session_kind'], 'internal_review')
            self.assertEqual(monitor.dashboard('chat-1')["detail"]["summary"]["calls"], 1)
            append(self.log, [response("next", counts(500,400,2), counts(1500,1300,22), 2)])
            monitor.collector.scan()
            self.assertEqual(monitor.dashboard('chat-1')["detail"]["summary"]["calls"], 2)
        finally:
            monitor.close()

    def test_resumed_checkpoint_preserves_calls_outside_its_counter_lineage(self):
        append(self.log, [meta(), response()])
        checkpoint = self.log.stat().st_size
        append(self.log, [response('outside-checkpoint', counts(100,80,5), counts(1100,980,25), 2)])
        resumed = meta()
        resumed['payload']['history_base'] = {'thread_id': 'chat-1', 'end_byte_offset': checkpoint, 'end_ordinal_exclusive': 2}
        append(self.logs/'resumed.jsonl', [resumed,
            event('turn_context', {'model': 'another-model', 'turn_id': 'turn-2'}, 3),
            response('resumed-call', counts(200,100,10), counts(1200,1000,30), 3)])
        self.collector.scan();self.collector.scan()
        history = self.store.history('chat-1')
        self.assertEqual(history['summary']['calls'], 3)
        self.assertEqual(history['summary']['input_tokens'], 1300)
        self.assertEqual(history['summary']['cached_input_tokens'], 1080)
        self.assertEqual(history['latest']['model'], 'another-model')
        self.assertEqual(history['quality']['status'], 'verified')
        self.assertTrue(history['quality']['reconciled'])
        self.assertTrue(history['quality']['notes'])

    def test_repeated_edits_verify_segment_checkpoints_and_keep_spent_usage(self):
        append(self.log, [meta(), response()])
        first_checkpoint = self.log.stat().st_size
        append(self.log, [response('replaced-original', counts(100,80,5), counts(1100,980,25), 2)])
        resumed = meta()
        resumed['payload']['history_base'] = {'thread_id': 'chat-1', 'end_byte_offset': first_checkpoint,
                                             'end_ordinal_exclusive': 2}
        first_resume = self.logs/'resume-one.jsonl'
        append(first_resume, [resumed, response('first-edit', counts(200,100,10), counts(1200,1000,30), 3,
                                               turn='edited-turn-1')])
        second_checkpoint = first_resume.stat().st_size
        append(first_resume, [response('replaced-resumed', counts(50,40,2), counts(1250,1040,32), 4,
                                       turn='replaced-turn')])
        edited = meta()
        edited['payload']['history_base'] = {'thread_id': 'prior-rollout-segment-id',
                                            'end_byte_offset': second_checkpoint, 'end_ordinal_exclusive': 4}
        last_call = response('second-edit', counts(300,250,3), counts(1500,1250,33), 5, turn='edited-turn-2')
        append(self.logs/'resume-two.jsonl', [edited, last_call, last_call])
        self.collector.scan(); self.collector.scan()
        history = self.store.history('chat-1', 1)
        self.assertEqual(history['summary']['calls'], 5)
        self.assertEqual(history['summary']['input_tokens'], 1650)
        self.assertEqual(history['summary']['cached_input_tokens'], 1370)
        self.assertEqual(history['summary']['output_tokens'], 40)
        self.assertEqual(history['quality']['status'], 'verified')
        self.assertTrue(history['quality']['reconciled'])
        self.assertEqual(history['latest']['response_id'], 'second-edit')
        self.assertEqual(history['turns'][-1]['id'], 'edited-turn-2')
        self.assertEqual(history['turns'][-1]['summary']['input_tokens'], 300)
        self.assertEqual(history['usage_by_model'][0]['input_tokens'], 1650)

        # Recognizing segment references must not hide a genuine later mismatch.
        append(self.logs/'resume-two.jsonl', [response('bad-counter', counts(100,50,1),
                                                     counts(9999,1300,34), 6, turn='edited-turn-2')])
        self.collector.scan()
        self.assertFalse(self.store.history('chat-1')['quality']['reconciled'])

    def test_segment_checkpoint_requires_proof_from_the_same_chat(self):
        append(self.log, [meta(), response()])
        checkpoint = self.log.stat().st_size
        resumed = meta('chat-2')
        resumed['payload']['history_base'] = {'thread_id': 'unknown-rollout-segment-id',
                                             'end_byte_offset': checkpoint, 'end_ordinal_exclusive': 2}
        append(self.logs/'other.jsonl', [resumed, response('other-call', counts(200,100,10),
                                                          counts(1200,1000,30), sid='chat-2')])
        self.collector.scan()
        history = self.store.history('chat-2')
        self.assertEqual(history['summary']['input_tokens'], 200)
        self.assertEqual(history['quality']['status'], 'unreconciled')
        self.assertIsNone(history['quality']['reconciled'])
        self.assertEqual(self.store.history('chat-1')['summary']['calls'], 1)

    def test_inherited_parent_metadata_does_not_steal_subagent_usage(self):
        append(self.log, [meta(), response()])
        child = meta('worker')
        child['payload'].update(source={'subagent': {'thread_spawn': {'parent_thread_id': 'chat-1'}}},
                                forked_from_id='chat-1', subagent_history_start_ordinal=5)
        path = self.logs/'worker.jsonl'
        append(path, [child, meta(), event('turn_context', {'model': 'parent-model'}), response(), snapshot(counts()),
                      event('turn_context', {'model': 'worker-model', 'turn_id': 'worker-turn'}),
                      response('worker-response', counts(500,400,10), sid='worker'), snapshot(counts(500,400,10))])
        self.collector.scan()
        parent = self.store.history('chat-1');worker = self.store.history('worker')
        self.assertEqual(parent['summary']['calls'], 1)
        self.assertEqual(parent['quality']['status'], 'verified')
        self.assertEqual(worker['summary']['input_tokens'], 500)
        self.assertEqual(worker['session']['session_kind'], 'subagent')
        self.assertEqual(worker['latest']['model'], 'worker-model')
        self.assertEqual(worker['quality']['status'], 'verified')

        # An old collector had advanced past every event with the wrong owner.
        cursor = self.store.db.execute('SELECT state FROM files WHERE path=?',(str(path),)).fetchone()
        state = json.loads(cursor[0]);state.pop('collector_version');state['session_id']='chat-1'
        self.store.db.execute('UPDATE files SET state=? WHERE path=?',(json.dumps(state),str(path)))
        self.store.db.execute('UPDATE sessions SET issues=? WHERE id=?',
                             (json.dumps(['A response record belongs to a different chat and was excluded.']),'chat-1'))
        self.store.db.execute('DELETE FROM usage WHERE session_id=?',('worker',))
        self.store.db.commit()
        self.collector.scan()
        self.assertEqual(self.store.history('worker')['summary']['calls'], 1)
        self.assertEqual(self.store.history('chat-1')['quality']['status'], 'verified')
        self.assertEqual(json.loads(self.store.db.execute('SELECT state FROM files WHERE path=?',(str(path),)).fetchone()[0])['session_id'], 'worker')

    def test_unavailable_resume_checkpoint_never_invents_unrecorded_tokens(self):
        resumed = meta()
        resumed['payload']['history_base'] = {'thread_id': 'chat-1', 'end_byte_offset': 99999, 'end_ordinal_exclusive': 100}
        append(self.log, [resumed, response(usage=counts(200,100,10), total=counts(1200,1000,30))])
        self.collector.scan()
        history = self.store.history('chat-1')
        self.assertEqual(history['summary']['input_tokens'], 200)
        self.assertIsNone(history['quality']['reconciled'])
        self.assertEqual(history['quality']['status'], 'unreconciled')

    def test_concurrent_collectors_preserve_usage_and_cursors(self):
        append(self.log, [meta()] + [response(f'call-{i}', counts(100,80,1), counts(i*100,i*80,i), i)
                                    for i in range(1,31)])
        other = Store(self.database)
        collectors = [self.collector, Collector(self.logs, other)]
        start = threading.Barrier(2)
        def scan(collector):
            start.wait()
            collector.scan()
        workers = [threading.Thread(target=scan,args=(collector,)) for collector in collectors]
        try:
            for worker in workers:worker.start()
            for worker in workers:worker.join(10)
            self.assertTrue(all(not worker.is_alive() for worker in workers))
            self.assertTrue(all(collector.last_error is None for collector in collectors))
            self.assertEqual(self.store.history('chat-1')['summary']['calls'], 30)
            self.assertEqual(self.store.history('chat-1')['quality']['status'], 'verified')
        finally:
            other.close()

    def test_whole_chat_model_totals_ignore_chart_history_limit(self):
        append(self.log, [meta(), event('turn_context', {'model':'gpt-6.1-sol','turn_id':'turn-1'}), response(),
                          event('turn_context', {'model':'gpt-6.1-terra','turn_id':'turn-2'},2),
                          response('second-model',counts(200,100,10),counts(1200,1000,30),2),
                          event('turn_context', {'model':None,'turn_id':'turn-3'},3),
                          response('unknown-model',counts(50,0,2),counts(1250,1000,32),3)])
        self.collector.scan()
        detail=self.store.history('chat-1',1)
        self.assertEqual(len(detail['history']),1)
        self.assertTrue(detail['history_truncated'])
        groups={row['model']:row for row in detail['usage_by_model']}
        self.assertEqual(set(groups),{'gpt-6.1-sol','gpt-6.1-terra',None})
        self.assertEqual(groups['gpt-6.1-sol']['input_tokens'],1000)
        self.assertEqual(groups['gpt-6.1-terra']['cached_input_tokens'],100)
        for key in ['calls','input_tokens','cached_input_tokens','output_tokens']:
            self.assertEqual(sum(row[key] for row in groups.values()),detail['summary'][key])


class MCPTest(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_tools_ui_resource_and_app_refresh(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);logs=base/'logs';logs.mkdir();log=logs/'rollout.jsonl'
            append(log,[meta(),response()])
            review=meta('review-1');review['payload']['thread_source']='guardian_review'
            append(logs/'review.jsonl',[review,response(sid='review-1')])
            append(logs/'other.jsonl',[meta('other-chat'),response(sid='other-chat')])
            params=StdioServerParameters(command=sys.executable,args=['-m','cache_monitor','mcp','--logs',str(logs),'--database',str(base/'usage.sqlite3')],cwd=str(Path(__file__).parents[1]))
            async with stdio_client(params) as (read,write):
                async with ClientSession(read,write,read_timeout_seconds=timedelta(seconds=10)) as client:
                    initialized=await client.initialize()
                    self.assertEqual(initialized.serverInfo.name, 'gauge')
                    self.assertIn('io.modelcontextprotocol/ui',initialized.capabilities.model_extra['extensions'])
                    listed=await client.list_tools()
                    tool=next(t for t in listed.tools if t.name=='show_cache_dashboard')
                    self.assertEqual(tool.title, 'Open Gauge')
                    self.assertEqual(tool.inputSchema['required'], ['session_id'])
                    for name in ['show_cache_dashboard', 'refresh_cache_dashboard']:
                        self.assertTrue((await client.call_tool(name, {})).isError)
                    uri=tool.meta['ui']['resourceUri']
                    self.assertEqual(tool.meta['openai/outputTemplate'], uri)
                    self.assertEqual(tool.meta['openai/ui']['preferredModelDisplayMode'], 'fullscreen')
                    resource=await client.read_resource(uri)
                    self.assertEqual(resource.contents[0].mimeType,'text/html;profile=mcp-app')
                    self.assertIn('<title>Gauge</title>',resource.contents[0].text)
                    self.assertIn('<h1>Gauge</h1>',resource.contents[0].text)
                    self.assertNotIn('<script src=',resource.contents[0].text)
                    self.assertEqual(resource.contents[0].meta['ui']['csp']['connectDomains'], [])
                    self.assertEqual(resource.contents[0].meta['openai/ui']['availableDisplayModes'], ['fullscreen'])
                    for removed in ['refresh','float','expand','return-inline']:
                        self.assertNotIn(f'id="{removed}"',resource.contents[0].text)
                    self.assertIn('id="auto"',resource.contents[0].text)
                    self.assertNotIn('/api/dashboard',resource.contents[0].text)
                    self.assertNotIn('8765',resource.contents[0].text)
                    for _ in range(20):
                        result=await client.call_tool('show_cache_dashboard',{'session_id':'chat-1'})
                        if result.meta['dashboard']['detail']: break
                        await asyncio.sleep(.1)
                    self.assertFalse(result.isError)
                    self.assertEqual(result.meta['dashboard']['detail']['summary']['calls'],1)
                    self.assertEqual(result.meta['dashboard']['detail']['usage_by_model'][0]['input_tokens'],1000)
                    self.assertEqual([s['id'] for s in result.meta['dashboard']['sessions']], ['chat-1'])
                    waiting=await client.call_tool('show_cache_dashboard',{'session_id':'not-yet-indexed'})
                    self.assertEqual(waiting.meta['dashboard']['selected_session_id'], 'not-yet-indexed')
                    self.assertEqual(waiting.meta['dashboard']['sessions'], [])
                    self.assertIsNone(waiting.meta['dashboard']['detail'])
                    self.assertNotIn('history', json.dumps(result.structuredContent))
                    self.assertIn('90.00%',result.content[0].text)
                    listed_default=await client.call_tool('list_cache_sessions',{})
                    self.assertEqual({s['id'] for s in listed_default.structuredContent['sessions']},{'chat-1','other-chat'})
                    listed_all=await client.call_tool('list_cache_sessions',{'include_internal':True})
                    self.assertEqual(len(listed_all.structuredContent['sessions']),3)
                    review_result=await client.call_tool('show_cache_dashboard',{'session_id':'review-1'})
                    self.assertIn('Internal review',review_result.content[0].text)
                    self.assertTrue(review_result.meta['dashboard']['include_internal'])
                    self.assertEqual([s['id'] for s in review_result.meta['dashboard']['sessions']], ['review-1'])
                    append(log,[response('next',counts(100,0,1),counts(1100,900,21),2)])
                    for _ in range(30):
                        result=await client.call_tool('refresh_cache_dashboard',{'session_id':'chat-1'})
                        if result.structuredContent['detail']['summary']['calls']==2: break
                        await asyncio.sleep(.1)
                    self.assertEqual(result.structuredContent['detail']['summary']['calls'],2)
                    self.assertEqual(sum(row['input_tokens'] for row in result.structuredContent['detail']['usage_by_model']),1100)
                    self.assertEqual([s['id'] for s in result.structuredContent['sessions']], ['chat-1'])
                    self.assertTrue(result.structuredContent['detail']['quality']['reconciled'])
                    missing=await client.call_tool('get_cache_summary',{'session_id':'missing'})
                    self.assertTrue(missing.isError)
                    invalid=await client.call_tool('get_cache_history',{'session_id':'chat-1','limit':0})
                    self.assertTrue(invalid.isError)


if __name__ == '__main__':
    unittest.main()
