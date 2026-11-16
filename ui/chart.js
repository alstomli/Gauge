// Fit the visible calls with padding and rounded ticks, bounded by 0–100%.
export function reuseScale(values) {
  const valid = values.filter(value => Number.isFinite(value) && value >= 0 && value <= 1);
  if (!valid.length) return {min: 0, max: 1, ticks: [0, .25, .5, .75, 1]};
  let low = 100, high = 0;
  for (const value of valid) {
    low = Math.min(low, value * 100);
    high = Math.max(high, value * 100);
  }
  const middle = (low + high) / 2;
  // A one-percentage-point minimum span avoids magnifying rounding noise.
  const span = Math.max(1, (high - low) * 1.2);
  low = Math.max(0, middle - span / 2);
  high = Math.min(100, middle + span / 2);
  const target = (high - low) / 4;
  const magnitude = 10 ** Math.floor(Math.log10(target));
  const step = [1, 2, 2.5, 5, 10].find(value => value * magnitude >= target) * magnitude;
  low = Math.max(0, Math.floor(low / step) * step);
  high = Math.min(100, Math.ceil(high / step) * step);
  const clean = value => Number((value / 100).toFixed(10));
  const ticks = [clean(low)];
  for (let index = Math.ceil(low / step); index * step < high; index++) {
    const tick = clean(index * step);
    if (tick > ticks[ticks.length - 1]) ticks.push(tick);
  }
  if (clean(high) > ticks[ticks.length - 1]) ticks.push(clean(high));
  return {min: ticks[0], max: ticks[ticks.length - 1], ticks};
}

export const axisPercent = value => `${Number((value * 100).toFixed(8))}%`;
