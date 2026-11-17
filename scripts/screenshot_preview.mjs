// Render the real UI with synthetic MCP responses; never read local chat logs.
// Build previews with `node scripts/screenshot_preview.mjs`, then capture the
// generated dark.html / light.html in a browser at 1200 x 1300.
import { build } from 'esbuild';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';

const output = resolve(process.argv[2] || '.release-test/screenshot-preview');
const ratios = [.48, .67, .78, .85, .89, .92, .94, .95, .91, .94, .96, .97,
  .95, .97, .98, .96, .98, .97, .98, .99, .97, .98, .99, .98];
const history = ratios.map((ratio, index) => ({
  response_id: `sample-call-${index + 1}`, model: 'gpt-6.1-sol',
  timestamp: new Date(Date.UTC(2026, 10, 16, 17, index * 2)).toISOString(),
  input_tokens: 20_000 + index * 1000,
  cached_input_tokens: Math.round((20_000 + index * 1000) * ratio),
  output_tokens: 180 + index * 10,
}));
const summarize = rows => {
  const summary = {calls: rows.length, input_tokens: 0, cached_input_tokens: 0, output_tokens: 0};
  for (const row of rows) for (const key of ['input_tokens', 'cached_input_tokens', 'output_tokens']) summary[key] += row[key];
  summary.cache_reuse = summary.cached_input_tokens / summary.input_tokens;
  return summary;
};
const summary = summarize(history);
const detail = {
  session: {id: 'screenshot-example', project: 'Example workspace'}, summary,
  latest: history.at(-1), history, history_truncated: false,
  turns: [{attributed: true, summary: summarize(history.slice(-4))}],
  usage_by_model: [{...summary, model: 'gpt-6.1-sol'}],
  quality: {source: 'token_usage_record', status: 'verified', reconciled: true,
    issues: [], notes: ['Synthetic sample data for documentation.']},
  last_record_at: history.at(-1).timestamp,
};
const snapshot = {selected_session_id: detail.session.id, detail,
  collector: {error: null, last_scan_at: detail.last_record_at}, sessions: [detail.session]};
const template = await readFile('ui/index.html', 'utf8');
const css = await readFile('ui/style.css', 'utf8');
await mkdir(output, {recursive: true});
for (const theme of ['dark', 'light']) {
  const mock = `const nativeMatchMedia = window.matchMedia.bind(window);
    window.matchMedia = query => {
      const media = nativeMatchMedia(query);
      if (query === '(prefers-reduced-motion: reduce)') Object.defineProperty(media, 'matches', {value: true});
      return media;
    };
    const snapshot = ${JSON.stringify(snapshot)};
    const result = {structuredContent: snapshot};
    export class App {
      async connect() {
        this.ontoolinput?.({arguments: {session_id: snapshot.selected_session_id}});
        this.ontoolresult?.(result);
        ${theme === 'light' ? "document.getElementById('appearance').click();" : ''}
      }
      getHostContext() { return {displayMode: 'fullscreen'}; }
      async callServerTool() { return result; }
    }`;
  const bundle = await build({entryPoints: ['ui/app.js'], bundle: true, write: false,
    format: 'iife', platform: 'browser', target: ['es2022'], minify: true,
    plugins: [{name: 'sample-mcp-host', setup(build) {
      build.onResolve({filter: /^@modelcontextprotocol\/ext-apps$/}, () => ({path: 'host', namespace: 'sample'}));
      build.onLoad({filter: /.*/, namespace: 'sample'}, () => ({contents: mock, loader: 'js'}));
    }}]});
  const js = bundle.outputFiles[0].text.replace(/<\/script/gi, '<\\/script');
  await writeFile(resolve(output, `${theme}.html`), template
    .replace('/* MONITOR_CSS */', () => css).replace('/* MONITOR_JS */', () => js));
}
console.log(`Built dark/light sample previews in ${output}`);
