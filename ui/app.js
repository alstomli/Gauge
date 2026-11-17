import { App } from '@modelcontextprotocol/ext-apps';
import { createSidePanel } from './presentation.js';
import { formatReuse } from './format.js';
import { reuseScale, axisPercent } from './chart.js';
import { pricingFor, rateFor, estimateCredits, wholeChatModelUsage } from './credits.js';
import { createCreditCounter } from './credit-counter.js';
import { isHostCallUnavailable, SNAPSHOT_MESSAGE } from './host-calls.js';

const $ = id => document.getElementById(id);
const number = n => new Intl.NumberFormat().format(n);
const percent = formatReuse;
const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const projectName = path => path ? path.split(/[\\/]/).filter(Boolean).pop() || path : 'Unknown project';
const isInternal = session => session?.session_kind === 'internal_review';
let app, snapshot, selected = '';
let limit = 500, auto = true, busy = false, generation = 0, lastSuccess;
let followAllCalls = false;
// Snapshot only: the host renders the dashboard but cannot proxy its tool calls.
let snapshotOnly = false;
let sidePanel;
const creditNumber = new Intl.NumberFormat(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
const motionPreference = window.matchMedia('(prefers-reduced-motion: reduce)');
let pricing = pricingFor('codex');
const creditCounter = createCreditCounter({
  total: $('credits-total'), input: $('credits-input'), cached: $('credits-cached'), write: $('credits-write'), output: $('credits-output'),
}, {format: value => creditNumber.format(value), reduceMotion: () => motionPreference.matches || document.hidden, unit: () => pricing.unit});
let creditCache, creditLoadingKey = '', creditError;

function showError(message) { $('error').textContent = message; $('error').hidden = !message; }
function announce(message) { $('announcement').textContent = message; }
function enterSnapshotMode() {
  if (snapshotOnly) return;
  snapshotOnly = true; auto = false;
  clearInterval(refreshTimer);
  $('auto').textContent = 'Auto refresh unavailable';
  $('auto').setAttribute('aria-pressed', 'false');
  $('auto').disabled = true;
  $('host-note').textContent = SNAPSHOT_MESSAGE;
  $('host-note').hidden = false;
  showError('');
  render();
  announce('Automatic refresh is unavailable in this app.');
}
function base(summary) { return `${number(summary.cached_input_tokens)} cached / ${number(summary.input_tokens)} input tokens`; }
function bindChat(id) {
  if (typeof id !== 'string' || !id.trim()) throw new Error('Open the monitor with the current chat ID.');
  if (selected && selected !== id) throw new Error('This dashboard is fixed to the chat that opened it.');
  selected = id;
}
function decode(result) {
  if (result.isError) throw new Error(result.content?.find(c => c.type === 'text')?.text || 'MCP tool failed');
  const value = result._meta?.dashboard || result.structuredContent;
  if (!value || !value.collector || !('detail' in value)) throw new Error('Gauge returned an unsupported result.');
  if (value.detail && value.detail.session.id !== value.selected_session_id) throw new Error('Gauge returned data for a different chat.');
  bindChat(value.selected_session_id);
  return value;
}
async function refresh(manual = false) {
  if (busy || !selected || snapshotOnly) return;
  busy = true;
  const requestGeneration = generation, requestSession = selected;
  try {
    // Keep a bounded history locally so dragging the chart window is immediate.
    const args = {limit: 2000, session_id: selected};
    const result = decode(await app.callServerTool({name:'refresh_cache_dashboard', arguments:args}));
    if (requestGeneration !== generation || requestSession !== selected) return;
    snapshot = result; lastSuccess = new Date(); showError(''); render();
    if (manual) announce('Cache usage updated.');
  } catch(error) {
    if (isHostCallUnavailable(error)) { enterSnapshotMode(); return; }
    showError(`Refresh failed. Previous readings are retained. ${error.message}`);
    $('connection').textContent = 'Disconnected';
  } finally { busy = false; }
}

function render() {
  if (!snapshot) return;
  const {detail, collector} = snapshot;
  $('connection').textContent = collector.error ? 'Collector needs attention' : `MCP App · ${snapshotOnly ? 'snapshot' : auto ? 'auto refresh' : 'paused'}`;
  $('detail').hidden = !detail;
  $('empty').hidden = Boolean(detail);
  if (detail) renderDetail(detail);
  $('freshness').textContent = collector.error || (detail?.last_record_at ? `Last usage ${new Date(detail.last_record_at).toLocaleString()} · refreshed ${lastSuccess?.toLocaleTimeString() || 'now'}` : collector.last_scan_at ? `Last scan ${new Date(collector.last_scan_at).toLocaleTimeString()}` : 'Initial scan in progress…');
}

function renderDetail(detail) {
  const latest = detail.latest, turn = detail.turns[detail.turns.length - 1];
  $('chat-title').textContent = `${isInternal(detail.session) ? 'Internal review · ' : ''}${projectName(detail.session.project)}`;
  $('model-label').textContent = latest?.model || 'Model unavailable';
  $('quality-label').textContent = `${detail.quality.source} · ${detail.quality.status}`;
  $('quality-label').dataset.quality = detail.quality.status;
  $('latest').textContent = percent(latest && latest.input_tokens ? latest.cached_input_tokens / latest.input_tokens : null);
  $('latest-base').textContent = latest ? base(latest) : 'Waiting for a completed call';
  $('weighted').textContent = percent(detail.summary.cache_reuse); $('weighted-base').textContent = base(detail.summary);
  $('weighted-count').textContent = `${number(detail.summary.calls)} completed calls`;
  $('latest-uncached').textContent = latest ? `${number(latest.input_tokens-latest.cached_input_tokens)} uncached input tokens` : 'Updates after a completed call';
  $('turn-rate').textContent = percent(turn?.summary.cache_reuse); $('turn-base').textContent = turn ? `${number(turn.summary.calls)} calls · ${turn.attributed ? 'explicit turn ID' : 'prompt attribution unavailable'}` : 'No prompt usage available';
  renderCredits(detail);
  renderHistory(detail);
  const counterStatus = detail.quality.reconciled === true ? (detail.quality.counter_scope === 'log/checkpoint' ? 'matched per log/checkpoint' : 'matched') : detail.quality.reconciled === false ? 'mismatch' : 'not yet reconciled';
  $('quality-detail').innerHTML = `<p>Source: ${escape(detail.quality.source)}. Session counters: ${counterStatus}.</p><ul>${detail.quality.issues.map(issue => `<li>${escape(issue)}</li>`).join('')}</ul>${(detail.quality.notes || []).map(note => `<p>${escape(note)}</p>`).join('')}`;
}

function renderHistory(detail) {
  const available = detail.history.length;
  // An all-calls view follows incoming calls; a smaller window keeps its size.
  if (followAllCalls) limit = Math.max(1, available);
  const rows = detail.history.slice(-limit);
  const all = rows.length === detail.summary.calls;
  followAllCalls = all;
  $('limit').max = String(Math.max(1, available));
  $('limit').value = String(Math.min(limit, Math.max(1, available)));
  $('limit').disabled = available < 2;
  $('limit').setAttribute('aria-valuetext', `${number(rows.length)} most recent completed calls`);
  const fraction = available > 1 ? (rows.length - 1) / (available - 1) : 1;
  $('history-rail').style.setProperty('--window-start', `${(1 - fraction) * 100}%`);
  $('history-rail').dataset.disabled = String(available < 2);
  $('history-window').textContent = `${all ? 'All' : 'Last'} ${number(rows.length)} ${rows.length === 1 ? 'call' : 'calls'}`;
  $('history-label').textContent = `${number(rows.length)} of ${number(detail.summary.calls)} calls`;
  drawChart(rows);
}

function creditUsageKey(detail) {
  return JSON.stringify([detail.session.id, detail.summary.calls, detail.summary.input_tokens,
    detail.summary.cached_input_tokens, detail.summary.output_tokens]);
}

function applyPricing(provider) {
  const next = pricingFor(provider);
  if (next === pricing) return;
  pricing = next;
  $('credits-title').textContent = pricing.title;
  $('credits-unit').textContent = pricing.unit;
  $('credits-checked').textContent = `Rates checked ${pricing.checked}`;
}

function renderCredits(detail) {
  const summary = detail.summary, key = creditUsageKey(detail);
  applyPricing(detail.session.provider);
  const written = (summary.cache_write_5m_tokens ?? 0) + (summary.cache_write_1h_tokens ?? 0);
  $('credits-write-part').hidden = detail.session.provider !== 'claude';
  $('credits-write-tokens').textContent = `${number(written)} tokens`;
  if (creditError?.key === key && Date.now() >= creditError.retryAt) creditError = null;
  const groups = wholeChatModelUsage(detail) || (creditCache?.key === key ? creditCache.groups : null);
  $('credits-input-tokens').textContent = `${number(summary.input_tokens - summary.cached_input_tokens - written)} tokens`;
  $('credits-cached-tokens').textContent = `${number(summary.cached_input_tokens)} tokens`;
  $('credits-output-tokens').textContent = `${number(summary.output_tokens)} tokens`;
  if (!groups) {
    creditCounter.clear({preserveValue: true});
    $('credit-panel').dataset.partial = 'true';
    $('credits-coverage').textContent = creditError?.key === key ? creditError.message : 'Calculating the whole-chat estimate…';
    $('credits-rates').textContent = '';
    if (creditLoadingKey !== key && creditError?.key !== key) void loadWholeChatCreditUsage(detail);
    return;
  }
  const estimate = estimateCredits(groups, pricing.rates);
  creditCounter.update({total: estimate.total, input: estimate.input, cached: estimate.cached, write: estimate.write, output: estimate.output},
    {partial: !estimate.complete, available: estimate.pricedCalls > 0 || estimate.complete});
  $('credit-panel').dataset.partial = String(!estimate.complete);
  $('credits-coverage').textContent = estimate.complete
    ? `${number(summary.calls)} completed calls · Standard-rate estimate`
    : `Partial estimate · ${number(estimate.pricedCalls)} of ${number(summary.calls)} calls priced. Unpriced: ${estimate.unpricedModels.join(', ')}.`;
  $('credits-rates').textContent = groups.map(group => {
    const rate = rateFor(group.model, pricing.rates);
    const writes = rate?.write5m !== undefined ? ` / cache write ${rate.write5m} (5m), ${rate.write1h} (1h)` : '';
    return rate ? `${group.model}: fresh ${rate.input} / cached ${rate.cached}${writes} / output ${rate.output} ${pricing.unit} per 1M tokens`
      : `${group.model || 'Model unavailable'}: no published rate in this estimate`;
  }).join('\n');
}

async function loadWholeChatCreditUsage(detail) {
  // Compatibility with a running older server: request complete history once per
  // usage change, never price just the chart's recent-history slice.
  const key = creditUsageKey(detail);
  creditLoadingKey = key;
  try {
    const result = await app.callServerTool({name: 'get_cache_history', arguments: {session_id: selected, limit: 2000}});
    if (result.isError) throw new Error('Whole-chat pricing is unavailable. Automatic refresh will retry.');
    const full = result.structuredContent;
    if (full?.session?.id !== selected) throw new Error('Whole-chat pricing returned a different chat.');
    let groups = wholeChatModelUsage(full);
    if (!groups) throw Object.assign(new Error('Reload the MCP connection to price the complete history of this chat.'), {permanent: true});
    let resultKey = creditUsageKey(full);
    // A completed call may arrive between the two requests. Keep the estimate
    // aligned with the displayed snapshot, even when automatic refresh is paused.
    if (resultKey !== key && !full.history_truncated) {
      const aligned = wholeChatModelUsage({summary: detail.summary, history_truncated: false,
        history: full.history.filter(row => row.timestamp <= detail.last_record_at)});
      if (aligned) {groups = aligned; resultKey = key;}
    }
    creditCache = {key: resultKey, groups};
    creditError = null;
    if (snapshot?.detail && creditUsageKey(snapshot.detail) === creditCache.key) renderCredits(snapshot.detail);
  } catch (error) {
    if (isHostCallUnavailable(error)) {
      enterSnapshotMode();
      error = Object.assign(new Error('Whole-chat pricing needs host tool calls, which this app does not support.'), {permanent: true});
    }
    creditError = {key, message: error.message, retryAt: error.permanent ? Infinity : Date.now() + 10_000};
    if (snapshot?.detail && creditUsageKey(snapshot.detail) === key) renderCredits(snapshot.detail);
  } finally {if (creditLoadingKey === key) creditLoadingKey = '';}
}

function drawChart(rows) {
  if (!rows.length) { $('chart').textContent = 'No completed model calls recorded.';$('chart-scale').textContent='Percentage axis';delete $('chart').dataset.signature;return; }
  const width = Math.max(220, $('chart').clientWidth || 600), height=230, left=58, right=20, top=20, bottom=42;
  const signature=JSON.stringify([snapshot.detail.session.id,width, rows.map(r=>[r.response_id,r.timestamp,r.input_tokens,r.cached_input_tokens]),snapshot.detail.summary.calls]);
  if($('chart').dataset.signature===signature)return;
  $('chart').dataset.signature=signature;
  const min = Date.parse(rows[0].timestamp), max = Date.parse(rows[rows.length-1].timestamp);
  const x = r => left + (Date.parse(r.timestamp)-min) / Math.max(1,max-min) * (width-left-right);
  const valid = rows.filter(r => r.input_tokens > 0);
  const scale = reuseScale(valid.map(r => r.cached_input_tokens/r.input_tokens));
  const y = r => top+(scale.max-r)/(scale.max-scale.min)*(height-top-bottom);
  const range = `${axisPercent(scale.min)}–${axisPercent(scale.max)}`;
  $('chart-scale').textContent = `Auto scale · ${range}`;
  let path = '', gap = true;
  rows.forEach(r => {if (!r.input_tokens) {gap=true; return;} path += `${gap ? 'M':'L'}${x(r).toFixed(2)},${y(r.cached_input_tokens/r.input_tokens).toFixed(2)} `;gap=false;});
  const ticks=scale.ticks.map(v => `<line class="grid" x1="${left}" x2="${width-right}" y1="${y(v)}" y2="${y(v)}"/><text x="${left-7}" y="${y(v)+4}" text-anchor="end">${axisPercent(v)}</text>`).join('');
  const labelTime = timestamp => new Date(timestamp).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});
  const pointMarks = valid.length <= 100 ? valid.map(r => `<circle class="point" cx="${x(r)}" cy="${y(r.cached_input_tokens/r.input_tokens)}" r="3"><title>${escape(base(r))} · ${percent(r.cached_input_tokens/r.input_tokens)}</title></circle>`).join('') : '';
  $('chart').innerHTML = `<svg class="history-chart" xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" role="img" aria-label="Cache reuse for ${rows.length} completed calls over time. Percentage axis automatically scaled to ${range}.">${ticks}<path class="line" d="${path}"/>${pointMarks}<text x="${left}" y="${height-bottom+19}">${escape(labelTime(rows[0].timestamp))}</text>${max>min ? `<text x="${width-right}" y="${height-bottom+19}" text-anchor="end">${escape(labelTime(rows[rows.length-1].timestamp))}</text>`:''}<text x="${width/2}" y="${height-2}" text-anchor="middle">Recorded time</text></svg>`;
}

$('limit').addEventListener('input', event => {
  followAllCalls = false;
  limit = Number(event.target.value);
  if (snapshot?.detail) renderHistory(snapshot.detail);
});
$('credits-checked').textContent = `Rates checked ${pricing.checked}`;
$('credits-source').addEventListener('click', async () => {
  try {
    const result = await app.openLink({url: pricing.source});
    if (result?.isError) throw new Error('The host could not open the pricing page.');
  } catch(error) {showError(error.message);}
});
const metricInfos = [...document.querySelectorAll('.metric-info')];
for (const info of metricInfos) {
  info.addEventListener('toggle', () => {
    if (info.open) metricInfos.forEach(other => {if (other !== info) other.open = false;});
  });
}
document.addEventListener('click', event => {
  metricInfos.forEach(info => {if (!info.contains(event.target)) info.open = false;});
});
document.addEventListener('keydown', event => {
  if (event.key === 'Escape') metricInfos.forEach(info => {info.open = false;});
});
document.addEventListener('visibilitychange', () => {if (document.hidden) creditCounter.finish();});
$('auto').addEventListener('click',()=>{auto=!auto;$('auto').textContent=`Auto refresh ${auto?'on':'off'}`;$('auto').setAttribute('aria-pressed',String(auto));render();if(auto)refresh();});
let resizeTimer;
const resizeObserver = new ResizeObserver(()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(()=>{if(snapshot?.detail)renderHistory(snapshot.detail);},100);});
resizeObserver.observe($('chart'));
let refreshTimer;
let darkAppearance = true;
function applyAppearance() {
  document.documentElement.dataset.appearance=darkAppearance?'dark':'light';
  $('appearance').textContent=darkAppearance?'Light theme':'Dark theme';
  $('appearance').setAttribute('aria-label',`Switch to ${darkAppearance?'light':'dark'} theme`);
}
$('appearance').addEventListener('click',()=>{darkAppearance=!darkAppearance;applyAppearance();});
applyAppearance();

async function start() {
    app = new App({name:'Gauge',version:'0.1.2'}, {availableDisplayModes:['fullscreen']}, {autoResize:true});
    sidePanel = createSidePanel(app, state => {
      $('display-note').textContent = state.message;
      $('display-note').hidden = !state.message;
    });
    app.ontoolinput = ({arguments:args}) => {
      try {
        bindChat(args?.session_id);
        if(Number.isInteger(args?.limit) && args.limit>=1 && args.limit<=2000) {limit=args.limit;followAllCalls=false;}
        $('limit').value=String(limit);generation++;
      } catch(error) {showError(error.message);}
    };
    app.ontoolresult = result => {
      try { const data=decode(result);generation++;snapshot=data;lastSuccess=new Date();showError('');render(); }
      catch(error){showError(error.message);}
    };
    app.onhostcontextchanged = context => {
      void sidePanel.update(context);
    };
    app.onteardown = async () => {
      clearInterval(refreshTimer);clearTimeout(resizeTimer);resizeObserver.disconnect();
      creditCounter.destroy();
      return {};
    };
    await app.connect();
    const context=app.getHostContext() || {};
    void sidePanel.update(context);
  await refresh();
  refreshTimer=setInterval(()=>{if(auto && document.visibilityState!=='hidden')refresh();},2000);
}
start().catch(error=>{showError(`Unable to connect: ${error.message}`);$('connection').textContent='Disconnected';});
