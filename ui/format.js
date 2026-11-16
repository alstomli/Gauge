export function formatReuse(fraction) {
  if (fraction == null || !Number.isFinite(fraction)) return 'Unavailable';
  if (fraction > 0 && fraction < 0.00005) return '<0.01%';
  if (fraction < 1 && fraction >= 0.99995) return '>99.99%';
  return `${(100 * fraction).toFixed(2)}%`;
}
