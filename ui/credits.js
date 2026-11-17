export const PRICING_SOURCE = 'https://learn.chatgpt.com/docs/pricing#token-rates';
export const PRICING_CHECKED = '2026-11-16';
// Published Standard-speed credits per million tokens, checked at PRICING_SOURCE.
export const CREDIT_RATES = Object.freeze({
  'gpt-6-astra': {input: 250, cached: 25, output: 1250},
  'gpt-6.1-sol': {input: 50, cached: 2.5, output: 250},
  'gpt-6.1-terra': {input: 25, cached: 1.25, output: 125},
  'gpt-6-sol': {input: 50, cached: 5, output: 250},
  'gpt-6-luna': {input: 2.5, cached: .25, output: 12.5},
  'gpt-5.6-sol': {input: 100, cached: 10, output: 500},
  'gpt-5.6-terra': {input: 50, cached: 5, output: 300},
  'gpt-5.6-luna': {input: 5, cached: .5, output: 30},
});

// Claude Code: Anthropic API list prices in USD per million tokens. Claude Code
// subscriptions are not billed per token, so this is an API-equivalent cost.
// Cache writes cost 1.25x input (5-minute TTL) or 2x input (1-hour TTL).
export const CLAUDE_PRICING_SOURCE = 'https://platform.claude.com/docs/en/about-claude/pricing';
export const CLAUDE_PRICING_CHECKED = '2026-11-16';
const claude = (input, cached, output) => ({input, cached, output, write5m: input * 1.25, write1h: input * 2});
export const CLAUDE_RATES = Object.freeze({
  'claude-fable-5-2': claude(8, .2, 40), 'claude-mythos-5-2': claude(8, .2, 40),
  'claude-fable-5-1': claude(10, .25, 50), 'claude-mythos-5-1': claude(10, .25, 50),
  'claude-fable-5': claude(10, 1, 50), 'claude-mythos-5': claude(10, 1, 50),
  'claude-opus-5-5': claude(4, .2, 20),
  'claude-opus-5': claude(5, .5, 25),
  'claude-opus-4-8': claude(5, .5, 25), 'claude-opus-4-7': claude(5, .5, 25), 'claude-opus-4-6': claude(5, .5, 25),
  'claude-sonnet-5-5': claude(2, .1, 10),
  'claude-sonnet-5': claude(2, .2, 10),
  'claude-sonnet-4-6': claude(3, .3, 15),
  // Prompts above 100K tokens cost 5x on Haiku 5.5; that surcharge is excluded.
  'claude-haiku-5-5': claude(.1, .01, .5),
  'claude-haiku-4-5': claude(1, .1, 5),
});

// Pricing presentation for each host. Sessions without a provider are Codex.
export const PRICING = Object.freeze({
  codex: {rates: CREDIT_RATES, source: PRICING_SOURCE, checked: PRICING_CHECKED, unit: 'credits', title: 'Estimated credits'},
  claude: {rates: CLAUDE_RATES, source: CLAUDE_PRICING_SOURCE, checked: CLAUDE_PRICING_CHECKED, unit: 'USD', title: 'Estimated API cost'},
});

export function pricingFor(provider) {
  return provider === 'claude' ? PRICING.claude : PRICING.codex;
}

export function rateFor(model, rates = CREDIT_RATES) {
  if (typeof model !== 'string') return null;
  if (Object.hasOwn(rates, model)) return rates[model];
  // Dated snapshots (claude-haiku-4-5-20251001) share their alias's price.
  const alias = model.replace(/-\d{8}$/, '');
  return Object.hasOwn(rates, alias) ? rates[alias] : null;
}

const WRITE_FIELDS = ['cache_write_5m_tokens', 'cache_write_1h_tokens'];
const writes = group => WRITE_FIELDS.reduce((sum, key) => sum + (group[key] ?? 0), 0);

export function groupModelUsage(rows) {
  const groups = new Map();
  for (const row of rows) {
    const model = row.model || null;
    if (!groups.has(model)) groups.set(model, {model, calls: 0, input_tokens: 0, cached_input_tokens: 0, output_tokens: 0});
    const group = groups.get(model);
    group.calls++;
    for (const field of ['input_tokens', 'cached_input_tokens', 'output_tokens']) group[field] += row[field];
    for (const field of WRITE_FIELDS) group[field] = (group[field] ?? 0) + (row[field] ?? 0);
  }
  return [...groups.values()];
}

export function wholeChatModelUsage(detail) {
  const groups = Array.isArray(detail.usage_by_model) ? detail.usage_by_model
    : !detail.history_truncated && detail.history?.length === detail.summary.calls ? groupModelUsage(detail.history) : null;
  if (!groups) return null;
  for (const field of ['calls', 'input_tokens', 'cached_input_tokens', 'output_tokens']) {
    if (groups.reduce((sum, group) => sum + group[field], 0) !== detail.summary[field]) return null;
  }
  return groups;
}

export function estimateCredits(groups, rates = CREDIT_RATES) {
  let input = 0, cached = 0, write = 0, output = 0, pricedCalls = 0, unpricedCalls = 0;
  const unpricedModels = new Set();
  for (const group of groups) {
    const rate = rateFor(group.model, rates);
    const valid = ['input_tokens', 'cached_input_tokens', 'output_tokens', 'calls'].every(key => Number.isSafeInteger(group[key]) && group[key] >= 0)
      && WRITE_FIELDS.every(key => group[key] === undefined || (Number.isSafeInteger(group[key]) && group[key] >= 0))
      && group.cached_input_tokens + writes(group) <= group.input_tokens
      && (writes(group) === 0 || (rate?.write5m !== undefined && rate?.write1h !== undefined));
    if (!rate || !valid) {
      unpricedCalls += Number.isSafeInteger(group.calls) && group.calls >= 0 ? group.calls : 1;
      unpricedModels.add(group.model || 'Model unavailable');
      continue;
    }
    // Cached input and cache writes are part of input_tokens: bill the remainder at the fresh rate.
    input += (group.input_tokens - group.cached_input_tokens - writes(group)) * rate.input / 1_000_000;
    cached += group.cached_input_tokens * rate.cached / 1_000_000;
    write += ((group.cache_write_5m_tokens ?? 0) * (rate.write5m ?? 0) + (group.cache_write_1h_tokens ?? 0) * (rate.write1h ?? 0)) / 1_000_000;
    output += group.output_tokens * rate.output / 1_000_000;
    pricedCalls += group.calls;
  }
  return {input, cached, write, output, total: input + cached + write + output, pricedCalls, unpricedCalls,
    unpricedModels: [...unpricedModels], complete: unpricedModels.size === 0};
}
