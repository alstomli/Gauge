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

export function groupModelUsage(rows) {
  const groups = new Map();
  for (const row of rows) {
    const model = row.model || null;
    if (!groups.has(model)) groups.set(model, {model, calls: 0, input_tokens: 0, cached_input_tokens: 0, output_tokens: 0});
    const group = groups.get(model);
    group.calls++;
    for (const field of ['input_tokens', 'cached_input_tokens', 'output_tokens']) group[field] += row[field];
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

export function estimateCredits(groups) {
  let input = 0, cached = 0, output = 0, pricedCalls = 0, unpricedCalls = 0;
  const unpricedModels = new Set();
  for (const group of groups) {
    const rate = Object.hasOwn(CREDIT_RATES, group.model) ? CREDIT_RATES[group.model] : null;
    const valid = ['input_tokens', 'cached_input_tokens', 'output_tokens', 'calls'].every(key => Number.isSafeInteger(group[key]) && group[key] >= 0)
      && group.cached_input_tokens <= group.input_tokens;
    if (!rate || !valid) {
      unpricedCalls += Number.isSafeInteger(group.calls) && group.calls >= 0 ? group.calls : 1;
      unpricedModels.add(group.model || 'Model unavailable');
      continue;
    }
    // Cached input is already part of input_tokens: bill the remainder at the fresh rate.
    input += (group.input_tokens - group.cached_input_tokens) * rate.input / 1_000_000;
    cached += group.cached_input_tokens * rate.cached / 1_000_000;
    output += group.output_tokens * rate.output / 1_000_000;
    pricedCalls += group.calls;
  }
  return {input, cached, output, total: input + cached + output, pricedCalls, unpricedCalls,
    unpricedModels: [...unpricedModels], complete: unpricedModels.size === 0};
}
